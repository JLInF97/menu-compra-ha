"""Registro de acciones HA 2026.11.1: schemas probatio y respuestas explícitas."""
from __future__ import annotations

from datetime import datetime, timezone
import logging

import probatio as vol
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .actions import SERVICES, execute
from .api import BridgeError
from .settings import DOMAIN
from .telegram import Update, event_payload

SERVICE_NAMES = (*SERVICES, "telegram_update")
_LOGGER = logging.getLogger(__name__)
def whole_number(value):
    """Accept integral selector numbers, never truncate an ID, price or delta."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise vol.Invalid("Se necesita un número entero") from None
    if isinstance(value, bool) or (isinstance(value, str) and str(number) != value) or (not isinstance(value, str) and value != number):
        raise vol.Invalid("Se necesita un número entero, sin truncar ni corregir el valor")
    return number


ID = vol.All(whole_number, vol.Range(min=1, max=9223372036854775807))
TEXT = vol.All(cv.string, vol.Length(min=1, max=1000))
NAME = vol.All(cv.string, vol.Length(min=1, max=180))
CONFIRM = vol.All(cv.boolean, vol.In([True]))
SLOT = vol.In(["lunch", "dinner"])


def schemas():
    common = {vol.Required("config_entry_id"): cv.string}
    fields = {
        "get_shopping": {},
        "get_menu": {vol.Required("week"): cv.date},
        "get_products": {vol.Optional("name", default=""): cv.string},
        "add_shopping": {vol.Required("name"): NAME, vol.Optional("quantity", default=1): vol.Coerce(float),
                         vol.Optional("product_id"): ID, vol.Optional("price_cents"): vol.All(whole_number, vol.Range(min=0, max=100000000))},
        "update_shopping": {vol.Required("item_id"): ID, vol.Optional("quantity"): vol.Coerce(float), vol.Optional("checked"): cv.boolean},
        "adjust_shopping": {vol.Required("item_id"): ID, vol.Required("delta"): vol.All(whole_number, vol.In([-1, 1]))},
        "remove_shopping": {vol.Required("item_id"): ID, vol.Required("confirm"): CONFIRM},
        "clear_shopping": {vol.Required("checked_only"): cv.boolean, vol.Required("confirm"): CONFIRM},
        "add_menu": {vol.Required("date"): cv.date, vol.Required("slot"): SLOT, vol.Required("text"): TEXT},
        "update_menu": {vol.Required("entry_id"): ID, vol.Required("date"): cv.date, vol.Required("slot"): SLOT, vol.Required("text"): TEXT},
        "remove_menu": {vol.Required("entry_id"): ID, vol.Required("confirm"): CONFIRM},
        "add_menu_batch": {vol.Required("date"): cv.date, vol.Required("slot"): SLOT, vol.Required("texts"): vol.All([NAME], vol.Length(min=1, max=20))},
        "duplicate_week": {vol.Required("week"): cv.date, vol.Required("confirm"): CONFIRM},
        "telegram_update": {vol.Required("event_entity"): cv.entity_id, vol.Required("event_timestamp"): cv.string,
                            vol.Required("previous_timestamp"): cv.string, vol.Required("event_data"): dict},
    }
    return {name: vol.Schema({**common, **data}) for name, data in fields.items()}


async def telegram_update(hass, runtime, data):
    entity_id = data["event_entity"]
    if entity_id != runtime.router.event_entity or not entity_id.startswith("event."):
        raise ServiceValidationError("La entidad Telegram no coincide con la configurada")
    state = hass.states.get(entity_id)
    if state is None:
        return {"handled": False}
    try:
        timestamp = datetime.fromisoformat(data["event_timestamp"])
        previous = datetime.fromisoformat(data["previous_timestamp"])
        current = datetime.fromisoformat(state.state)
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        if timestamp <= previous or timestamp > current or age < -5 or age > 120:
            return {"handled": False}
    except (ValueError, TypeError):
        return {"handled": False}
    # Snapshot explícito del trigger: si llega otro update mientras la acción está
    # en cola no se pierde el anterior ni se usan sus datos con un timestamp nuevo.
    # Son datos de una acción HA autorizada, nunca un webhook público.
    attrs = event_payload(dict(data["event_data"]))
    if state.state == data["event_timestamp"] and attrs != event_payload(dict(state.attributes)):
        raise ServiceValidationError("Los datos no coinciden con el evento Telegram actual")
    if attrs.get("event_type") not in ("telegram_command", "telegram_callback"):
        return {"handled": False}
    # No confiar en bot.config_entry_id que venga de atributos o de un servicio.
    registry_entry = er.async_get(hass).async_get(entity_id)
    bot_entry = hass.config_entries.async_get_entry(registry_entry.config_entry_id) if registry_entry else None
    if not bot_entry or bot_entry.domain != "telegram_bot" or registry_entry.platform != "telegram_bot":
        raise ServiceValidationError("La entidad no pertenece a una entrada Telegram Bot")
    bot_info = attrs.get("bot")
    if isinstance(bot_info, dict) and bot_info.get("config_entry_id", bot_entry.entry_id) != bot_entry.entry_id:
        raise ServiceValidationError("El bot del evento no coincide con el registro de entidades")
    update = Update(entity_id, data["event_timestamp"], attrs["event_type"], attrs, bot_entry.entry_id)
    handled = await runtime.router.handle(update)
    if handled and attrs["event_type"] == "telegram_callback" and attrs.get("id"):
        try:
            await hass.services.async_call("telegram_bot", "answer_callback_query",
                                          {"config_entry_id": bot_entry.entry_id,
                                           "callback_query_id": str(attrs["id"])}, blocking=True)
        except HomeAssistantError:
            # An expired acknowledgement must not re-execute an already committed write.
            _LOGGER.debug("No se ha podido cerrar el aviso de un botón Telegram; no se repite la acción")
    return {"handled": handled}


@callback
def async_register(hass):
    if hass.services.has_service(DOMAIN, "get_shopping"):
        return

    async def handler(call):
        entry_id = call.data["config_entry_id"]
        runtime = hass.data.get(DOMAIN, {}).get(entry_id)
        if runtime is None:
            raise ServiceValidationError("Selecciona una entrada Menú y Compra cargada")
        try:
            if call.service == "telegram_update":
                return await telegram_update(hass, runtime, call.data)
            return await execute(runtime.client, call.service, dict(call.data))
        except BridgeError as err:
            raise HomeAssistantError(str(err)) from None
        except ValueError as err:
            raise ServiceValidationError(str(err)) from None

    for name, schema in schemas().items():
        hass.services.async_register(DOMAIN, name, handler, schema=schema,
                                     supports_response=SupportsResponse.OPTIONAL)
