"""Cliente bridge v1 independiente de Home Assistant. Nunca reintenta escrituras."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlsplit

import aiohttp

DEFAULT_URL = "http://local-menu-compra:8099"


class BridgeError(Exception):
    """Error seguro para mostrar: no incluye URL, cabeceras ni cuerpo remoto."""

    def __init__(self, message: str, status: int = 0, data: Any = None):
        super().__init__(message)
        self.status = status
        self.data = data


class AuthenticationError(BridgeError):
    """Clave incorrecta, bridge revocado o desactivado."""


class ChoiceRequired(BridgeError):
    """Una compra ambigua no ha producido ninguna escritura."""


def normalize_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as err:
        raise ValueError("URL no válida") from err
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or parts.path
            or any(c.isspace() for c in value) or "\\" in value
            or (port is not None and port < 1)):
        raise ValueError("Indica solo http(s)://servidor:puerto, sin Ingress ni credenciales")
    return value


# Defensa adicional al servidor: ninguna acción expone un proxy HTTP arbitrario.
_ALLOWED = {
    "GET": re.compile(r"(?:health|bootstrap|categories|supermarkets|products(?:/matches|/[1-9]\d*)?|shopping|menu(?:/[1-9]\d*)?)\Z"),
    "POST": re.compile(r"(?:shopping/quick-add|shopping/items/[1-9]\d*/adjust|menu(?:/batch|/duplicate-week)?)\Z"),
    "PATCH": re.compile(r"shopping/items/[1-9]\d*\Z"),
    "PUT": re.compile(r"menu/[1-9]\d*\Z"),
    "DELETE": re.compile(r"(?:shopping(?:/checked|/items/[1-9]\d*)?|menu/[1-9]\d*)\Z"),
}


def identifier(value: Any) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError("El ID debe ser un entero positivo")
    return int(value)


class BridgeClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, api_key: str):
        self.session = session
        self.base_url = normalize_url(base_url)
        if not api_key or any(c.isspace() for c in api_key):
            raise ValueError("Clave no válida")
        self._api_key = api_key

    async def _request(self, method: str, path: str, *, body: Any = None,
                       params: dict | None = None) -> Any:
        if method not in _ALLOWED or not _ALLOWED[method].fullmatch(path):
            raise ValueError("Ruta o método no permitido")
        payload = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if payload is not None and len(payload) > 32768:
            raise ValueError("La petición supera 32 KiB")
        try:
            # aiohttp 3.12+ reintenta PUT/DELETE tras ServerDisconnectedError,
            # incluso en una sesión nueva. Desactivar ese mecanismo SOLO en la
            # sesión privada de escritura; no modificar la sesión compartida HA.
            # Este atributo interno se contrasta con aiohttp de HA y se cubre con
            # un servidor TCP que pierde la respuesta después de recibir el body.
            if method == "GET":
                return await self._exchange(self.session, method, path, payload, params)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),
                                             trust_env=False) as write_session:
                write_session._retry_connection = False
                return await self._exchange(write_session, method, path, payload, params)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            raise BridgeError("No se pudo completar la conexión. Si era una escritura, comprueba el resultado antes de repetir: no se ha reintentado.") from None

    async def _exchange(self, session, method, path, payload, params):
        async with session.request(
            method, f"{self.base_url}/bridge/v1/{path}", params=params,
            data=payload, headers={"Authorization": f"Bearer {self._api_key}",
                                    "Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False,
        ) as response:
            if response.status in (401, 403):
                raise AuthenticationError("Bridge desactivado o clave no válida; revisa la conexión en ajustes.", response.status)
            # Ni siquiera intentar decodificar un redirect; nunca seguir Location.
            if 300 <= response.status < 400:
                raise BridgeError("El servidor ha redirigido la petición; usa su URL interna directa.", response.status)
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise BridgeError("Respuesta del servidor demasiado grande.")
                chunks.append(chunk)
            raw = b"".join(chunks)
            try:
                data = json.loads(raw) if raw else {}
            except (ValueError, UnicodeDecodeError):
                raise BridgeError("El servidor no ha devuelto JSON válido.", response.status) from None
            if response.status == 409 and isinstance(data, dict) and data.get("status") == "choose":
                raise ChoiceRequired("Hay varios productos. Elige su supermercado.", 409, data)
            if response.status >= 400:
                messages = {404: "El elemento ya no existe.", 409: "La operación entra en conflicto con los datos actuales.",
                            422: "Los datos no son válidos o se ha alcanzado un límite.",
                            413: "La petición supera el tamaño permitido."}
                raise BridgeError(messages.get(response.status, "El servidor no pudo completar la operación."), response.status)
            return data

    async def health(self):
        data = await self._request("GET", "health")
        if not isinstance(data, dict) or data.get("status") != "ok" or data.get("version") not in {"0.6.0", "1.0.0"}:
            raise BridgeError("Se necesita un bridge compatible de Menú y Compra 0.6.0 o 1.0.0.")
        return data

    async def shopping(self):
        return await self._request("GET", "shopping")

    async def products(self, query: str = ""):
        return await self._request("GET", "products/matches" if query else "products",
                                   params={"name": query} if query else None)

    async def product(self, product_id: int):
        return await self._request("GET", f"products/{identifier(product_id)}")

    async def quick_add(self, name: str, quantity: float = 1, product_id: int | None = None,
                        price_cents: int | None = None):
        body = {"name": name, "quantity": quantity}
        if product_id is not None:
            body["product_id"] = identifier(product_id)
        if price_cents is not None:
            body["price_cents"] = price_cents
        return await self._request("POST", "shopping/quick-add", body=body)

    async def update_shopping(self, item_id: int, **fields):
        if not fields or set(fields) - {"checked", "quantity"}:
            raise ValueError("Indica checked o quantity")
        return await self._request("PATCH", f"shopping/items/{identifier(item_id)}", body=fields)

    async def adjust_shopping(self, item_id: int, delta: int):
        if type(delta) is not int or delta not in (-1, 1):
            raise ValueError("El ajuste debe ser -1 o 1")
        return await self._request("POST", f"shopping/items/{identifier(item_id)}/adjust", body={"delta": delta})

    async def remove_shopping(self, item_id: int):
        return await self._request("DELETE", f"shopping/items/{identifier(item_id)}")

    async def clear_shopping(self, checked_only: bool):
        return await self._request("DELETE", "shopping/checked" if checked_only else "shopping")

    async def menu(self, week: str):
        return await self._request("GET", "menu", params={"week": week})

    async def menu_entry(self, entry_id: int):
        return await self._request("GET", f"menu/{identifier(entry_id)}")

    async def add_menu(self, date: str, slot: str, text: str):
        return await self._request("POST", "menu", body={"date": date, "slot": slot, "text": text, "dish_id": None})

    async def update_menu(self, entry_id: int, date: str, slot: str, text: str):
        return await self._request("PUT", f"menu/{identifier(entry_id)}", body={"date": date, "slot": slot, "text": text, "dish_id": None})

    async def remove_menu(self, entry_id: int):
        return await self._request("DELETE", f"menu/{identifier(entry_id)}")

    async def add_menu_batch(self, date: str, slot: str, texts: list[str]):
        return await self._request("POST", "menu/batch", body={"date": date, "slot": slot, "texts": texts})

    async def duplicate_week(self, week: str):
        return await self._request("POST", "menu/duplicate-week", body={"week": week})
