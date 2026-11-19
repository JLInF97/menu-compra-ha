"""Copias JSON portables. Restauración validada y completamente atómica."""
from datetime import date, datetime
from copy import deepcopy
from collections import Counter
from pydantic import TypeAdapter
from .db import TABLES, now, sync_shopping_products, ensure_system_metadata
from .models import CategoryIn, SupermarketIn, ProductIn, PriceIn, Quantity, DishIn

FORMAT = "menu-compra"
COLUMNS = {
    "categories": {"id", "name", "sort_order", "is_frozen"},
    "supermarkets": {"id", "name"},
    "products": {"id", "name", "category_id", "supermarket_id", "unit", "notes", "price_cents", "active", "updated_at"},
    "price_history": {"id", "product_id", "supermarket_id", "price_cents", "recorded_at", "source", "supermarket_name_snapshot"},
    "dishes": {"id", "name", "notes"},
    "dish_ingredients": {"dish_id", "product_id", "quantity"},
    "menu_entries": {"id", "date", "slot", "text", "dish_id", "position"},
    "shopping_items": {"id", "product_id", "supermarket_id", "unit", "quantity", "checked", "note", "unit_price_cents"},
}


def export_data(connection):
    return {"format": FORMAT, "version": 3, "exported_at": now(), "tables": {
        table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
        for table in TABLES
    }}


def validate_backup(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT or type(data.get("version")) is not int or data["version"] not in (1, 2, 3):
        raise ValueError("Formato o versión de copia no compatible")
    tables = deepcopy(data.get("tables"))
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise ValueError("Faltan tablas o hay tablas desconocidas en la copia")
    count = 0
    for table in TABLES:
        rows = tables[table]
        if not isinstance(rows, list):
            raise ValueError(f"Tabla inválida: {table}")
        count += len(rows)
        if count > 100000:
            raise ValueError("La copia supera el límite de 100.000 registros")
        for row in rows:
            if data["version"] < 3 and table == "price_history":
                if not isinstance(row, dict) or set(row) != COLUMNS[table] - {"supermarket_name_snapshot"}:
                    raise ValueError("Columnas del historial antiguo no válidas")
                row["supermarket_name_snapshot"] = None
            if data["version"] == 1 and table == "menu_entries":
                if not isinstance(row, dict) or set(row) != COLUMNS[table] - {"position"}:
                    raise ValueError("Columnas del menú antiguo no válidas")
                row["position"] = 0
            if not isinstance(row, dict) or set(row) != COLUMNS[table]:
                raise ValueError(f"Columnas no válidas: {table}")
            for key, value in row.items():
                if key == "id" or key.endswith("_id"):
                    if key == "dish_id" and table == "menu_entries" and value is None:
                        continue
                    if type(value) is not int or not 0 < value <= 9_223_372_036_854_775_807:
                        raise ValueError(f"Identificador inválido: {table}.{key}")
            if table == "categories":
                normalized = CategoryIn.model_validate({k: row[k] for k in ("name", "sort_order", "is_frozen")})
                if row["is_frozen"] not in (0, 1) or type(row["is_frozen"]) not in (int, bool):
                    raise ValueError("Indicador de congelados inválido")
                row.update(normalized.model_dump())
            elif table == "supermarkets":
                row.update(SupermarketIn.model_validate({"name": row["name"]}).model_dump())
            elif table == "products":
                row.update(ProductIn.model_validate({k: row[k] for k in ProductIn.model_fields}).model_dump())
                if row["active"] not in (0, 1) or type(row["active"]) not in (int, bool):
                    raise ValueError("Estado de producto inválido")
                row["active"] = 1
                datetime.fromisoformat(row["updated_at"])
            elif table == "price_history":
                PriceIn.model_validate({"price_cents": row["price_cents"]})
                datetime.fromisoformat(row["recorded_at"])
                if not isinstance(row["source"], str) or not 1 <= len(row["source"]) <= 100:
                    raise ValueError("Origen de precio inválido")
                snapshot = row["supermarket_name_snapshot"]
                if snapshot is not None:
                    if not isinstance(snapshot, str) or not 1 <= len(snapshot.strip()) <= 180:
                        raise ValueError("Nombre histórico de supermercado inválido")
                    row["supermarket_name_snapshot"] = snapshot.strip()
            elif table == "dishes":
                normalized = DishIn.model_validate({"name": row["name"], "notes": row["notes"]})
                row.update(name=normalized.name, notes=normalized.notes)
            elif table in ("dish_ingredients", "shopping_items"):
                row["quantity"] = str(TypeAdapter(Quantity).validate_python(row["quantity"]))
                if table == "shopping_items":
                    PriceIn.model_validate({"price_cents": row["unit_price_cents"]})
                    if not isinstance(row["unit"], str) or not 1 <= len(row["unit"].strip()) <= 20:
                        raise ValueError("Unidad de compra inválida")
                    row["unit"] = row["unit"].strip()
                    if row["checked"] not in (0, 1) or type(row["checked"]) not in (int, bool):
                        raise ValueError("Estado de compra inválido")
                    if not isinstance(row["note"], str) or len(row["note"]) > 1000:
                        raise ValueError("Nota de compra inválida")
            elif table == "menu_entries":
                if date.fromisoformat(row["date"]).isoformat() != row["date"] or row["slot"] not in ("lunch", "dinner"):
                    raise ValueError("Fecha o turno del menú inválido")
                if not isinstance(row["text"], str) or not 1 <= len(row["text"]) <= 1000:
                    raise ValueError("Texto del menú inválido")
                if type(row["position"]) is not int or not 0 <= row["position"] <= 1_000_000:
                    raise ValueError("Orden del plato inválido")
    if any(count > 20 for count in Counter((row["date"], row["slot"]) for row in tables["menu_entries"]).values()):
        raise ValueError("El menú supera los 20 platos por comida o cena")
    if tables["products"] and (not tables["categories"] or not tables["supermarkets"]):
        raise ValueError("La copia debe incluir categorías y supermercados")
    return tables


def restore_data(connection, data):
    tables = validate_backup(data)
    for table in reversed(TABLES):
        connection.execute(f"DELETE FROM {table}")
    for table in TABLES:
        for row in tables[table]:
            columns = sorted(COLUMNS[table])
            placeholders = ",".join("?" for _ in columns)
            connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", [row[column] for column in columns])
    for product in connection.execute("SELECT * FROM products"):
        history = connection.execute("SELECT * FROM price_history WHERE product_id=? ORDER BY id DESC LIMIT 1", (product["id"],)).fetchone()
        if history is None or (history["price_cents"], history["supermarket_id"]) != (product["price_cents"], product["supermarket_id"]):
            raise ValueError("El historial no coincide con el precio o supermercado actual")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Hay referencias a registros inexistentes")
    ensure_system_metadata(connection)
    sync_shopping_products(connection)
    return {"restored": True, "counts": {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}}
