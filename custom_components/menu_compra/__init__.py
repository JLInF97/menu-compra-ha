"""Menú y Compra 1.1.0: acciones locales sin entidades ni polling."""
from __future__ import annotations
from dataclasses import dataclass

from .api import AuthenticationError, BridgeClient, BridgeError
from .settings import DOMAIN
from .telegram import TelegramRouter


@dataclass
class Runtime:
    client: BridgeClient
    router: TelegramRouter


async def async_setup_entry(hass, entry):
    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.util import dt as dt_util
    from .services import async_register

    settings = {**entry.data, **entry.options}
    client = BridgeClient(async_get_clientsession(hass), settings["base_url"], settings["api_key"])
    try:
        await client.health()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from None
    except BridgeError as err:
        raise ConfigEntryNotReady(str(err)) from None

    async def send(update, payload):
        # Destino explícito derivado del registro, nunca el primer bot del sistema.
        await hass.services.async_call("telegram_bot", "send_message", payload, blocking=True)

    router = TelegramRouter(client, settings.get("telegram_event_entity", ""),
                            set(settings.get("allowed_chats", [])), send,
                            today=lambda: dt_util.now().date())
    entry.runtime_data = Runtime(client, router)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.runtime_data
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    async_register(hass)
    return True


async def _options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    from .services import SERVICE_NAMES
    loaded = hass.data.get(DOMAIN, {})
    loaded.pop(entry.entry_id, None)
    if not loaded:
        for service in SERVICE_NAMES:
            hass.services.async_remove(DOMAIN, service)
    return True
