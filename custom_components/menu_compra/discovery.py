"""Strict Supervisor discovery contract; credentials never become UI labels."""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from .api import normalize_url
from .settings import DOMAIN

_SLUG = re.compile(r"(?:local|[a-f0-9]{8})_menu_compra\Z")
_KEY = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_CONNECTION_FIELDS = ("base_url", "api_key", "app_slug", "protocol_version")


class DiscoveryError(ValueError):
    """Invalid or ambiguous announcement, without remote data in the error."""


class DiscoveryUnavailable(Exception):
    """Supervisor discovery cannot currently be read."""


@dataclass(frozen=True)
class AppDiscovery:
    slug: str
    base_url: str
    api_key: str = field(repr=False)
    protocol_version: int = 1

    def connection(self):
        return {"base_url": self.base_url, "api_key": self.api_key,
                "app_slug": self.slug, "protocol_version": self.protocol_version}


def parse_discovery(service, slug, config):
    """Accept only the canonical internal origin of this installed app."""
    if (service != DOMAIN or not isinstance(slug, str) or not _SLUG.fullmatch(slug)
            or not isinstance(config, dict)):
        raise DiscoveryError("Descubrimiento no válido")
    base_url = f"http://{slug.replace('_', '-')}:8099"
    key = config.get("api_key")
    if (type(config.get("protocol_version")) is not int or config["protocol_version"] != 1
            or config.get("base_url") != base_url
            or not isinstance(key, str) or not _KEY.fullmatch(key)):
        raise DiscoveryError("Descubrimiento no válido")
    return AppDiscovery(slug, base_url, key)


def parse_discoveries(records):
    """Read aiohasupervisor Discovery models, ignoring unrelated/bad services."""
    found = {}
    for record in records:
        if record.service != DOMAIN:
            continue
        try:
            app = parse_discovery(record.service, record.addon, record.config)
        except DiscoveryError:
            continue
        if app.slug in found and found[app.slug] != app:
            raise DiscoveryError("Descubrimientos contradictorios")
        found[app.slug] = app
    return [found[slug] for slug in sorted(found)]


async def async_discover(hass):
    """Use Core's authenticated client, never a browser URL or an app token."""
    if "hassio" not in hass.config.components:
        raise DiscoveryUnavailable("Supervisor no disponible")
    # Lazy import keeps manual setup working on non-supervised Core installs.
    from aiohasupervisor import SupervisorError
    from aiohttp import ClientError
    from homeassistant.components.hassio.handler import get_supervisor_client

    try:
        records = await get_supervisor_client(hass).discovery.list()
    except (SupervisorError, ClientError, OSError, TimeoutError, KeyError):
        raise DiscoveryUnavailable("No se pudo leer Supervisor") from None
    return parse_discoveries(records)


def matches_entry(app, entry):
    """A managed installation can never be silently replaced by another one."""
    current = {**entry.data, **entry.options}
    if current.get("app_slug"):
        return current["app_slug"] == app.slug
    try:
        return normalize_url(current.get("base_url", "")) == app.base_url
    except (ValueError, AttributeError):
        return False


def entry_update(app, entry):
    """Preserve every non-connection data/option, including Telegram settings."""
    if not matches_entry(app, entry):
        raise DiscoveryError("La entrada pertenece a otra instalación")
    connection = app.connection()
    data = {**entry.data, **connection}
    # Older options flows stored a complete settings snapshot. Refresh those
    # overrides too, otherwise they would mask the newly discovered credentials.
    options = dict(entry.options)
    options.update({key: connection[key] for key in _CONNECTION_FIELDS if key in options})
    return data, options
