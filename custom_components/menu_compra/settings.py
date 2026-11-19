"""Normalización de configuración, sin dependencias de Home Assistant."""
from __future__ import annotations

import re
from .api import DEFAULT_URL, normalize_url

DOMAIN = "menu_compra"


def allowed_chats(value) -> list[int]:
    if isinstance(value, str):
        values = re.split(r"[,\s]+", value.strip()) if value.strip() else []
    elif isinstance(value, (tuple, list)):
        values = value
    else:
        raise ValueError("Chats no válidos")
    chats = set()
    for item in values:
        if isinstance(item, bool) or not re.fullmatch(r"-?[1-9]\d*", str(item)):
            raise ValueError("Chats: usa IDs enteros separados por comas; los grupos pueden ser negativos")
        chats.add(int(item))
    if len(chats) > 100:
        raise ValueError("Máximo 100 chats permitidos")
    return sorted(chats)


def normalize_settings(data: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    api_key = data.get("api_key") or previous.get("api_key", "")
    if not isinstance(api_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", api_key):
        raise ValueError("Copia la clave bridge completa de Datos y ajustes")
    entity = data.get("telegram_event_entity", "") or ""
    if entity and not re.fullmatch(r"event\.[a-z0-9_]+", entity):
        raise ValueError("Selecciona una entidad event de Telegram")
    chats = allowed_chats(data.get("allowed_chats", ""))
    if chats and not entity:
        raise ValueError("Selecciona la entidad Telegram para habilitar chats")
    return {"base_url": normalize_url(data.get("base_url", previous.get("base_url", DEFAULT_URL))),
            "api_key": api_key, "telegram_event_entity": entity, "allowed_chats": chats}
