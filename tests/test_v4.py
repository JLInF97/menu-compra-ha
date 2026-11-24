"""Regresión del contrato backend 0.4.0; sin expectativas de archivo/snapshots de lista.

Las bases y copias pre-v3 son fixtures independientes del SCHEMA actual. Los
productos archivados se preparan por SQL, nunca mediante un DELETE moderno.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
import sqlite3
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


HEADERS = {"X-Menu-Compra": "1"}
DAY = "2026-11-12"
STAMP = "2026-11-10T12:00:00+00:00"
TABLES = (
    "categories", "supermarkets", "products", "price_history", "dishes",
    "dish_ingredients", "menu_entries", "shopping_items",
)
GENERIC = {"categories": "Sin especificar", "supermarkets": "Sin especificar"}

# Esquema congelado de SQLite v2: no importar SCHEMA de una versión en desarrollo.
LEGACY_SCHEMA_V2 = """
CREATE TABLE categories (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 sort_order INTEGER NOT NULL DEFAULT 50 CHECK(sort_order BETWEEN 0 AND 10000),
 is_frozen INTEGER NOT NULL DEFAULT 0 CHECK(is_frozen IN (0,1)));
CREATE TABLE supermarkets (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE);
CREATE TABLE products (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE,
 category_id INTEGER NOT NULL REFERENCES categories(id),
 supermarket_id INTEGER NOT NULL REFERENCES supermarkets(id),
 unit TEXT NOT NULL DEFAULT 'ud', notes TEXT NOT NULL DEFAULT '',
 price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 100000000),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), updated_at TEXT NOT NULL,
 UNIQUE(name,supermarket_id));
CREATE TABLE price_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL REFERENCES products(id),
 supermarket_id INTEGER NOT NULL REFERENCES supermarkets(id),
 price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 100000000),
 recorded_at TEXT NOT NULL, source TEXT NOT NULL);
CREATE INDEX history_product ON price_history(product_id,id);
CREATE TABLE dishes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 notes TEXT NOT NULL DEFAULT '');
CREATE TABLE dish_ingredients (
 dish_id INTEGER NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
 product_id INTEGER NOT NULL REFERENCES products(id), quantity TEXT NOT NULL,
 PRIMARY KEY(dish_id,product_id));
CREATE TABLE menu_entries (
 id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
 slot TEXT NOT NULL CHECK(slot IN ('lunch','dinner')), text TEXT NOT NULL,
 dish_id INTEGER REFERENCES dishes(id) ON DELETE SET NULL,
 position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0));
CREATE INDEX menu_day_slot ON menu_entries(date,slot,position,id);
CREATE TABLE shopping_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL UNIQUE REFERENCES products(id),
 supermarket_id INTEGER NOT NULL REFERENCES supermarkets(id), unit TEXT NOT NULL,
 quantity TEXT NOT NULL, checked INTEGER NOT NULL DEFAULT 0 CHECK(checked IN (0,1)),
 note TEXT NOT NULL DEFAULT '',
 unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents BETWEEN 0 AND 100000000));
