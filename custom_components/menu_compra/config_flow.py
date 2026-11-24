"""Flujos UI para Core 2026.11.1 (probatio, no voluptuous)."""
from __future__ import annotations

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import AuthenticationError, BridgeClient, BridgeError, DEFAULT_URL

from .discovery import (
    DiscoveryError, DiscoveryUnavailable, async_discover, entry_update,
    matches_entry, parse_discovery,
)
from .settings import DOMAIN, normalize_settings


def telegram_schema(current):
    """Normal options never expose connection credentials."""
    return vol.Schema({
        vol.Optional("telegram_event_entity", description={"suggested_value": current.get("telegram_event_entity", "")}): selector.EntitySelector(
            selector.EntitySelectorConfig(filter={"domain": "event", "integration": "telegram_bot"})),
        vol.Optional("allowed_chats", description={"suggested_value": ", ".join(str(c) for c in current.get("allowed_chats", []))}): selector.TextSelector(),
    })


def discovery_schema(apps):
    # Only validated installation slugs, never names, keys or remote model reprs.
    return vol.Schema({vol.Required("app_slug"): selector.SelectSelector(
        selector.SelectSelectorConfig(options=[app.slug for app in apps], mode="dropdown"))})


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
        """Prefer Supervisor; the credentials form is explicitly advanced."""
        try:
            apps = await async_discover(self.hass)
        except DiscoveryUnavailable:
            apps = []
        except DiscoveryError:
            return self.async_abort(reason="invalid_discovery")
        if apps:
            return await self._async_choose(apps)
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return self.async_show_menu(step_id="user", menu_options=["automatic", "manual"])

    async def async_step_hassio(self, discovery_info: HassioServiceInfo):
        """Core retrieves this service info over its authenticated Supervisor API."""
        try:
            app = parse_discovery(DOMAIN, discovery_info.slug, discovery_info.config)
        except DiscoveryError:
            return self.async_abort(reason="invalid_discovery")
        if self._async_current_entries():
            return await self._async_pair(app)
        try:
            apps = await async_discover(self.hass)
        except DiscoveryUnavailable:
            return self._automatic_form("supervisor_unavailable")
        except DiscoveryError:
            return self.async_abort(reason="invalid_discovery")
        same = next((item for item in apps if item.slug == app.slug), None)
        if same is not None and same != app:
            return self._automatic_form("discovery_changed")
        if same is None:
            apps.append(app)
        return await self._async_choose(apps)

    def _automatic_form(self, error):
        return self.async_show_form(step_id="automatic", data_schema=vol.Schema({}),
                                    errors={"base": error})

    async def async_step_automatic(self, user_input=None):
        try:
            apps = await async_discover(self.hass)
        except DiscoveryUnavailable:
            return self._automatic_form("supervisor_unavailable")
        except DiscoveryError:
            return self._automatic_form("invalid_discovery")
        if not apps:
            return self._automatic_form("no_discoveries")
        return await self._async_choose(apps)

    async def _async_choose(self, apps):
        entries = self._async_current_entries()
        if entries:
            matching = [app for app in apps if matches_entry(app, entries[0])]
            if not matching:
                return self.async_abort(reason="different_installation")
            apps = matching
        if len(apps) == 1:
            return await self._async_pair(apps[0])
        self._discovered_apps = apps
        return await self.async_step_select_app()

    async def async_step_select_app(self, user_input=None):
        apps = self._discovered_apps
        errors = {}
        if user_input is not None:
            slug = user_input.get("app_slug")
            if any(app.slug == slug for app in apps):
                # Re-read after the UI round-trip: rotation/removal invalidates
                # cached credentials, while the public selection remains a slug.
                try:
                    fresh = await async_discover(self.hass)
                except DiscoveryUnavailable:
                    return self._automatic_form("supervisor_unavailable")
                except DiscoveryError:
                    return self._automatic_form("invalid_discovery")
                app = next((item for item in fresh if item.slug == slug), None)
                if app is None:
                    return self._automatic_form("discovery_changed")
                return await self._async_pair(app)
            errors = {"base": "invalid_selection"}
        return self.async_show_form(step_id="select_app", data_schema=discovery_schema(apps), errors=errors)

    async def _async_pair(self, app):
        entries = self._async_current_entries()
        if entries and not matches_entry(app, entries[0]):
            return self.async_abort(reason="different_installation")
        try:
            await BridgeClient(async_get_clientsession(self.hass), app.base_url, app.api_key).health()
        except AuthenticationError:
            return self._automatic_form("invalid_auth")
        except BridgeError:
            return self._automatic_form("cannot_connect")
        # Health yielded; recheck the single-entry invariant before writing.
        entries = self._async_current_entries()
        if entries:
            entry = entries[0]
            try:
                data, options = entry_update(app, entry)
            except DiscoveryError:
                return self.async_abort(reason="different_installation")
            return self._finish_update(entry, data, options, reason="automatic_updated")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Menú y Compra", data={
            **app.connection(), "telegram_event_entity": "", "allowed_chats": []})

    async def async_step_manual(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            data, errors = await _checked(self.hass, user_input, {})
            if data is not None:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Menú y Compra", data=data)
        return self.async_show_form(step_id="manual", data_schema=form_schema({}, initial=True), errors=errors)

    async def _async_refresh_managed(self, entry):
        try:
            apps = await async_discover(self.hass)
        except DiscoveryUnavailable:
            return self._automatic_form("supervisor_unavailable")
        except DiscoveryError:
            return self._automatic_form("invalid_discovery")
        app = next((app for app in apps if matches_entry(app, entry)), None)
        if app is None:
            return self._automatic_form("no_discoveries")
        return await self._async_pair(app)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        if entry.data.get("app_slug") or entry.options.get("app_slug"):
            return await self._async_refresh_managed(entry)
        return await self._async_manual_update(entry, "reconfigure", user_input)

    def _finish_update(self, entry, data, options, *, reason=None):
        kwargs = {"data": data, "options": options, "unique_id": DOMAIN}
        if reason is not None:
            kwargs["reason"] = reason
        # Loaded entries already have our reload listener. Failed setup/reauth
        # entries may not: explicitly schedule their retry without double reloads.
        if entry.update_listeners:
            return self.async_update_and_abort(entry, **kwargs)
        return self.async_update_reload_and_abort(entry,
            reload_even_if_entry_is_unchanged=False, **kwargs)

    async def _async_manual_update(self, entry, step_id, user_input):
        current = {**entry.data, **entry.options}
        errors = {}
        if user_input is not None:
            data, errors = await _checked(self.hass, user_input, current)
            if data is not None:
                return self._finish_update(entry, {**entry.data, **data},
                    {**entry.options, **data})
        return self.async_show_form(step_id=step_id, data_schema=form_schema(current), errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        if entry.data.get("app_slug") or entry.options.get("app_slug"):
            return await self._async_refresh_managed(entry)
        return await self._async_manual_update(entry, "reauth_confirm", user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MenuCompraOptionsFlow()


class MenuCompraOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["telegram", "advanced"])

    async def async_step_telegram(self, user_input=None):
        current = {**self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            data, errors = await _checked(self.hass, user_input, current)
            if data is not None:
                return self.async_create_entry(title="", data={**self.config_entry.options,
                    "telegram_event_entity": data["telegram_event_entity"],
                    "allowed_chats": data["allowed_chats"]})
        return self.async_show_form(step_id="telegram", data_schema=telegram_schema(current), errors=errors)

    async def async_step_advanced(self, user_input=None):
        current = {**self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            if current.get("app_slug") and user_input.get("base_url", current["base_url"]) != current["base_url"]:
                errors = {"base": "different_installation"}
            else:
                data, errors = await _checked(self.hass, user_input, current)
                if data is not None:
                    return self.async_create_entry(title="", data={**self.config_entry.options, **data})
        return self.async_show_form(step_id="advanced", data_schema=form_schema(current), errors=errors)
