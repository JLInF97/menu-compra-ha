"""Conexión interna opt-in para HA. Independiente de Ingress y del catálogo.

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
        self._lock = RLock()
        self._enabled = False
        self._token = ""

    def load(self):
        with self._lock:
            self._enabled, self._token = False, ""
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
                pass
            except (OSError, ValueError, UnicodeError):
                # Fail closed without preventing use of the local shopping/menu UI.
                logging.getLogger(__name__).warning("Configuración de conexión HA no legible; conexión desactivada. Puede regenerarla en Datos y ajustes.")

    def _save(self, enabled, token):
        """Commit the file before publishing in-memory state; preserve it on errors."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".ha-bridge-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                os.chmod(temporary, 0o600)
                json.dump({"version": 1, "enabled": enabled, "token": token}, file)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            self._enabled, self._token = enabled, token
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def status(self):
        with self._lock:
            return {"enabled": self._enabled, "has_token": bool(self._token),
                    "base_url": "http://local-menu-compra:8099", "protocol_version": 1}

    def configure(self, enabled):
        with self._lock:
            token = self._token or (secrets.token_urlsafe(32) if enabled else "")
            self._save(enabled, token)
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
            return {"token": self._token}

    def authorized(self, authorization):
        with self._lock:
            scheme, _, supplied = authorization.partition(" ")
            if scheme.lower() != "bearer" or not self._enabled or not self._token:
                return False
            return hmac.compare_digest(supplied.encode("utf-8"), self._token.encode("ascii"))
