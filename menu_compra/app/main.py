"""Menú y Compra: aplicación local para Home Assistant Ingress."""
from contextlib import asynccontextmanager
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import asyncio
import logging
import os
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .backup import export_data, restore_data
from .db import Database, now, sync_shopping_products, ensure_system_metadata
from .ha_bridge import BridgeState, BridgeConfig, bridge_target, BODY_LIMIT
from .models import CategoryIn, SupermarketIn, ProductIn, PriceIn, ShoppingIn, ShoppingPatch, DishIn, MenuIn, IngredientSelection, MenuBatchIn, MenuShoppingIn, QuickShoppingIn, DuplicateWeekIn, ShoppingAdjustIn
from .supervisor_discovery import SupervisorDiscovery, SupervisorTransport, INTERVAL, local_http_ready

VERSION = "1.1.0"
STATIC = Path(__file__).parent / "static"
PRODUCT_SELECT = """SELECT p.*,c.name AS category_name,c.is_frozen,s.name AS supermarket_name
 FROM products p JOIN categories c ON p.category_id=c.id
 JOIN supermarkets s ON p.supermarket_id=s.id"""


def require_row(connection, table, row_id):
    row = connection.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No se ha encontrado el registro")
    return row


def product_json(row):
    result = dict(row)
    result["active"] = bool(result["active"])
    result["is_frozen"] = bool(result["is_frozen"])
    return result