PRAGMA user_version=2;
"""


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def backup(client):
    return ok(client.get("/api/backup"))


def tables(client):
    return backup(client)["tables"]


def canonical(data):
    """Comparar tablas sin depender del orden incidental de SELECT sin ORDER BY."""
    return {name: sorted(json.dumps(row, sort_keys=True) for row in rows) for name, rows in data.items()}


def unchanged(client, before):
    assert canonical(tables(client)) == canonical(before)


def metadata(client, kind, name, **extra):
    return ok(client.post(f"/api/{kind}", json={"name": name, **extra}), 201)


def by_name(client, kind, name):
    return next(row for row in ok(client.get(f"/api/{kind}")) if row["name"] == name)


def product(client, name="Producto v4", *, category_id=None, supermarket_id=None, price=200, unit="kg"):
    category_id = category_id or by_name(client, "categories", "Carne")["id"]
    supermarket_id = supermarket_id or by_name(client, "supermarkets", "Sin especificar")["id"]
    return ok(client.post("/api/products", json={
        "name": name, "category_id": category_id, "supermarket_id": supermarket_id,
        "unit": unit, "price_cents": price, "notes": "Nota del catálogo",
    }), 201)


def edit_payload(p, **changes):
    return {**{key: p[key] for key in (
        "name", "category_id", "supermarket_id", "unit", "price_cents", "notes",
    )}, **changes}


def detail(client, p):
    return ok(client.get(f"/api/products/{p['id']}"))


def items(data):
    return [item for group in data["groups"] for item in group["items"]]


def shopping(client):
    return ok(client.get("/api/shopping"))


def line(client, p):
    return next(item for item in items(shopping(client)) if item["product_id"] == p["id"])


def add(client, p, quantity="2.5", *, checked=False, note="Nota de la compra"):
    data = ok(client.post("/api/shopping/items", json={
        "product_id": p["id"], "quantity": quantity, "note": note,
    }), 201)
    item = next(item for item in items(data) if item["product_id"] == p["id"])
    if checked:
        ok(client.patch(f"/api/shopping/items/{item['id']}", json={"checked": True}))
    return line(client, p)


def plate(client, text="Producto v4", dish_id=None):
    return ok(client.post("/api/menu", json={
        "date": DAY, "slot": "lunch", "text": text, "dish_id": dish_id,
    }), 201)


def recipe(client, name, products):
    return ok(client.post("/api/dishes", json={
        "name": name,
        "ingredients": [{"product_id": p["id"], "quantity": "0.5"} for p in products],
    }), 201)


def assert_integrity(client):
    with client.app.state.database.connect() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4


def assert_preserved_line(before, after):
    for key in ("id", "product_id", "quantity", "checked", "note"):
        assert after[key] == before[key], key


def assert_live_line(client, p):
    item = line(client, p)
    for key in ("unit", "category_id", "category_name", "supermarket_id", "supermarket_name", "is_frozen"):
        assert item[key] == p[key], key
    assert item["product_name"] == p["name"]
    assert item["unit_price_cents"] == p["price_cents"]
    expected = int((Decimal(str(item["quantity"])) * p["price_cents"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    assert item["subtotal_cents"] == expected
    # No basta con proyectar el catálogo en GET: las filas persistidas también son vivas.
    stored = next(row for row in tables(client)["shopping_items"] if row["product_id"] == p["id"])
    assert (stored["unit"], stored["supermarket_id"], stored["unit_price_cents"]) == (
        p["unit"], p["supermarket_id"], p["price_cents"],
    )
    return item


@pytest.fixture
def migration_pre3(tmp_path):
    """Base v2 real con active=0 y una línea obsoleta, ambas creadas por SQL."""
    path = tmp_path / "legacy"
    path.mkdir()
    with sqlite3.connect(path / "menu_compra.sqlite3") as connection:
        connection.row_factory = sqlite3.Row
        connection.create_collation("NOCASE", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
        connection.executescript(LEGACY_SCHEMA_V2)
        connection.executemany("INSERT INTO categories(id,name,sort_order,is_frozen) VALUES(?,?,?,?)", [
            (3, "Carne", 30, 0), (9, "Congelados antiguos", 0, 1),
        ])
        connection.executemany("INSERT INTO supermarkets(id,name) VALUES(?,?)", [
            (1, "Tienda antigua"), (7, "Tienda actual"),
        ])
        connection.executemany("""INSERT INTO products
            (id,name,category_id,supermarket_id,unit,notes,price_cents,active,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)""", [
            (17, "Archivado legado", 9, 7, "l", "Conservar notas", 450, 0, STAMP),
            (23, "Otro legado", 3, 1, "ud", "", 100, 1, STAMP),
        ])
        connection.executemany("""INSERT INTO price_history
            (id,product_id,supermarket_id,price_cents,recorded_at,source) VALUES(?,?,?,?,?,?)""", [
            (41, 17, 1, 200, STAMP, "alta"),
            (42, 17, 7, 450, STAMP, "edición"),
            (43, 23, 1, 100, STAMP, "alta"),
        ])
        connection.execute("INSERT INTO dishes(id,name,notes) VALUES(8,'Receta heredada','No borrar')")
        connection.execute("INSERT INTO dish_ingredients(dish_id,product_id,quantity) VALUES(8,17,'0.5')")
        connection.execute("""INSERT INTO menu_entries(id,date,slot,text,dish_id,position)
            VALUES(31,?,'lunch','Texto libre archivado',8,0)""", (DAY,))
        connection.execute("""INSERT INTO shopping_items
            (id,product_id,supermarket_id,unit,quantity,checked,note,unit_price_cents)
            VALUES(61,17,1,'kg','1.5',1,'Conservar esta nota',200)""")
        old_tables = {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")] for table in TABLES}
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert "supermarket_name_snapshot" not in {row[1] for row in connection.execute("PRAGMA table_info(price_history)")}
    return {"directory": path, "backup": {
        "format": "menu-compra", "version": 2, "exported_at": STAMP, "tables": old_tables,
    }}


def expected_upgrade(old_tables, system_ids=None):
    expected = deepcopy(old_tables)
    system_ids = system_ids or {kind: max(row["id"] for row in expected[kind]) + 1 for kind in ("categories", "supermarkets")}
    expected["categories"].append({"id": system_ids["categories"], "name": "Sin especificar", "sort_order": 110, "is_frozen": 0})
    expected["supermarkets"].append({"id": system_ids["supermarkets"], "name": "Sin especificar"})
    products = {p["id"]: p for p in expected["products"]}
    for p in products.values():
        p["active"] = 1
    for row in expected["price_history"]:
        row["supermarket_name_snapshot"] = None
    for row in expected["shopping_items"]:
        p = products[row["product_id"]]
        row.update(unit=p["unit"], supermarket_id=p["supermarket_id"], unit_price_cents=p["price_cents"])
    return expected


def test_bootstrap_reports_v4_and_preserves_existing_fields(client):
    data = ok(client.get("/api/bootstrap"))
    assert data.get("version") == "1.1.0", data
    assert {"categories", "supermarkets", "products", "dishes"} <= data.keys()
    assert ok(client.get("/api/health")) == {"status": "ok", "version": "1.1.0"}
    assert backup(client)["version"] == 3
    assert_integrity(client)


@pytest.mark.parametrize("write", [False, True])
def test_connections_enable_secure_delete(client, write):
    with client.app.state.database.connect(write=write) as connection:
        assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1


@pytest.mark.parametrize("checked", [False, True], ids=["pendiente", "comprado"])
def test_product_put_synchronizes_entire_existing_line_without_losing_state(client, checked):
    p = product(client)
    original = add(client, p, checked=checked)
    category = metadata(client, "categories", "Nueva sección congelada", sort_order=1, is_frozen=True)
    shop = metadata(client, "supermarkets", "Nuevo mercado")
    updated = ok(client.put(f"/api/products/{p['id']}", json=edit_payload(
        p, name="Producto editado", category_id=category["id"], supermarket_id=shop["id"],
        unit="l", price_cents=399, notes="Nueva nota del catálogo",
    )))
    current = assert_live_line(client, updated)
    assert_preserved_line(original, current)
    data = shopping(client)
    assert data["groups"][0]["name"] == category["name"]
    assert data["groups"][0]["is_frozen"] is True
    assert data["checked_count"] == int(checked)
    assert data["checked_total_cents"] == (current["subtotal_cents"] if checked else 0)
    assert data["pending_total_cents"] == (0 if checked else current["subtotal_cents"])
    history = detail(client, p)["price_history"]
    assert len(history) == len(p["price_history"]) + 1
    assert history[0]["supermarket_id"] == shop["id"]
    assert history[0]["price_cents"] == 399
    assert all(h["supermarket_deleted"] is False for h in history)


@pytest.mark.parametrize("checked", [False, True], ids=["pendiente", "comprado"])
def test_price_post_reprices_existing_line_and_keeps_checked_quantity_note(client, checked):
    p = product(client)
    original = add(client, p, checked=checked)
    updated = ok(client.post(f"/api/products/{p['id']}/price", json={"price_cents": 333}))
    assert_preserved_line(original, assert_live_line(client, updated))
    assert [h["price_cents"] for h in updated["price_history"]] == [333, p["price_cents"]]
    assert updated["price_history"][0]["source"] == "ficha"
    before = tables(client)
    ok(client.post(f"/api/products/{p['id']}/price", json={"price_cents": 333}))
    unchanged(client, before)


@pytest.mark.parametrize("kind", ["items", "quick", "menu"])
def test_explicit_price_while_adding_keeps_catalog_history_and_line_coherent(client, kind):
    p = product(client)
    original = add(client, p)
    if kind == "items":
        route, payload = "/api/shopping/items", {"product_id": p["id"]}
    elif kind == "quick":
        route, payload = "/api/shopping/quick-add", {"name": p["name"], "product_id": p["id"]}
    else:
        entry = plate(client, p["name"])
        route, payload = f"/api/menu/{entry['id']}/shopping", {"product_id": p["id"]}
    ok(client.post(route, json={**payload, "quantity": "0.25", "price_cents": 350}), 201)
    updated = detail(client, p)
    current = assert_live_line(client, updated)
    assert current["id"] == original["id"]
    assert Decimal(str(current["quantity"])) == Decimal(str(original["quantity"])) + Decimal("0.25")
    assert current["checked"] is False and current["note"] == original["note"]
    assert [h["price_cents"] for h in updated["price_history"]] == [350, p["price_cents"]]
    assert updated["price_history"][0]["source"] == "lista"


def test_invalid_catalog_edit_rolls_back_product_history_and_live_line(client):
    shop = metadata(client, "supermarkets", "Destino con colisión")
    p = product(client, "Mismo nombre")
    product(client, "MISMO NOMBRE", supermarket_id=shop["id"])
    add(client, p, checked=True)
    before = tables(client)
    response = client.put(f"/api/products/{p['id']}", json=edit_payload(p, supermarket_id=shop["id"], price_cents=999))
    assert response.status_code == 409, response.text
    unchanged(client, before)


def test_overflow_add_with_new_price_rolls_back_live_line_and_history(client):
    p = product(client)
    add(client, p, "100000")
    before = tables(client)
    response = client.post("/api/shopping/items", json={"product_id": p["id"], "quantity": 1, "price_cents": 999})
    assert response.status_code == 422, response.text
    unchanged(client, before)


def test_sqlite_v2_startup_migrates_activates_and_live_syncs_without_losing_relations(migration_pre3):
    directory = migration_pre3["directory"]
    expected = expected_upgrade(migration_pre3["backup"]["tables"])
    with TestClient(create_app(directory, development=True), headers=HEADERS) as migrated:
        assert canonical(tables(migrated)) == canonical(expected)
        assert_integrity(migrated)
        with migrated.app.state.database.connect() as connection:
            columns = {row[1]: row for row in connection.execute("PRAGMA table_info(price_history)")}
            assert "supermarket_name_snapshot" in columns
            assert columns["supermarket_name_snapshot"][2].upper() == "TEXT"
            assert columns["supermarket_name_snapshot"][3] == 0  # NULL permitido.
        assert {p["id"] for p in ok(migrated.get("/api/products"))} == {17, 23}
        assert {p["id"] for p in ok(migrated.get("/api/bootstrap"))["products"]} == {17, 23}
        p = ok(migrated.get("/api/products/17"))
        assert p["active"] is True
        assert all(h["supermarket_deleted"] is False for h in p["price_history"])
        assert [h["supermarket_name"] for h in p["price_history"]] == ["Tienda actual", "Tienda antigua"]
        assert assert_live_line(migrated, p)["checked"] is True
        assert ok(migrated.get("/api/products/matches", params={"name": p["name"]}))["status"] == "unique"
        first = tables(migrated)
    with TestClient(create_app(directory, development=True), headers=HEADERS) as restarted:
        assert canonical(tables(restarted)) == canonical(first)
        assert_integrity(restarted)


@pytest.mark.parametrize("version", [1, 2])
def test_restore_old_formats_upgrades_to_v3_activates_and_syncs(client, migration_pre3, version):
    old = deepcopy(migration_pre3["backup"])
    old["version"] = version
    if version == 1:
        for row in old["tables"]["menu_entries"]:
            del row["position"]
    sentinel = product(client, "No debe sobrevivir al restore")
    add(client, sentinel)
    response = ok(client.post("/api/restore", json=old))
    assert response["restored"] is True
    # Los IDs nuevos respetan AUTOINCREMENT del destino, no se reciclan tras borrar.
    system_ids = {kind: by_name(client, kind, GENERIC[kind])["id"] for kind in ("categories", "supermarkets")}
    assert all(system_ids[kind] not in {row["id"] for row in old["tables"][kind]} for kind in system_ids)
    expected = expected_upgrade(migration_pre3["backup"]["tables"], system_ids)
    exported = backup(client)
    assert exported["format"] == "menu-compra" and exported["version"] == 3
    assert canonical(exported["tables"]) == canonical(expected)
    assert {p["id"] for p in ok(client.get("/api/products"))} == {17, 23}
    assert ok(client.get("/api/products/17"))["active"] is True
    assert assert_live_line(client, ok(client.get("/api/products/17")))["checked"] is True
    assert all(h["supermarket_deleted"] is False for h in ok(client.get("/api/products/17"))["price_history"])
    assert_integrity(client)
    # El resultado migrado vuelve a ser restaurable sin cambios ni nueva historia.
    ok(client.post("/api/restore", json=exported))
    unchanged(client, exported["tables"])


def test_product_delete_removes_all_relations_but_preserves_menu_text_and_other_records(client):
    p = product(client, "Borrar de verdad")
    other = product(client, "Conservar")
    add(client, p, checked=True)
    add(client, other)
    ok(client.post(f"/api/products/{p['id']}/price", json={"price_cents": 299}))
    first = recipe(client, "Receta mixta", [p, other])
    recipe(client, "Otra receta del eliminado", [p])
    plate(client, p["name"], first["id"])
    plate(client, p["name"])
    before = tables(client)
    removed = {"products": 1, **{
        table: sum(row["product_id"] == p["id"] for row in before[table])
        for table in ("shopping_items", "price_history", "dish_ingredients")
    }}
    assert ok(client.delete(f"/api/products/{p['id']}")) == {"deleted": True, "removed": removed}
    assert client.get(f"/api/products/{p['id']}").status_code == 404
    assert client.delete(f"/api/products/{p['id']}").status_code == 404
    after = tables(client)
    expected = deepcopy(before)
    expected["products"] = [row for row in expected["products"] if row["id"] != p["id"]]
    for table in ("shopping_items", "price_history", "dish_ingredients"):
        expected[table] = [row for row in expected[table] if row["product_id"] != p["id"]]
    assert canonical(after) == canonical(expected)
    assert after["menu_entries"] == before["menu_entries"]
    assert [row["id"] for row in ok(client.get("/api/products", params={"include_archived": True}))] == [other["id"]]
    assert_integrity(client)


def test_delete_product_without_relations_reports_zero_counts_and_allows_same_name_again(client):
    p = product(client)
    expected = {"products": 1, "shopping_items": 0, "price_history": len(p["price_history"]), "dish_ingredients": 0}
    assert ok(client.delete(f"/api/products/{p['id']}")) == {"deleted": True, "removed": expected}
    replacement = product(client, p["name"])
    assert replacement["active"] is True
    assert len(replacement["price_history"]) == 1


def test_category_put_updates_name_order_and_frozen_grouping_live(client):
    cat = metadata(client, "categories", "Sección temporal", sort_order=999, is_frozen=False)
    p = product(client, category_id=cat["id"])
    other = product(client, "Otra sección")
    original = add(client, p, checked=True)
    add(client, other)
    history = tables(client)["price_history"]
    updated = ok(client.put(f"/api/categories/{cat['id']}", json={
        "name": "Sección renombrada", "sort_order": 0, "is_frozen": True,
    }))
    assert updated == {"id": cat["id"], "name": "Sección renombrada", "sort_order": 0, "is_frozen": True}
    assert by_name(client, "categories", updated["name"]) == updated
    group = shopping(client)["groups"][-1]
    assert group["category_id"] == cat["id"] and group["is_frozen"] is True
    assert group["name"] == updated["name"]
    assert_preserved_line(original, assert_live_line(client, detail(client, p)))
    assert tables(client)["price_history"] == history
    ok(client.put(f"/api/categories/{cat['id']}", json={"name": updated["name"], "sort_order": 0, "is_frozen": False}))
    assert shopping(client)["groups"][0]["category_id"] == cat["id"]


def test_supermarket_put_renames_live_list_and_unsnapshotted_history(client):
    shop = metadata(client, "supermarkets", "Mercado original")
    p = product(client, supermarket_id=shop["id"])
    original = add(client, p, checked=True)
    before = tables(client)
    updated = ok(client.put(f"/api/supermarkets/{shop['id']}", json={"name": "Mercado renombrado"}))
    assert updated == {"id": shop["id"], "name": "Mercado renombrado"}
    assert by_name(client, "supermarkets", updated["name"]) == updated
    current_product = detail(client, p)
    assert_preserved_line(original, assert_live_line(client, current_product))
    assert all(h["supermarket_name"] == updated["name"] and h["supermarket_deleted"] is False
               for h in current_product["price_history"])
    assert tables(client)["price_history"] == before["price_history"]
    assert all(row["supermarket_name_snapshot"] is None for row in tables(client)["price_history"])


@pytest.mark.parametrize("kind", ["categories", "supermarkets"])
@pytest.mark.parametrize("method", ["post", "put"])
def test_metadata_duplicate_names_are_409_and_rollback_unicode(client, kind, method):
    metadata(client, kind, "Piña única")
    target = metadata(client, kind, "Otro nombre")
    before = tables(client)
    route = f"/api/{kind}" + (f"/{target['id']}" if method == "put" else "")
    response = client.request(method.upper(), route, json={"name": " PIÑA ÚNICA "})
    assert response.status_code == 409, response.text
    unchanged(client, before)


@pytest.mark.parametrize("kind", ["categories", "supermarkets"])
@pytest.mark.parametrize("method", ["put", "delete"])
def test_metadata_missing_target_returns_404_without_changes(client, kind, method):
    before = tables(client)
    kwargs = {"json": {"name": "No existe"}} if method == "put" else {}
    response = client.request(method.upper(), f"/api/{kind}/999999", **kwargs)
    assert response.status_code == 404, response.text
    unchanged(client, before)


@pytest.mark.parametrize("kind,payload", [
    ("categories", {"name": ""}), ("categories", {"name": "x", "sort_order": -1}),
    ("categories", {"name": "x", "sort_order": 10001}),
    ("categories", {"name": "x", "unexpected": 1}),
    ("supermarkets", {"name": "   "}), ("supermarkets", {"name": "x" * 181}),
    ("supermarkets", {"name": "x", "unexpected": 1}),
])
def test_metadata_invalid_update_returns_422_without_changes(client, kind, payload):
    target = metadata(client, kind, "Válido")
    before = tables(client)
    assert client.put(f"/api/{kind}/{target['id']}", json=payload).status_code == 422
    unchanged(client, before)


def test_used_category_delete_reuses_protected_fallback_and_keeps_products_history_menu(client):
    target = metadata(client, "categories", "Sección a eliminar", is_frozen=True)
    assert by_name(client, "categories", GENERIC["categories"])["is_system"] is True
    p = product(client, category_id=target["id"])
    original = add(client, p, checked=True)
    saved_recipe = recipe(client, "Receta conservada", [p])
    plate(client, p["name"], saved_recipe["id"])
    before = tables(client)
    assert ok(client.delete(f"/api/categories/{target['id']}")) == {"deleted": True, "reassigned_products": 1}
    fallback = by_name(client, "categories", GENERIC["categories"])
    current = detail(client, p)
    assert current["category_id"] == fallback["id"]
    assert current["is_frozen"] is False
    assert_preserved_line(original, assert_live_line(client, current))
    after = tables(client)
    for table in ("price_history", "dishes", "dish_ingredients", "menu_entries", "shopping_items", "supermarkets"):
        assert after[table] == before[table], table
    assert all(c["id"] != target["id"] for c in ok(client.get("/api/categories")))
    assert_integrity(client)


@pytest.mark.parametrize("kind", ["categories", "supermarkets"])
def test_used_generic_metadata_delete_is_409_and_rolls_back(client, kind):
    if kind == "categories":
        target = by_name(client, kind, GENERIC[kind])
        p = product(client, category_id=target["id"])
    else:
        target = by_name(client, kind, GENERIC[kind])
        p = product(client, supermarket_id=target["id"])
    add(client, p, checked=True)
    before = tables(client)
    response = client.delete(f"/api/{kind}/{target['id']}")
    assert response.status_code == 409, response.text
    unchanged(client, before)


@pytest.mark.parametrize("kind", ["categories", "supermarkets"])
@pytest.mark.parametrize("generic", [False, True], ids=["nombre-normal", "generica-vacia"])
def test_empty_metadata_can_be_deleted_without_deleting_anything_else(client, kind, generic):
    if generic:
        target = by_name(client, kind, GENERIC[kind])
    else:
        target = metadata(client, kind, "Vacío para borrar")
    before = tables(client)
    if generic:
        assert client.delete(f"/api/{kind}/{target['id']}").status_code == 409
        unchanged(client, before)
        return
    assert ok(client.delete(f"/api/{kind}/{target['id']}")) == {"deleted": True, "reassigned_products": 0}
    expected = deepcopy(before)
    expected[kind] = [row for row in expected[kind] if row["id"] != target["id"]]
    unchanged(client, expected)
    assert all(row["id"] != target["id"] for row in ok(client.get(f"/api/{kind}")))


def test_used_supermarket_delete_snapshots_old_name_reassigns_and_preserves_other_data(client):
    old_shop = metadata(client, "supermarkets", "Tienda histórica exacta")
    current_shop = metadata(client, "supermarkets", "Tienda que permanece")
    p = product(client, "Actual de tienda eliminada", supermarket_id=old_shop["id"])
    moved = product(client, "Solo historia en tienda eliminada", supermarket_id=old_shop["id"])
    moved = ok(client.put(f"/api/products/{moved['id']}", json=edit_payload(moved, supermarket_id=current_shop["id"])))
    original = add(client, p, checked=True)
    add(client, moved)
    saved_recipe = recipe(client, "Receta sin borrar", [p, moved])
    plate(client, p["name"], saved_recipe["id"])
    before = tables(client)
    assert ok(client.delete(f"/api/supermarkets/{old_shop['id']}")) == {"deleted": True, "reassigned_products": 1}
    fallback = by_name(client, "supermarkets", GENERIC["supermarkets"])
    current = detail(client, p)
    assert current["supermarket_id"] == fallback["id"]
    assert_preserved_line(original, assert_live_line(client, current))
    assert detail(client, moved)["supermarket_id"] == current_shop["id"]
    after = tables(client)
    assert {row["id"] for row in after["products"]} == {row["id"] for row in before["products"]}
    for table in ("categories", "dishes", "dish_ingredients", "menu_entries"):
        assert after[table] == before[table], table
    expected_history = deepcopy(before["price_history"])
    for row in expected_history:
        if row["supermarket_id"] == old_shop["id"]:
            row.update(supermarket_id=fallback["id"], supermarket_name_snapshot=old_shop["name"])
    assert after["price_history"] == expected_history
    for candidate in (p, moved):
        for history in detail(client, candidate)["price_history"]:
            original_history = next(row for row in before["price_history"] if row["id"] == history["id"])
            deleted = original_history["supermarket_id"] == old_shop["id"]
            assert history["supermarket_deleted"] is deleted
            assert history["supermarket_name"] == (old_shop["name"] if deleted else current_shop["name"])
    assert all(row["id"] != old_shop["id"] for row in ok(client.get("/api/supermarkets")))
    assert_integrity(client)


def test_supermarket_fallback_stays_protected_and_is_reused(client):
    generic = by_name(client, "supermarkets", GENERIC["supermarkets"])
    assert client.delete(f"/api/supermarkets/{generic['id']}").status_code == 409
    shop = metadata(client, "supermarkets", "Única tienda restante")
    p = product(client, supermarket_id=shop["id"])
    original = add(client, p, checked=True)
    assert ok(client.delete(f"/api/supermarkets/{shop['id']}")) == {"deleted": True, "reassigned_products": 1}
    fallback = by_name(client, "supermarkets", GENERIC["supermarkets"])
    assert detail(client, p)["supermarket_id"] == fallback["id"]
    assert_preserved_line(original, assert_live_line(client, detail(client, p)))
    assert_integrity(client)


def test_generic_supermarket_with_only_history_references_is_still_in_use(client):
    generic = by_name(client, "supermarkets", GENERIC["supermarkets"])
    p = product(client)
    shop = metadata(client, "supermarkets", "Producto trasladado aquí")
    ok(client.put(f"/api/products/{p['id']}", json=edit_payload(p, supermarket_id=shop["id"])))
    before = tables(client)
    assert not any(row["supermarket_id"] == generic["id"] for row in before["products"])
    assert client.delete(f"/api/supermarkets/{generic['id']}").status_code == 409
    unchanged(client, before)


def test_supermarket_delete_name_collision_rolls_back_every_table_and_snapshots(client):
    generic_product = product(client, "Atún")
    shop = metadata(client, "supermarkets", "No puede fusionarse")
    colliding = product(client, "ATÚN", supermarket_id=shop["id"])
    unproblematic = product(client, "Otro de la misma tienda", supermarket_id=shop["id"])
    for p in (generic_product, colliding, unproblematic):
        add(client, p, checked=True)
    plate(client, "Texto sin cambios")
    before = tables(client)
    response = client.delete(f"/api/supermarkets/{shop['id']}")
    assert response.status_code == 409, response.text
    unchanged(client, before)
    assert all(row["supermarket_name_snapshot"] is None for row in tables(client)["price_history"])
    assert_integrity(client)


def test_deleted_shop_snapshot_survives_refused_generic_rename_restore_and_product_delete(client):
    shop = metadata(client, "supermarkets", "Nombre histórico que conservar")
    p = product(client, supermarket_id=shop["id"])
    other = product(client, "Producto ajeno")
    add(client, p)
    ok(client.delete(f"/api/supermarkets/{shop['id']}"))
    generic = by_name(client, "supermarkets", GENERIC["supermarkets"])
    assert client.put(f"/api/supermarkets/{generic['id']}", json={"name": "Genérica renombrada"}).status_code == 409
    historic = detail(client, p)["price_history"][0]
    assert historic["supermarket_name"] == shop["name"]
    assert historic["supermarket_deleted"] is True
    assert detail(client, other)["price_history"][0]["supermarket_name"] == GENERIC["supermarkets"]
    exported = backup(client)
    assert exported["version"] == 3
    snapshots = {row["product_id"]: row["supermarket_name_snapshot"] for row in exported["tables"]["price_history"]}
    assert snapshots == {p["id"]: shop["name"], other["id"]: None}
    ok(client.post("/api/restore", json=exported))
    unchanged(client, exported["tables"])
    assert detail(client, p)["price_history"][0] == historic
    deleted = ok(client.delete(f"/api/products/{p['id']}"))
    assert deleted["removed"]["price_history"] == len(p["price_history"])
    after = tables(client)
    assert all(row["product_id"] != p["id"] for row in after["price_history"])
    assert all(row["supermarket_name_snapshot"] is None for row in after["price_history"])
    assert client.get(f"/api/products/{p['id']}").status_code == 404
    assert detail(client, other)["id"] == other["id"]
    assert_integrity(client)


@pytest.mark.parametrize("damage", ["missing", "number", "boolean", "list", "object", "extra-column"])
def test_v3_restore_validates_snapshot_column_atomically(client, damage):
    product(client)
    original = backup(client)
    assert original["version"] == 3
    invalid = deepcopy(original)
    row = invalid["tables"]["price_history"][0]
    assert row["supermarket_name_snapshot"] is None
    if damage == "missing":
        del row["supermarket_name_snapshot"]
    elif damage == "extra-column":
        row["unexpected_snapshot"] = "no"
    else:
        row["supermarket_name_snapshot"] = {"number": 123, "boolean": True, "list": [], "object": {}}[damage]
    response = client.post("/api/restore", json=invalid)
    assert response.status_code == 422, response.text
    unchanged(client, original["tables"])


@pytest.mark.parametrize("version", [0, 4, True, "3"])
def test_restore_rejects_unsupported_or_noninteger_version_without_changes(client, version):
    product(client)
    original = backup(client)
    invalid = deepcopy(original)
    invalid["version"] = version
    assert client.post("/api/restore", json=invalid).status_code == 422
    unchanged(client, original["tables"])


@pytest.mark.parametrize("checked", [False, True])
@pytest.mark.parametrize("delta", [-1, 1])
def test_adjust_changes_only_quantity_preserving_checked_price_notes_and_history(client, checked, delta):
    p = product(client)
    original = add(client, p, checked=checked)
    before = tables(client)
    result = ok(client.post(f"/api/shopping/items/{original['id']}/adjust", json={"delta": delta}))
    current = next(row for row in items(result) if row["id"] == original["id"])
    expected_quantity = Decimal(str(original["quantity"])) + delta
    assert Decimal(str(current["quantity"])) == expected_quantity
    for key in original.keys() - {"quantity", "subtotal_cents"}:
        assert current[key] == original[key], key
    expected = deepcopy(before)
    next(row for row in expected["shopping_items"] if row["id"] == original["id"])["quantity"] = str(expected_quantity)
    unchanged(client, expected)
    assert line(client, p) == current


@pytest.mark.parametrize("quantity,delta,expected", [
    ("0.125", 1, "1.125"), ("1.5", -1, "0.5"), ("1.001", -1, "0.001"),
    ("99999", 1, "100000"), ("100000", -1, "99999"),
])
def test_adjust_accepts_exact_step_one_and_fractional_results(client, quantity, delta, expected):
    p = product(client)
    item = add(client, p, quantity)
    ok(client.post(f"/api/shopping/items/{item['id']}/adjust", json={"delta": delta}))
    assert Decimal(str(line(client, p)["quantity"])) == Decimal(expected)
    assert shopping(client)["count"] == 1


@pytest.mark.parametrize("quantity,delta", [
    ("0.5", -1), ("1", -1), ("0.001", -1), ("100000", 1), ("99999.5", 1),
])
def test_adjust_out_of_bounds_returns_422_without_removing_line_or_changing_data(client, quantity, delta):
    p = product(client)
    item = add(client, p, quantity, checked=True)
    before = tables(client)
    response = client.post(f"/api/shopping/items/{item['id']}/adjust", json={"delta": delta})
    assert response.status_code == 422, response.text
    unchanged(client, before)
    assert shopping(client)["count"] == 1


def test_adjust_one_and_half_to_half_then_refuses_another_minus_and_manual_edit_still_works(client):
    p = product(client)
    item = add(client, p, "1.5", checked=True)
    route = f"/api/shopping/items/{item['id']}/adjust"
    ok(client.post(route, json={"delta": -1}))
    assert line(client, p)["quantity"] == 0.5
    before = tables(client)
    assert client.post(route, json={"delta": -1}).status_code == 422
    unchanged(client, before)
    data = ok(client.patch(f"/api/shopping/items/{item['id']}", json={"quantity": "0.125"}))
    current = next(row for row in items(data) if row["id"] == item["id"])
    assert current["quantity"] == 0.125 and current["checked"] is True


@pytest.mark.parametrize("payload", [
    {}, {"delta": True}, {"delta": False}, {"delta": 1.0}, {"delta": -1.0},
    {"delta": "1"}, {"delta": "-1"}, {"delta": None}, {"delta": 0},
    {"delta": 2}, {"delta": -2}, {"delta": 1, "quantity": 4},
])
def test_adjust_delta_is_strict_integer_plus_or_minus_one(client, payload):
    p = product(client)
    item = add(client, p)
    before = tables(client)
    response = client.post(f"/api/shopping/items/{item['id']}/adjust", json=payload)
    assert response.status_code == 422, response.text
    unchanged(client, before)


def test_adjust_missing_item_returns_404_without_changes(client):
    before = tables(client)
    assert client.post("/api/shopping/items/999999/adjust", json={"delta": 1}).status_code == 404
    unchanged(client, before)


@pytest.mark.parametrize("deltas", [[1] * 24, [-1] * 24, [1, -1] * 12], ids=["sumas", "restas", "mixto"])
def test_concurrent_adjusts_are_atomic_without_lost_updates(client, deltas):
    p = product(client)
    item = add(client, p, "50.5", checked=True)
    before = tables(client)
    barrier = Barrier(6)

    def worker(delta):
        barrier.wait(timeout=20)
        response = client.post(f"/api/shopping/items/{item['id']}/adjust", json={"delta": delta})
        return response.status_code, response.text

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(worker, deltas))
    assert all(status == 200 for status, _ in results), results
    expected_quantity = Decimal(str(item["quantity"])) + sum(deltas)
    current = line(client, p)
    assert Decimal(str(current["quantity"])) == expected_quantity
    assert current["checked"] is True
    expected = deepcopy(before)
    expected["shopping_items"][0]["quantity"] = str(expected_quantity)
    unchanged(client, expected)


@pytest.mark.parametrize("quantity,delta,expected", [("1.5", -1, "0.5"), ("99998.5", 1, "99999.5")])
def test_concurrent_adjusts_enforce_bounds_inside_same_transaction(client, quantity, delta, expected):
    p = product(client)
    item = add(client, p, quantity, checked=True)
    before = tables(client)
    barrier = Barrier(6)

    def worker(_):
        barrier.wait(timeout=20)
        return client.post(f"/api/shopping/items/{item['id']}/adjust", json={"delta": delta}).status_code

    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses = list(executor.map(worker, range(6)))
    assert sorted(statuses) == [200] + [422] * 5, statuses
    assert Decimal(str(line(client, p)["quantity"])) == Decimal(expected)
    expected_tables = deepcopy(before)
    expected_tables["shopping_items"][0]["quantity"] = expected
    unchanged(client, expected_tables)


def test_clear_all_erases_only_shopping_and_is_idempotent(client):
    p = product(client)
    other = product(client, "Segundo producto")
    add(client, p, checked=True)
    add(client, other, checked=False)
    saved_recipe = recipe(client, "Receta y menú intactos", [p, other])
    plate(client, "Texto libre intacto", saved_recipe["id"])
    before = tables(client)
    expected_shopping = {"groups": [], "total_cents": 0, "pending_total_cents": 0,
                         "checked_total_cents": 0, "count": 0, "checked_count": 0}
    assert ok(client.delete("/api/shopping")) == expected_shopping
    assert shopping(client) == expected_shopping
    expected = {**before, "shopping_items": []}
    unchanged(client, expected)
    assert ok(client.delete("/api/shopping")) == expected_shopping
    unchanged(client, expected)
    assert_integrity(client)


def test_clear_checked_remains_separate_and_does_not_erase_pending_items(client):
    p = product(client)
    pending = product(client, "Pendiente")
    add(client, p, checked=True)
    remaining = add(client, pending)
    before = tables(client)
    data = ok(client.delete("/api/shopping/checked"))
    assert items(data) == [remaining]
    assert data["count"] == 1 and data["checked_count"] == 0
    expected = deepcopy(before)
    expected["shopping_items"] = [row for row in expected["shopping_items"] if not row["checked"]]
    unchanged(client, expected)


@pytest.mark.parametrize("operation", [
    "category-put", "category-delete", "supermarket-put", "supermarket-delete",
    "adjust", "clear-all", "clear-checked", "product-delete", "product-put", "price-post",
])
@pytest.mark.parametrize("csrf", [None, "0"], ids=["sin-cabecera", "cabecera-invalida"])
def test_v4_mutations_require_csrf_and_never_change_data_when_denied(client, operation, csrf):
    category = metadata(client, "categories", "Categoría CSRF")
    shop = metadata(client, "supermarkets", "Tienda CSRF")
    p = product(client, category_id=category["id"], supermarket_id=shop["id"])
    item = add(client, p, checked=True)
    routes = {
        "category-put": ("PUT", f"/api/categories/{category['id']}", {"name": "No cambiar"}),
        "category-delete": ("DELETE", f"/api/categories/{category['id']}", None),
        "supermarket-put": ("PUT", f"/api/supermarkets/{shop['id']}", {"name": "No cambiar"}),
        "supermarket-delete": ("DELETE", f"/api/supermarkets/{shop['id']}", None),
        "adjust": ("POST", f"/api/shopping/items/{item['id']}/adjust", {"delta": 1}),
        "clear-all": ("DELETE", "/api/shopping", None),
        "clear-checked": ("DELETE", "/api/shopping/checked", None),
        "product-delete": ("DELETE", f"/api/products/{p['id']}", None),
        "product-put": ("PUT", f"/api/products/{p['id']}", edit_payload(p, price_cents=999)),
        "price-post": ("POST", f"/api/products/{p['id']}/price", {"price_cents": 999}),
    }
    method, route, payload = routes[operation]
    before = tables(client)
    request = client.build_request(method, route, **({"json": payload} if payload is not None else {}))
    # headers={} no elimina la cabecera por defecto de TestClient.
    request.headers.pop("X-Menu-Compra", None)
    if csrf is not None:
        request.headers["X-Menu-Compra"] = csrf
    response = client.send(request)
    assert response.status_code == 403, response.text
    unchanged(client, before)
