"""Flujos UI para Core 2026.11.1 (probatio, no voluptuous)."""
from __future__ import annotations

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import entity_registry as er, selector

from .api import AuthenticationError, BridgeClient, BridgeError, DEFAULT_URL
from .settings import DOMAIN, normalize_settings


def form_schema(current, *, initial=False):
    fields = {
        vol.Required("base_url", default=current.get("base_url", DEFAULT_URL)): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)),
        (vol.Required(vol.Secret("api_key")) if initial else vol.Optional(vol.Secret("api_key"))): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD, autocomplete="off")),
        vol.Optional("telegram_event_entity", description={"suggested_value": current.get("telegram_event_entity", "")}): selector.EntitySelector(
            selector.EntitySelectorConfig(filter={"domain": "event", "integration": "telegram_bot"})),
        vol.Optional("allowed_chats", description={"suggested_value": ", ".join(str(c) for c in current.get("allowed_chats", []))}): selector.TextSelector(),
    }
    return vol.Schema(fields)


async def validate(hass, data, previous=None):
    result = normalize_settings(data, previous)
    entity = result["telegram_event_entity"]
    if entity:
        registry_entry = er.async_get(hass).async_get(entity)
        bot_entry = hass.config_entries.async_get_entry(registry_entry.config_entry_id) if registry_entry else None
        if not bot_entry or bot_entry.domain != "telegram_bot" or registry_entry.platform != "telegram_bot":
            raise ValueError("La entidad no pertenece a Telegram Bot")
    await BridgeClient(async_get_clientsession(hass), result["base_url"], result["api_key"]).health()
    return result


async def _checked(hass, user_input, current):
    try:
        return await validate(hass, user_input, current), {}
    except AuthenticationError:
        return None, {"base": "invalid_auth"}
    except BridgeError:
        return None, {"base": "cannot_connect"}
    except ValueError:
        return None, {"base": "invalid_settings"}


class MenuCompraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            data, errors = await _checked(self.hass, user_input, {})
            if data is not None:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Menú y Compra", data=data)
        return self.async_show_form(step_id="user", data_schema=form_schema({}, initial=True), errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        current = {**entry.data, **entry.options}
        errors = {}
        if user_input is not None:
            data, errors = await _checked(self.hass, user_input, current)
            if data is not None:
                return self.async_update_reload_and_abort(entry, data=data, options={})
        return self.async_show_form(step_id="reconfigure", data_schema=form_schema(current), errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        current = {**entry.data, **entry.options}
        errors = {}
        if user_input is not None:
            data, errors = await _checked(self.hass, user_input, current)
            if data is not None:
                return self.async_update_reload_and_abort(entry, data=data, options={})
        return self.async_show_form(step_id="reauth_confirm", data_schema=form_schema(current), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MenuCompraOptionsFlow()


class MenuCompraOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        current = {**self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            data, errors = await _checked(self.hass, user_input, current)
            if data is not None:
                return self.async_create_entry(title="", data=data)
        return self.async_show_form(step_id="init", data_schema=form_schema(current), errors=errors)
