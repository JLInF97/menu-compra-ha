"""Conexión interna para HA. Independiente de Ingress y del catálogo.

La clave solo se devuelve mediante una acción explícita dentro de Ingress.
El JSON privado vive en /data, no en las copias de datos descargables.
"""
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
from threading import RLock

from pydantic import BaseModel, ConfigDict, StrictBool

from .supervisor_discovery import valid_record

PREFIX = "/bridge/v1/"
BODY_LIMIT = 32 * 1024
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
ROUTES = {
    "GET": re.compile(r"(?:health|bootstrap|categories|supermarkets|products(?:/matches|/[1-9][0-9]*)?|shopping|menu(?:/[1-9][0-9]*)?)\Z"),
    "POST": re.compile(r"(?:shopping/quick-add|shopping/items/[1-9][0-9]*/adjust|menu(?:/batch|/duplicate-week)?)\Z"),
    "PATCH": re.compile(r"shopping/items/[1-9][0-9]*\Z"),
    "PUT": re.compile(r"menu/[1-9][0-9]*\Z"),
    "DELETE": re.compile(r"(?:shopping(?:/checked|/items/[1-9][0-9]*)?|menu/[1-9][0-9]*)\Z"),
}


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


def bridge_target(path, method):
    """Only a fixed allowlist can be forwarded to the existing domain API."""
    if not path.startswith(PREFIX):
        return None
    suffix = path[len(PREFIX):]
    pattern = ROUTES.get(method)
    return "/api/" + suffix if pattern is not None and pattern.fullmatch(suffix) else None


class BridgeState:
    def __init__(self, directory):
        self.path = Path(directory) / "ha_bridge.json"
        self.discovery_path = Path(directory) / "ha_discovery.json"
        self.discovery_error = False
        self._lock = RLock()
        self._enabled = False
        self._token = ""
        self._discovery = None
        self._automatic = False
        self._base_url = ""
        self._discovery_state = "unavailable"
        self.on_change = None

    def load(self, automatic=False):
        with self._lock:
            self._enabled, self._token = False, ""
            self._discovery = None
            self._automatic = automatic
            self._base_url = ""
            try:
                with self.path.open("r", encoding="utf-8") as file:
                    text = file.read(8193)
                if len(text) > 8192:
                    raise ValueError("oversized")
                data = json.loads(text)
                if (not isinstance(data, dict) or data.get("version") != 1
                        or type(data.get("enabled")) is not bool
                        or not isinstance(data.get("token"), str)
                        or (data["token"] and TOKEN_PATTERN.fullmatch(data["token"]) is None)
                        or (data["enabled"] and not data["token"])):
                    raise ValueError("invalid state")
                self._enabled, self._token = data["enabled"], data["token"]

            except FileNotFoundError:
                if automatic:
                    try:
                        self._save(True, secrets.token_urlsafe(32))
                    except OSError:
                        logging.getLogger(__name__).warning("No se ha podido activar la conexión HA; conexión desactivada.")
            except (OSError, ValueError, UnicodeError, RecursionError):
                # Fail closed without preventing use of the local shopping/menu UI.
                logging.getLogger(__name__).warning("Configuración de conexión HA no legible; conexión desactivada. Puede regenerarla en Datos y ajustes.")
            self._discovery_state = ("pending" if self._enabled else "disabled") if automatic else "unavailable"
            self.discovery_error = False
            try:
                with self.discovery_path.open("r", encoding="utf-8") as file:
                    text = file.read(8193)
                record = json.loads(text)
                if len(text) > 8192 or not valid_record(record):
                    raise ValueError("invalid discovery journal")
                self._discovery = record
            except FileNotFoundError:
                pass
            except (OSError, ValueError, UnicodeError, RecursionError):
                self.discovery_error = True
                logging.getLogger(__name__).warning("Registro privado de descubrimiento HA no legible; anuncio suspendido.")

    @staticmethod
    def _write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".ha-bridge-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                os.chmod(temporary, 0o600)
                json.dump(data, file)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _save(self, enabled, token):
        """Commit the original three-field schema before publishing memory."""
        self._write_json(self.path, {"version": 1, "enabled": enabled, "token": token})
        self._enabled, self._token = enabled, token

    def status(self):
        with self._lock:
            return {"enabled": self._enabled, "has_token": bool(self._token),
                    "base_url": self._base_url, "protocol_version": 1,
                    "automatic": self._automatic, "discovery_state": self._discovery_state}

    def discovery_snapshot(self):
        """Private worker snapshot; never return this from an HTTP route."""
        with self._lock:
            return self._enabled, self._token, self._discovery

    def record_discovery(self, record):
        with self._lock:
            if record is None:
                try:
                    self.discovery_path.unlink()
                except FileNotFoundError:
                    pass
            else:
                if not valid_record(record):
                    raise ValueError("Invalid private discovery record")
                self._write_json(self.discovery_path, record)
            self._discovery = record

    def discovery_status(self, state, base_url=None, *, expected=None):
        with self._lock:
            if base_url is not None:
                self._base_url = base_url
            if expected is not None and expected != (self._enabled, self._token):
                return
            self._discovery_state = state

    def _changed(self):
        if self._automatic:
            self._discovery_state = "pending" if self._enabled else "disabled"
        if self.on_change is not None:
            self.on_change()

    def configure(self, enabled):
        with self._lock:
            token = self._token or (secrets.token_urlsafe(32) if enabled else "")
            self._save(enabled, token)
            self._changed()
            return self.status()

    def reveal(self):
        with self._lock:
            if not self._enabled:
                raise ValueError("Activa primero la conexión con Home Assistant.")
            return {"token": self._token}

    def rotate(self):
        with self._lock:
            if not self._enabled:
                raise ValueError("Activa primero la conexión con Home Assistant.")
            self._save(True, secrets.token_urlsafe(32))
            self._changed()
            return {"token": self._token}

    def authorized(self, authorization):
        with self._lock:
            scheme, _, supplied = authorization.partition(" ")
            if scheme.lower() != "bearer" or not self._enabled or not self._token:
                return False
            return hmac.compare_digest(supplied.encode("utf-8"), self._token.encode("ascii"))