def product_detail(connection, product_id):
    row = connection.execute(PRODUCT_SELECT + " WHERE p.id=?", (product_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Producto no encontrado")
    result = product_json(row)
    result["price_history"] = [{**dict(r), "supermarket_deleted": r["supermarket_name_snapshot"] is not None} for r in connection.execute("""SELECT h.id,h.price_cents,h.recorded_at,h.source,h.supermarket_id,h.supermarket_name_snapshot,COALESCE(h.supermarket_name_snapshot,s.name) AS supermarket_name
      FROM price_history h JOIN supermarkets s ON h.supermarket_id=s.id WHERE h.product_id=? ORDER BY h.id DESC""", (product_id,))]
    return result


def categories_json(connection):
    return [{**dict(r), "is_frozen": bool(r["is_frozen"]), **({"is_system": True} if r["name"].casefold() == "sin especificar" else {})} for r in connection.execute("SELECT * FROM categories ORDER BY is_frozen,sort_order,name COLLATE NOCASE")]


def supermarkets_json(connection):
    return [{**dict(r), **({"is_system": True} if r["name"].casefold() == "sin especificar" else {})} for r in connection.execute("SELECT * FROM supermarkets ORDER BY name COLLATE NOCASE")]


def products_json(connection, q="", category_id=None, supermarket_id=None, include_archived=False):
    clauses = [] if include_archived else ["p.active=1"]
    params = []
    if q:
        clauses.append("(instr(casefold(p.name),casefold(?))>0 OR instr(casefold(p.notes),casefold(?))>0)")
        params += [q, q]
    for column, value in (("category_id", category_id), ("supermarket_id", supermarket_id)):
        if value is not None:
            clauses.append(f"p.{column}=?")
            params.append(value)
    sql = PRODUCT_SELECT + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY p.name COLLATE NOCASE,s.name COLLATE NOCASE,p.id"
    return [product_json(r) for r in connection.execute(sql, params)]


def update_price(connection, product_id, price_cents, source, force=False):
    product = require_row(connection, "products", product_id)
    if force or product["price_cents"] != price_cents:
        timestamp = now()
        connection.execute("UPDATE products SET price_cents=?,updated_at=? WHERE id=?", (price_cents, timestamp, product_id))
        connection.execute("INSERT INTO price_history(product_id,supermarket_id,price_cents,recorded_at,source) VALUES(?,?,?,?,?)", (product_id, product["supermarket_id"], price_cents, timestamp, source))
    sync_shopping_products(connection, product_id)


def shopping_json(connection):
    rows = connection.execute("""SELECT i.*,p.name AS product_name,p.category_id,
      c.name AS category_name,c.is_frozen,s.name AS supermarket_name
      FROM shopping_items i JOIN products p ON p.id=i.product_id
      JOIN categories c ON c.id=p.category_id JOIN supermarkets s ON s.id=i.supermarket_id
      ORDER BY c.is_frozen,c.sort_order,c.name COLLATE NOCASE,p.name COLLATE NOCASE,i.id""")
    groups = {}
    total = checked_total = count = checked_count = 0
    for row in rows:
        item = dict(row)
        quantity = Decimal(item["quantity"])
        subtotal = int((quantity * item["unit_price_cents"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        item.update(quantity=float(quantity), checked=bool(item["checked"]), is_frozen=bool(item["is_frozen"]), subtotal_cents=subtotal)
        category_id = item["category_id"]
        if category_id not in groups:
            groups[category_id] = {"category_id": category_id, "name": item["category_name"], "is_frozen": item["is_frozen"], "items": []}
        groups[category_id]["items"].append(item)
        total += subtotal
        count += 1
        if item["checked"]:
            checked_total += subtotal
            checked_count += 1
    return {"groups": list(groups.values()), "total_cents": total, "pending_total_cents": total-checked_total, "checked_total_cents": checked_total, "count": count, "checked_count": checked_count}


def add_shopping(connection, product_id, quantity, price_cents=None, note=""):
    product = require_row(connection, "products", product_id)
    if not product["active"]:
        raise HTTPException(400, "El producto no está disponible. Vuelve a cargar el catálogo.")
    if price_cents is not None:
        update_price(connection, product_id, price_cents, "lista")
    price = product["price_cents"] if price_cents is None else price_cents
    existing = connection.execute("SELECT * FROM shopping_items WHERE product_id=?", (product_id,)).fetchone()
    quantity = Decimal(quantity)
    if existing:
        if not existing["checked"]:
            quantity += Decimal(existing["quantity"])
        if quantity > 100000:
            raise HTTPException(422, "La cantidad acumulada supera el límite de 100.000 unidades")
        connection.execute("UPDATE shopping_items SET quantity=?,checked=0,unit_price_cents=?,supermarket_id=?,unit=?,note=? WHERE id=?", (str(quantity), price, product["supermarket_id"], product["unit"], note or existing["note"], existing["id"]))
    else:
        connection.execute("INSERT INTO shopping_items(product_id,supermarket_id,unit,quantity,note,unit_price_cents) VALUES(?,?,?,?,?,?)", (product_id, product["supermarket_id"], product["unit"], str(quantity), note, price))


def dishes_json(connection, q=""):
    dishes = []
    sql = "SELECT * FROM dishes" + (" WHERE instr(casefold(name),casefold(?))>0" if q else "") + " ORDER BY name COLLATE NOCASE"
    for row in connection.execute(sql, (q,) if q else ()):
        dish = dict(row)
        dish["ingredients"] = [{**dict(i), "quantity": float(Decimal(i["quantity"]))} for i in connection.execute("""SELECT i.product_id,i.quantity,p.name AS product_name,p.unit,s.name AS supermarket_name
          FROM dish_ingredients i JOIN products p ON p.id=i.product_id JOIN supermarkets s ON s.id=p.supermarket_id
          WHERE i.dish_id=? ORDER BY p.name COLLATE NOCASE""", (dish["id"],))]
        dishes.append(dish)
    return dishes


def save_ingredients(connection, dish_id, ingredients):
    for ingredient in ingredients:
        product = require_row(connection, "products", ingredient.product_id)
        if not product["active"]:
            raise HTTPException(400, "No se puede asociar un ingrediente archivado")
    connection.execute("DELETE FROM dish_ingredients WHERE dish_id=?", (dish_id,))
    connection.executemany("INSERT INTO dish_ingredients(dish_id,product_id,quantity) VALUES(?,?,?)", [(dish_id, i.product_id, str(i.quantity)) for i in ingredients])


def menu_text(connection, data):
    text = data.text
    if data.dish_id is not None:
        legacy = require_row(connection, "dishes", data.dish_id)
        text = text or legacy["name"]
    return text


def menu_position(connection, day, slot):
    count, maximum = connection.execute("SELECT COUNT(*),MAX(position) FROM menu_entries WHERE date=? AND slot=?", (day, slot)).fetchone()
    if count >= 20:
        raise HTTPException(409, "Esta comida ya tiene 20 platos. Elimina alguno antes de añadir otro.")
    return 0 if maximum is None else maximum + 1


def create_menu_row(connection, day, slot, text, dish_id=None):
    if not text:
        raise HTTPException(422, "Escribe el nombre del plato")
    position = menu_position(connection, day, slot)
    row_id = connection.execute("INSERT INTO menu_entries(date,slot,text,dish_id,position) VALUES(?,?,?,?,?)", (day, slot, text, dish_id, position)).lastrowid
    return dict(require_row(connection, "menu_entries", row_id))


def menu_product_matches(connection, entry_id):
    entry = require_row(connection, "menu_entries", entry_id)
    name = entry["text"].strip()
    order = " ORDER BY p.name COLLATE NOCASE,s.name COLLATE NOCASE,p.id"
    exact = [product_json(row) for row in connection.execute(PRODUCT_SELECT + " WHERE p.active=1 AND casefold(p.name)=casefold(?)" + order, (name,))]
    if exact:
        return {"entry_id": entry_id, "text": entry["text"], "status": "exact" if len(exact) == 1 else "choose", "match_type": "exact", "matches": exact}
    partial = [product_json(row) for row in connection.execute(PRODUCT_SELECT + " WHERE p.active=1 AND instr(casefold(p.name),casefold(?))>0" + order, (name,))]
    return {"entry_id": entry_id, "text": entry["text"], "status": "choose" if partial else "missing", "match_type": "partial" if partial else "none", "matches": partial}


def named_product_matches(connection, name):
    order = " ORDER BY p.name COLLATE NOCASE,s.name COLLATE NOCASE,p.id"
    exact = [product_json(row) for row in connection.execute(PRODUCT_SELECT + " WHERE p.active=1 AND casefold(p.name)=casefold(?)" + order, (name,))]
    matches = exact or [product_json(row) for row in connection.execute(PRODUCT_SELECT + " WHERE p.active=1 AND instr(casefold(p.name),casefold(?))>0" + order, (name,))]
    return {"status": "missing" if not matches else "unique" if len(matches) == 1 else "choose",
            "match_type": "exact" if exact else "partial" if matches else "none", "matches": matches}


def generic_category(connection):
    return ensure_system_metadata(connection)[0]


def generic_supermarket(connection):
    return ensure_system_metadata(connection)[1]


def create_generic_product(connection, name):
    # No exigir un asistente de catálogo: valores genéricos y precio inicial cero.
    category = generic_category(connection)
    supermarket = generic_supermarket(connection)
    if connection.execute("SELECT id FROM products WHERE name=? AND supermarket_id=?", (name, supermarket)).fetchone():
        raise HTTPException(409, "Ya existe un producto con este nombre. Vuelve a cargar el catálogo.")
    product_id = connection.execute("INSERT INTO products(name,category_id,supermarket_id,unit,notes,price_cents,updated_at) VALUES(?,?,?,'ud','',0,?)", (name, category, supermarket, now())).lastrowid
    update_price(connection, product_id, 0, "alta rápida", force=True)
    return product_id


def duplicate_menu_week(connection, week):
    source = week - timedelta(days=week.weekday())
    if source.toordinal() + 13 > date.max.toordinal():
        raise HTTPException(422, "La semana siguiente queda fuera del calendario admitido")
    target = source + timedelta(days=7)
    rows = connection.execute("SELECT * FROM menu_entries WHERE date>=? AND date<=? ORDER BY date,slot,position,id", (source.isoformat(), (source + timedelta(days=6)).isoformat())).fetchall()
    if not rows:
        raise HTTPException(409, "No hay platos en esta semana para duplicar")
    existing = connection.execute("SELECT date,slot,text FROM menu_entries WHERE date>=? AND date<=?", (target.isoformat(), (source + timedelta(days=13)).isoformat())).fetchall()
    def key(day, slot, text):
        return day, slot, text.strip().casefold()
    available = Counter(key(row["date"], row["slot"], row["text"]) for row in existing)
    desired = Counter()
    entries = []
    skipped = 0
    for row in rows:
        day = (date.fromisoformat(row["date"]) + timedelta(days=7)).isoformat()
        identity = key(day, row["slot"], row["text"])
        desired[identity] += 1
        if available[identity] >= desired[identity]:
            skipped += 1
            continue
        entries.append(create_menu_row(connection, day, row["slot"], row["text"], row["dish_id"]))
    return {"source_week": source.isoformat(), "target_week": target.isoformat(), "copied": len(entries), "skipped": skipped, "entries": entries}


def create_app(data_dir=None, development=None, *, supervisor_transport=..., discovery_interval=INTERVAL):
    development = (os.getenv("MENU_COMPRA_DEV", "0") == "1") if development is None else development
    database = Database(data_dir or os.getenv("MENU_COMPRA_DATA_DIR", "/data"))
    bridge = BridgeState(database.path.parent)

    @asynccontextmanager
    async def lifespan(application):
        database.initialize()
        transport = SupervisorTransport.from_environment() if supervisor_transport is ... else supervisor_transport
        bridge.load(automatic=transport is not None)
        discovery = SupervisorDiscovery(bridge, transport, interval=discovery_interval,
                                       ready_check=local_http_ready if supervisor_transport is ... and transport is not None else None)
        application.state.supervisor_discovery = discovery
        discovery.start()
        try:
            yield
        finally:
            await discovery.close()

    application = FastAPI(title="Menú y Compra", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    application.state.database = database
    application.state.ha_bridge = bridge
    application.state.development = development

    @application.middleware("http")
    async def security(request: Request, call_next):
        peer = request.client.host if request.client else ""
        original_path = request.url.path
        machine = original_path.startswith("/bridge/")
        if machine:
            # Drain bounded machine bodies before an early denial. Otherwise an
            # unread TCP payload can reset the connection instead of delivering 401/404.
            try:
                length = int(request.headers.get("content-length", "0"))
                if length < 0:
                    raise ValueError
                if length > BODY_LIMIT:
                    return JSONResponse({"detail": "El archivo supera el tamaño permitido"}, status_code=413)
                chunks, size = [], 0
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > BODY_LIMIT:
                            return JSONResponse({"detail": "El archivo supera el tamaño permitido"}, status_code=413)
                        chunks.append(chunk)
                # Starlette's cached request replays this body to the route once.
                request._body = b"".join(chunks)
            except (ValueError, TimeoutError):
                return JSONResponse({"detail": "Cuerpo de solicitud no válido o incompleto"}, status_code=400)
            if not bridge.status()["enabled"]:
                return JSONResponse({"detail": "Conexión HA desactivada"}, status_code=404, headers={"Cache-Control": "no-store"})
            if not bridge.authorized(request.headers.get("Authorization", "")):
                return JSONResponse({"detail": "Clave de conexión no válida"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})
            target = bridge_target(original_path, request.method)
            if target is None:
                return JSONResponse({"detail": "Operación no permitida en la conexión HA"}, status_code=404, headers={"Cache-Control": "no-store"})
            # Scope rewrite, not an HTTP redirect or proxy: shares the exact business transactions.
            request.scope["path"] = target
            request.scope["raw_path"] = target.encode("ascii")
        health_local = original_path == "/api/health" and peer in ("127.0.0.1", "::1")
        if not machine and not development and peer != "172.30.32.2" and not health_local:
            return JSONResponse({"detail": "Accede desde Home Assistant Ingress"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not machine and request.headers.get("X-Menu-Compra") != "1":
                return JSONResponse({"detail": "Falta la cabecera de seguridad"}, status_code=403)
            request_limit = BODY_LIMIT if machine else (64 * 1024 * 1024 if original_path == "/api/restore" else 8 * 1024 * 1024)
            try:
                if int(request.headers.get("content-length", "0")) > request_limit:
                    return JSONResponse({"detail": "El archivo supera el tamaño permitido"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Tamaño de solicitud inválido"}, status_code=400)
            body = await request.body()
            if len(body) > request_limit:
                return JSONResponse({"detail": "El archivo supera el tamaño permitido"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exception):
        return JSONResponse({"detail": "Ya existe un registro con ese nombre en ese supermercado, o los datos hacen referencia a un registro inexistente."}, status_code=409)

    @application.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exception):
        logging.getLogger(__name__).exception("Error de almacenamiento", exc_info=exception)
        return JSONResponse({"detail": "No se ha podido acceder a los datos. Vuelve a intentarlo y comprueba el almacenamiento."}, status_code=503)

    @application.exception_handler(OverflowError)
    async def overflow_error(request, exception):
        return JSONResponse({"detail": "Identificador o fecha fuera de los límites admitidos."}, status_code=422)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exception):
        errors = [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exception.errors()]
        return JSONResponse({"detail": "Datos no válidos. Comprueba los campos y sus límites.", "errors": errors}, status_code=422)

    @application.get("/api/health")
    def health():
        with database.connect() as connection:
            connection.execute("SELECT 1 FROM categories LIMIT 1").fetchone()
        return {"status": "ok", "version": VERSION}

    @application.get("/api/ha/status")
    def ha_status():
        return bridge.status()

    def bridge_setting(action, *args):
        try:
            return action(*args)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except OSError as error:
            raise HTTPException(503, "No se ha podido guardar la conexión HA; no se ha cambiado la clave.") from error

    @application.post("/api/ha/config")
    def ha_config(data: BridgeConfig):
        return bridge_setting(bridge.configure, data.enabled)

    @application.post("/api/ha/token")
    def ha_token():
        return bridge_setting(bridge.reveal)

    @application.post("/api/ha/rotate")
    def ha_rotate():
        return bridge_setting(bridge.rotate)

    @application.get("/api/bootstrap")
    def bootstrap():
        with database.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM products p JOIN categories c ON c.id=p.category_id WHERE p.active=1 AND c.name='Sin especificar'").fetchone()[0]
            return {"version": VERSION, "uncategorized_count": count, "categories": categories_json(connection), "supermarkets": supermarkets_json(connection), "products": products_json(connection), "dishes": dishes_json(connection)}

    @application.get("/api/categories")
    def categories():
        with database.connect() as connection:
            return categories_json(connection)

    @application.post("/api/categories", status_code=201)
    def create_category(data: CategoryIn):
        if data.name.casefold() == "sin categoría":
            raise HTTPException(409, "Utiliza la categoría protegida Sin especificar.")
        with database.connect(write=True) as connection:
            row_id = connection.execute("INSERT INTO categories(name,sort_order,is_frozen) VALUES(?,?,?)", (data.name, data.sort_order, data.is_frozen)).lastrowid
            return {**dict(require_row(connection, "categories", row_id)), "is_frozen": data.is_frozen}

    @application.put("/api/categories/{category_id}")
    def edit_category(category_id: int, data: CategoryIn):
        with database.connect(write=True) as connection:
            old = require_row(connection, "categories", category_id)
            if old["name"].casefold() == "sin especificar":
                raise HTTPException(409, "La categoría Sin especificar es del sistema y no se puede editar.")
            if data.name.casefold() == "sin categoría":
                raise HTTPException(409, "Utiliza la categoría protegida Sin especificar.")
            connection.execute("UPDATE categories SET name=?,sort_order=?,is_frozen=? WHERE id=?", (data.name, data.sort_order, data.is_frozen, category_id))
            return {**dict(require_row(connection, "categories", category_id)), "is_frozen": data.is_frozen}

    @application.delete("/api/categories/{category_id}")
    def delete_category(category_id: int):
        with database.connect(write=True) as connection:
            category = require_row(connection, "categories", category_id)
            if category["name"].casefold() == "sin especificar":
                raise HTTPException(409, "La categoría Sin especificar es del sistema y no se puede eliminar.")
            count = connection.execute("SELECT COUNT(*) FROM products WHERE category_id=?", (category_id,)).fetchone()[0]
            if count:
                fallback = generic_category(connection)
                connection.execute("UPDATE products SET category_id=?,updated_at=? WHERE category_id=?", (fallback, now(), category_id))
            connection.execute("DELETE FROM categories WHERE id=?", (category_id,))
            return {"deleted": True, "reassigned_products": count}

    @application.get("/api/supermarkets")
    def supermarkets():
        with database.connect() as connection:
            return supermarkets_json(connection)

    @application.post("/api/supermarkets", status_code=201)
    def create_supermarket(data: SupermarketIn):
        with database.connect(write=True) as connection:
            row_id = connection.execute("INSERT INTO supermarkets(name) VALUES(?)", (data.name,)).lastrowid
            return dict(require_row(connection, "supermarkets", row_id))

    @application.put("/api/supermarkets/{supermarket_id}")
    def edit_supermarket(supermarket_id: int, data: SupermarketIn):
        with database.connect(write=True) as connection:
            old = require_row(connection, "supermarkets", supermarket_id)
            if old["name"].casefold() == "sin especificar":
                raise HTTPException(409, "El supermercado Sin especificar es del sistema y no se puede editar.")
            connection.execute("UPDATE supermarkets SET name=? WHERE id=?", (data.name, supermarket_id))
            return dict(require_row(connection, "supermarkets", supermarket_id))

    @application.delete("/api/supermarkets/{supermarket_id}")
    def delete_supermarket(supermarket_id: int):
        with database.connect(write=True) as connection:
            supermarket = require_row(connection, "supermarkets", supermarket_id)
            if supermarket["name"].casefold() == "sin especificar":
                raise HTTPException(409, "El supermercado Sin especificar es del sistema y no se puede eliminar.")
            count = connection.execute("SELECT COUNT(*) FROM products WHERE supermarket_id=?", (supermarket_id,)).fetchone()[0]
            used = any(connection.execute(f"SELECT 1 FROM {table} WHERE supermarket_id=? LIMIT 1", (supermarket_id,)).fetchone() for table in ("products", "shopping_items", "price_history"))
            if used:

                fallback = generic_supermarket(connection)
                collision = connection.execute("SELECT 1 FROM products p JOIN products q ON p.name=q.name WHERE p.supermarket_id=? AND q.supermarket_id=? LIMIT 1", (supermarket_id, fallback)).fetchone()
                if collision:
                    raise HTTPException(409, "Hay productos con el mismo nombre en Sin especificar. Reasígnalos antes de eliminar el supermercado; no se ha cambiado ningún dato.")
                connection.execute("UPDATE products SET supermarket_id=?,updated_at=? WHERE supermarket_id=?", (fallback, now(), supermarket_id))
                connection.execute("UPDATE price_history SET supermarket_name_snapshot=COALESCE(supermarket_name_snapshot,?),supermarket_id=? WHERE supermarket_id=?", (supermarket["name"], fallback, supermarket_id))
                sync_shopping_products(connection)
            connection.execute("DELETE FROM supermarkets WHERE id=?", (supermarket_id,))
            return {"deleted": True, "reassigned_products": count}

    @application.get("/api/products")
    def products(q: str = Query(default="", max_length=180), category_id: int | None = None, supermarket_id: int | None = None, include_archived: bool = False):
        with database.connect() as connection:
            return products_json(connection, q, category_id, supermarket_id, include_archived)

    @application.post("/api/products", status_code=201)
    def create_product(data: ProductIn):
        with database.connect(write=True) as connection:
            require_row(connection, "categories", data.category_id)
            require_row(connection, "supermarkets", data.supermarket_id)
            row_id = connection.execute("INSERT INTO products(name,category_id,supermarket_id,unit,notes,price_cents,updated_at) VALUES(?,?,?,?,?,?,?)", (data.name, data.category_id, data.supermarket_id, data.unit, data.notes, data.price_cents, now())).lastrowid
            update_price(connection, row_id, data.price_cents, "alta", force=True)
            return product_detail(connection, row_id)

    @application.get("/api/products/matches")
    def product_matches(name: str = Query(min_length=1, max_length=180)):
        name = name.strip()
        if not name:
            raise HTTPException(422, "Escribe el nombre del producto")
        with database.connect() as connection:
            return named_product_matches(connection, name)

    @application.get("/api/products/{product_id}")
    def get_product(product_id: int):
        with database.connect() as connection:
            return product_detail(connection, product_id)

    @application.put("/api/products/{product_id}")
    def edit_product(product_id: int, data: ProductIn):
        with database.connect(write=True) as connection:
            old = require_row(connection, "products", product_id)
            if old["unit"] != data.unit and connection.execute("SELECT 1 FROM dish_ingredients WHERE product_id=? LIMIT 1", (product_id,)).fetchone():
                raise HTTPException(409, "La unidad se utiliza en platos guardados. Retira primero el ingrediente de esos platos o crea un producto con la nueva unidad.")
            require_row(connection, "categories", data.category_id)
            require_row(connection, "supermarkets", data.supermarket_id)
            connection.execute("UPDATE products SET name=?,category_id=?,supermarket_id=?,unit=?,notes=?,active=1,updated_at=? WHERE id=?", (data.name, data.category_id, data.supermarket_id, data.unit, data.notes, now(), product_id))
            update_price(connection, product_id, data.price_cents, "edición", force=old["supermarket_id"] != data.supermarket_id)
            return product_detail(connection, product_id)

    @application.post("/api/products/{product_id}/price")
    def edit_price(product_id: int, data: PriceIn):
        with database.connect(write=True) as connection:
            update_price(connection, product_id, data.price_cents, "ficha")
            return product_detail(connection, product_id)

    @application.delete("/api/products/{product_id}")
    def delete_product(product_id: int):
        with database.connect(write=True) as connection:
            require_row(connection, "products", product_id)
            removed = {}
            for table in ("dish_ingredients", "shopping_items", "price_history"):
                removed[table] = connection.execute(f"DELETE FROM {table} WHERE product_id=?", (product_id,)).rowcount
            removed["products"] = connection.execute("DELETE FROM products WHERE id=?", (product_id,)).rowcount
            return {"deleted": True, "removed": removed}

    @application.get("/api/shopping")
    def shopping():
        with database.connect() as connection:
            return shopping_json(connection)

    @application.post("/api/shopping/items", status_code=201)
    def shopping_add(data: ShoppingIn):
        with database.connect(write=True) as connection:
            add_shopping(connection, data.product_id, data.quantity, data.price_cents, data.note)
            return shopping_json(connection)

    @application.post("/api/shopping/quick-add", status_code=201)
    def shopping_quick_add(data: QuickShoppingIn):
        with database.connect(write=True) as connection:
            product_id = data.product_id
            created = False
            if product_id is None:
                matches = named_product_matches(connection, data.name)
                if matches["status"] == "choose":
                    return JSONResponse({"detail": "Hay varias coincidencias. Elige un producto.", **matches}, status_code=409)
                if matches["status"] == "unique":
                    product_id = matches["matches"][0]["id"]
                else:
                    product_id = create_generic_product(connection, data.name)
                    created = True
            add_shopping(connection, product_id, data.quantity, None if created else data.price_cents)
            return {"shopping": shopping_json(connection), "product": product_detail(connection, product_id), "created": created}

    @application.post("/api/shopping/items/{item_id}/adjust")
    def shopping_adjust(item_id: int, data: ShoppingAdjustIn):
        with database.connect(write=True) as connection:
            item = require_row(connection, "shopping_items", item_id)
            quantity = Decimal(item["quantity"]) + data.delta
            if quantity <= 0 or quantity > 100000:
                raise HTTPException(422, "La cantidad debe ser mayor que cero y no superar 100.000. Para eliminar la línea utiliza Quitar.")
            connection.execute("UPDATE shopping_items SET quantity=? WHERE id=?", (str(quantity), item_id))
            return shopping_json(connection)

    @application.patch("/api/shopping/items/{item_id}")
    def shopping_edit(item_id: int, data: ShoppingPatch):
        with database.connect(write=True) as connection:
            require_row(connection, "shopping_items", item_id)
            for key in data.model_fields_set:
                value = getattr(data, key)
                if key == "quantity":
                    value = str(value)
                connection.execute(f"UPDATE shopping_items SET {key}=? WHERE id=?", (value, item_id))
            return shopping_json(connection)

    @application.delete("/api/shopping/items/{item_id}")
    def shopping_remove(item_id: int):
        with database.connect(write=True) as connection:
            require_row(connection, "shopping_items", item_id)
            connection.execute("DELETE FROM shopping_items WHERE id=?", (item_id,))
            return shopping_json(connection)

    @application.delete("/api/shopping/checked")
    def shopping_clear_checked():
        with database.connect(write=True) as connection:
            connection.execute("DELETE FROM shopping_items WHERE checked=1")
            return shopping_json(connection)

    @application.delete("/api/shopping")
    def shopping_clear_all():
        with database.connect(write=True) as connection:
            connection.execute("DELETE FROM shopping_items")
            return shopping_json(connection)

    @application.get("/api/shopping/export")
    def shopping_export():
        with database.connect() as connection:
            data = shopping_json(connection)
        lines = ["LISTA DE LA COMPRA", ""]
        for group in data["groups"]:
            lines.append(group["name"].upper())
            for item in group["items"]:
                mark = "x" if item["checked"] else " "
                price = f"{item['subtotal_cents'] / 100:.2f}".replace(".", ",")
                lines.append(f"[{mark}] {item['product_name']} — {item['quantity']:g} {item['unit']} — {item['supermarket_name']} — {price} €")
                if item["note"]:
                    lines.append("    " + item["note"])
            lines.append("")
        total = f"{data['total_cents'] / 100:.2f}".replace(".", ",")
        lines.append(f"Total estimado: {total} €")
        return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": 'attachment; filename="lista-compra.txt"'})

    @application.get("/api/dishes")
    def dishes(q: str = Query(default="", max_length=180)):
        with database.connect() as connection:
            return dishes_json(connection, q)

    @application.post("/api/dishes", status_code=201)
    def create_dish(data: DishIn):
        with database.connect(write=True) as connection:
            dish_id = connection.execute("INSERT INTO dishes(name,notes) VALUES(?,?)", (data.name, data.notes)).lastrowid
            save_ingredients(connection, dish_id, data.ingredients)
            return next(d for d in dishes_json(connection) if d["id"] == dish_id)

    @application.put("/api/dishes/{dish_id}")
    def edit_dish(dish_id: int, data: DishIn):
        with database.connect(write=True) as connection:
            require_row(connection, "dishes", dish_id)
            connection.execute("UPDATE dishes SET name=?,notes=? WHERE id=?", (data.name, data.notes, dish_id))
            save_ingredients(connection, dish_id, data.ingredients)
            return next(d for d in dishes_json(connection) if d["id"] == dish_id)

    @application.delete("/api/dishes/{dish_id}")
    def remove_dish(dish_id: int):
        with database.connect(write=True) as connection:
            require_row(connection, "dishes", dish_id)
            connection.execute("DELETE FROM dishes WHERE id=?", (dish_id,))
            return {"deleted": True}

    @application.get("/api/menu")
    def menu(week: date | None = None):
        day = week or date.today()
        monday = day - timedelta(days=day.weekday())
        with database.connect() as connection:
            if monday.toordinal() + 7 > date.max.toordinal():
                rows = connection.execute("SELECT * FROM menu_entries WHERE date>=? ORDER BY date,slot,position,id", (monday.isoformat(),))
            else:
                rows = connection.execute("SELECT * FROM menu_entries WHERE date>=? AND date<? ORDER BY date,slot,position,id", (monday.isoformat(), (monday + timedelta(days=7)).isoformat()))
            entries = [dict(r) for r in rows]
            return {"week": monday.isoformat(), "entries": entries}

    @application.put("/api/menu")
    def save_menu(data: MenuIn):
        # Compatibilidad con 0.1: actualizar solo el primer plato de esa franja.
        with database.connect(write=True) as connection:
            text = menu_text(connection, data)
            existing = connection.execute("SELECT * FROM menu_entries WHERE date=? AND slot=? ORDER BY position,id LIMIT 1", (data.date.isoformat(), data.slot)).fetchone()
            if not text:
                if existing:
                    connection.execute("DELETE FROM menu_entries WHERE id=?", (existing["id"],))
                return {"deleted": True}
            if existing:
                connection.execute("UPDATE menu_entries SET text=?,dish_id=? WHERE id=?", (text, data.dish_id, existing["id"]))
                return dict(require_row(connection, "menu_entries", existing["id"]))
            return create_menu_row(connection, data.date.isoformat(), data.slot, text, data.dish_id)

    @application.post("/api/menu", status_code=201)
    def add_menu(data: MenuIn):
        with database.connect(write=True) as connection:
            return create_menu_row(connection, data.date.isoformat(), data.slot, menu_text(connection, data), data.dish_id)

    @application.post("/api/menu/duplicate-week", status_code=201)
    def duplicate_week(data: DuplicateWeekIn):
        with database.connect(write=True) as connection:
            return duplicate_menu_week(connection, data.week)

    @application.post("/api/menu/batch", status_code=201)
    def add_menu_batch(data: MenuBatchIn):
        with database.connect(write=True) as connection:
            return {"entries": [create_menu_row(connection, data.date.isoformat(), data.slot, text) for text in data.texts]}

    @application.put("/api/menu/{entry_id}")
    def edit_menu(entry_id: int, data: MenuIn):
        with database.connect(write=True) as connection:
            old = require_row(connection, "menu_entries", entry_id)
            text = menu_text(connection, data)
            if not text:
                raise HTTPException(422, "Escribe un plato o utiliza Eliminar para quitarlo")
            day = data.date.isoformat()
            position = old["position"] if (day, data.slot) == (old["date"], old["slot"]) else menu_position(connection, day, data.slot)
            connection.execute("UPDATE menu_entries SET date=?,slot=?,text=?,dish_id=?,position=? WHERE id=?", (day, data.slot, text, data.dish_id, position, entry_id))
            return dict(require_row(connection, "menu_entries", entry_id))

    @application.get("/api/menu/{entry_id}")
    def get_menu_entry(entry_id: int):
        with database.connect() as connection:
            return dict(require_row(connection, "menu_entries", entry_id))

    @application.get("/api/menu/{entry_id}/matches")
    def menu_matches(entry_id: int):
        with database.connect() as connection:
            return menu_product_matches(connection, entry_id)

    @application.post("/api/menu/{entry_id}/shopping", status_code=201)
    def menu_shopping(entry_id: int, data: MenuShoppingIn):
        with database.connect(write=True) as connection:
            require_row(connection, "menu_entries", entry_id)
            product_id = data.product_id
            if product_id is None:
                matches = menu_product_matches(connection, entry_id)
                if matches["status"] != "exact":
                    raise HTTPException(409, "No hay una única coincidencia exacta. Elige un producto o crea uno nuevo.")
                product_id = matches["matches"][0]["id"]
            add_shopping(connection, product_id, data.quantity, data.price_cents, data.note)
            return shopping_json(connection)

    @application.delete("/api/menu/{entry_id}")
    def remove_menu(entry_id: int):
        with database.connect(write=True) as connection:
            require_row(connection, "menu_entries", entry_id)
            connection.execute("DELETE FROM menu_entries WHERE id=?", (entry_id,))
            return {"deleted": True}

    @application.post("/api/menu/{entry_id}/ingredients")
    def menu_ingredients(entry_id: int, data: IngredientSelection):
        with database.connect(write=True) as connection:
            entry = require_row(connection, "menu_entries", entry_id)
            if entry["dish_id"] is None:
                raise HTTPException(400, "Asocia primero un plato con ingredientes a esta comida")
            ingredients = {r["product_id"]: r for r in connection.execute("SELECT * FROM dish_ingredients WHERE dish_id=?", (entry["dish_id"],))}
            if not set(data.product_ids) <= ingredients.keys():
                raise HTTPException(422, "La selección contiene productos que no son ingredientes de este plato")
            for product_id in data.product_ids:
                add_shopping(connection, product_id, Decimal(ingredients[product_id]["quantity"]))
            return shopping_json(connection)

    @application.get("/api/backup")
    def backup():
        with database.connect() as connection:
            data = export_data(connection)
        response = JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="menu-compra-copia.json"'})
        if len(response.body) > 64 * 1024 * 1024 or sum(len(rows) for rows in data["tables"].values()) > 100000:
            raise HTTPException(413, "La copia JSON supera el límite restaurable (64 MB o 100.000 registros). Utiliza una copia de seguridad de Home Assistant que incluya esta aplicación.")
        return response

    @application.post("/api/restore")
    def restore(data: dict):
        try:
            with database.connect(write=True) as connection:
                return restore_data(connection, data)
        except (ValueError, TypeError, KeyError, OverflowError, ValidationError, sqlite3.IntegrityError) as error:
            raise HTTPException(422, "Copia no válida. No se ha modificado ningún dato.") from error

    @application.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    application.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    return application


app = create_app()
