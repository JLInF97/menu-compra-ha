"""Acciones de dominio, reutilizables y verificables sin Home Assistant."""
from __future__ import annotations
from datetime import date
import math

from .api import BridgeClient, ChoiceRequired, identifier

SERVICES = ("get_shopping", "get_menu", "get_products", "add_shopping", "update_shopping", "adjust_shopping",
            "remove_shopping", "clear_shopping", "add_menu", "update_menu", "remove_menu", "add_menu_batch", "duplicate_week")


def iso_date(value):
    text = str(value)
    if len(text) != 10:
        raise ValueError("Fecha no válida: usa YYYY-MM-DD")
    return date.fromisoformat(text).isoformat()


def quantity(value):
    if isinstance(value, bool):
        raise ValueError("Cantidad no válida")
    result = float(value)
    if not math.isfinite(result) or not 0 < result <= 100000:
        raise ValueError("Cantidad: mayor que cero y no superior a 100000")
    return result


def confirmed(data):
    if data.get("confirm") is not True:
        raise ValueError("Esta acción requiere confirm: true")


async def execute(client: BridgeClient, action: str, data: dict):
    if action == "get_shopping":
        result = await client.shopping()
    elif action == "get_menu":
        result = await client.menu(iso_date(data["week"]))
    elif action == "get_products":
        result = await client.products(data.get("name", ""))
    elif action == "add_shopping":
        try:
            result = await client.quick_add(data["name"], quantity(data.get("quantity", 1)), data.get("product_id"), data.get("price_cents"))
        except ChoiceRequired as err:
            # Respuesta explícita, NO una falsa confirmación de escritura.
            return {"status": "choose", "written": False, "matches": err.data["matches"]}
    elif action == "update_shopping":
        fields = {k: data[k] for k in ("quantity", "checked") if k in data}
        if "quantity" in fields:
            fields["quantity"] = quantity(fields["quantity"])
        if "checked" in fields and type(fields["checked"]) is not bool:
            raise ValueError("checked debe ser booleano")
        result = await client.update_shopping(identifier(data["item_id"]), **fields)
    elif action == "adjust_shopping":
        result = await client.adjust_shopping(identifier(data["item_id"]), data["delta"])
    elif action == "remove_shopping":
        confirmed(data)
        result = await client.remove_shopping(identifier(data["item_id"]))
    elif action == "clear_shopping":
        confirmed(data)
        if type(data["checked_only"]) is not bool:
            raise ValueError("checked_only debe ser booleano")
        result = await client.clear_shopping(data["checked_only"])
    elif action in ("add_menu", "update_menu", "add_menu_batch"):
        day, slot = iso_date(data["date"]), data["slot"]
        if slot not in ("lunch", "dinner"):
            raise ValueError("La franja debe ser lunch o dinner")
        if action == "add_menu_batch":
            texts = data["texts"]
            if not isinstance(texts, list) or not 1 <= len(texts) <= 20 or any(not isinstance(t, str) or not t.strip() or len(t) > 180 for t in texts):
                raise ValueError("Indica entre 1 y 20 platos, cada uno de 1 a 180 caracteres")
            result = await client.add_menu_batch(day, slot, texts)
        else:
            text = data["text"].strip()
            if not text or len(text) > 1000:
                raise ValueError("El plato debe tener de 1 a 1000 caracteres")
            if action == "add_menu":
                result = await client.add_menu(day, slot, text)
            else:
                result = await client.update_menu(identifier(data["entry_id"]), day, slot, text)
    elif action == "remove_menu":
        confirmed(data)
        result = await client.remove_menu(identifier(data["entry_id"]))
    elif action == "duplicate_week":
        confirmed(data)
        result = await client.duplicate_week(iso_date(data["week"]))
    else:
        raise ValueError("Acción no permitida")
    # Home Assistant admite solo diccionarios como respuesta del servicio.
    return result if isinstance(result, dict) else {"result": result}
