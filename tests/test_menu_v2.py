"""Menú 0.2: varios platos y compra directa por coincidencia de nombre."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db import SCHEMA, SEED_CATEGORIES, unicode_nocase, now
from app.main import create_app
from test_app import HEADERS, product, items


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as session:
        yield session


def plate(client, name="Filetes de cerdo", slot="lunch", day="2026-11-12"):
    response = client.post("/api/menu", json={"date": day, "slot": slot, "text": name})
    assert response.status_code == 201, response.text
    return response.json()


def week(client):
    return client.get("/api/menu?week=2026-11-12").json()["entries"]


def test_multiple_plates_same_meal_and_independent_dinner(client):
    response = client.post("/api/menu/batch", json={"date": "2026-11-12", "slot": "lunch", "texts": ["Filetes", "Patatas"]})
    assert response.status_code == 201
    assert [e["position"] for e in response.json()["entries"]] == [0, 1]
    plate(client, "Ensalada")
    plate(client, "Arroz", "dinner")
    plate(client, "Pollo", "dinner")
    entries = week(client)
    assert [e["text"] for e in entries if e["slot"] == "lunch"] == ["Filetes", "Patatas", "Ensalada"]
    assert [e["text"] for e in entries if e["slot"] == "dinner"] == ["Arroz", "Pollo"]


def test_edit_and_delete_only_target_plate(client):
    first = plate(client, "Filetes")
    second = plate(client, "Patatas")
    result = client.put(f"/api/menu/{first['id']}", json={"date": first["date"], "slot": "lunch", "text": "Pollo"})
    assert result.status_code == 200
    assert [e["text"] for e in week(client)] == ["Pollo", "Patatas"]
    assert client.delete(f"/api/menu/{first['id']}").status_code == 200
    assert [e["id"] for e in week(client)] == [second["id"]]


def test_legacy_put_does_not_destroy_siblings(client):
    plate(client, "Filetes")
    other = plate(client, "Patatas")
    assert client.put("/api/menu", json={"date": "2026-11-12", "slot": "lunch", "text": "Pollo"}).status_code == 200
    assert [e["text"] for e in week(client)] == ["Pollo", "Patatas"]
    client.put("/api/menu", json={"date": "2026-11-12", "slot": "lunch", "text": ""})
    assert [e["id"] for e in week(client)] == [other["id"]]


@pytest.mark.parametrize("texts", [[], ["Filetes", "   "], ["A"] * 21, ["A" * 181]])
def test_invalid_batch_is_atomic(client, texts):
    response = client.post("/api/menu/batch", json={"date": "2026-11-12", "slot": "lunch", "texts": texts})
    assert response.status_code == 422
    assert week(client) == []


def test_batch_capacity_rollback_and_edit_full_meal(client):
    response = client.post("/api/menu/batch", json={"date": "2026-11-12", "slot": "lunch", "texts": [f"Plato {i}" for i in range(19)]})
    assert response.status_code == 201
    response = client.post("/api/menu/batch", json={"date": "2026-11-12", "slot": "lunch", "texts": ["Veinte", "Veintiuno"]})
    assert response.status_code == 409
    assert len(week(client)) == 19
    last = plate(client, "Veinte")
    assert client.post("/api/menu", json={"date": "2026-11-12", "slot": "lunch", "text": "Extra"}).status_code == 409
    assert client.put(f"/api/menu/{last['id']}", json={"date": "2026-11-12", "slot": "lunch", "text": "Último"}).status_code == 200
    assert len(week(client)) == 20


def test_unique_exact_name_adds_without_choosing_product(client):
    p = product(client)
    e = plate(client)
    match = client.get(f"/api/menu/{e['id']}/matches").json()
    assert match["status"] == match["match_type"] == "exact"
    assert [m["id"] for m in match["matches"]] == [p["id"]]
    response = client.post(f"/api/menu/{e['id']}/shopping", json={})
    assert response.status_code == 201
    assert items(response.json())[0]["product_id"] == p["id"]
    assert items(response.json())[0]["quantity"] == 1
    assert items(response.json())[0]["unit_price_cents"] == p["price_cents"]


def test_exact_name_wins_over_partial_names(client):
    exact = product(client)
    product(client, "Filetes de cerdo adobados")
    e = plate(client)
    match = client.get(f"/api/menu/{e['id']}/matches").json()
    assert match["status"] == "exact"
    assert [m["id"] for m in match["matches"]] == [exact["id"]]


def test_multiple_exact_names_in_shops_require_explicit_choice(client):
    first = product(client)
    shop = client.post("/api/supermarkets", json={"name": "Otra tienda"}).json()
    second = product(client, supermarket_id=shop["id"], price=650)
    e = plate(client)
    match = client.get(f"/api/menu/{e['id']}/matches").json()
    assert match["status"] == "choose" and match["match_type"] == "exact"
    assert {p["id"] for p in match["matches"]} == {first["id"], second["id"]}
    assert client.post(f"/api/menu/{e['id']}/shopping", json={}).status_code == 409
    assert client.get("/api/shopping").json()["count"] == 0
    chosen = client.post(f"/api/menu/{e['id']}/shopping", json={"product_id": second["id"], "quantity": "0.5", "price_cents": 700})
    assert chosen.status_code == 201
    assert items(chosen.json())[0]["supermarket_id"] == shop["id"]
    assert chosen.json()["total_cents"] == 350
    assert client.get(f"/api/products/{second['id']}").json()["price_cents"] == 700


@pytest.mark.parametrize("names", [["Filetes de cerdo"], ["Filetes de cerdo", "Filetes de pollo"]])
def test_partial_match_is_never_added_automatically(client, names):
    for name in names:
        product(client, name)
    e = plate(client, "Filetes")
    match = client.get(f"/api/menu/{e['id']}/matches").json()
    assert match["status"] == "choose" and match["match_type"] == "partial"
    assert len(match["matches"]) == len(names)
    assert client.post(f"/api/menu/{e['id']}/shopping", json={}).status_code == 409
    assert client.get("/api/shopping").json()["count"] == 0


def test_missing_name_can_be_created_and_added_in_place(client):
    e = plate(client, "Arroz integral")
    match = client.get(f"/api/menu/{e['id']}/matches").json()
    assert match == {"entry_id": e["id"], "text": "Arroz integral", "status": "missing", "match_type": "none", "matches": []}
    assert client.post(f"/api/menu/{e['id']}/shopping", json={}).status_code == 409
    created = product(client, "Arroz integral", category="Despensa", price=130)
    response = client.post(f"/api/menu/{e['id']}/shopping", json={"product_id": created["id"]})
    assert response.status_code == 201
    assert items(response.json())[0]["product_name"] == "Arroz integral"


@pytest.mark.parametrize("stored,typed", [("Atún", " ATÚN "), ("PIÑA", "piña"), ("Filetes de cerdo", "FILETES DE CERDO")])
def test_exact_matching_uses_unicode_casefold(client, stored, typed):
    product(client, stored)
    e = plate(client, typed)
    assert client.get(f"/api/menu/{e['id']}/matches").json()["status"] == "exact"
    assert client.post(f"/api/menu/{e['id']}/shopping", json={}).status_code == 201


def test_matching_is_literal_name_only_and_ignores_deleted(client):
    p = product(client, "Leche 100%")
    other = product(client, "Producto", category="Otros")
    with client.app.state.database.connect(write=True) as connection:
        connection.execute("UPDATE products SET notes='Filetes' WHERE id=?", (other["id"],))
    e = plate(client, "%")
    assert [m["id"] for m in client.get(f"/api/menu/{e['id']}/matches").json()["matches"]] == [p["id"]]
    e2 = plate(client, "Filetes")
    assert client.get(f"/api/menu/{e2['id']}/matches").json()["status"] == "missing"
    client.delete(f"/api/products/{p['id']}")
    assert client.get(f"/api/menu/{e['id']}/matches").json()["status"] == "missing"
    assert client.post(f"/api/menu/{e['id']}/shopping", json={"product_id": p["id"]}).status_code == 404


def test_match_is_rechecked_when_adding_after_catalog_changes(client):
    product(client)
    e = plate(client)
    assert client.get(f"/api/menu/{e['id']}/matches").json()["status"] == "exact"
    shop = client.post("/api/supermarkets", json={"name": "Nueva"}).json()
    product(client, supermarket_id=shop["id"])
    assert client.post(f"/api/menu/{e['id']}/shopping", json={}).status_code == 409
    assert client.get("/api/shopping").json()["count"] == 0


def test_adding_separate_plates_keeps_category_order_and_prices(client):
    product(client, "Filetes", price=500)
    product(client, "Patatas", price=200, category="Congelados")
    frozen = plate(client, "Patatas")
    meat = plate(client, "Filetes")
    client.post(f"/api/menu/{frozen['id']}/shopping", json={})
    response = client.post(f"/api/menu/{meat['id']}/shopping", json={})
    assert [g["name"] for g in response.json()["groups"]] == ["Carne", "Congelados"]
    assert response.json()["total_cents"] == 700


def test_concurrent_menu_creations_keep_every_plate(client):
    def worker(index):
        return client.post("/api/menu", json={"date": "2026-11-12", "slot": "lunch", "text": f"Plato {index}"}).status_code
    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses = list(executor.map(worker, range(8)))
    assert statuses == [201] * 8
    assert len({e["id"] for e in week(client)}) == 8
    assert [e["position"] for e in week(client)] == list(range(8))


def test_new_backup_preserves_multiple_plates(client):
    plate(client, "Filetes")
    plate(client, "Patatas")
    backup = client.get("/api/backup").json()
    assert backup["version"] == 3
    assert client.post("/api/restore", json=backup).status_code == 200
    assert [e["text"] for e in week(client)] == ["Filetes", "Patatas"]


def test_restore_version_one_upgrades_without_losing_data(client):
    p = product(client)
    e = plate(client)
    client.post(f"/api/menu/{e['id']}/shopping", json={})
    original = client.get("/api/backup").json()
    old = deepcopy(original)
    old["version"] = 1
    for row in old["tables"]["menu_entries"]:
        del row["position"]
    for row in old["tables"]["price_history"]:
        del row["supermarket_name_snapshot"]
    response = client.post("/api/restore", json=old)
    assert response.status_code == 200, response.text
    assert client.get("/api/backup").json()["tables"] == original["tables"]
    assert client.get(f"/api/products/{p['id']}").json()["price_cents"] == p["price_cents"]
    plate(client, "Patatas")
    assert len(week(client)) == 2


def test_database_one_is_migrated_preserving_ids_and_legacy_recipes(tmp_path):
    legacy = SCHEMA.replace("position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0)", "UNIQUE(date,slot)").replace(",\n supermarket_name_snapshot TEXT", "")
    connection = sqlite3.connect(tmp_path / "menu_compra.sqlite3")
    connection.create_collation("NOCASE", unicode_nocase)
    connection.executescript(legacy)
    connection.executemany("INSERT INTO categories(name,sort_order,is_frozen) VALUES(?,?,?)", SEED_CATEGORIES)
    connection.execute("INSERT INTO supermarkets(name) VALUES('Mi tienda')")
    connection.execute("INSERT INTO products(id,name,category_id,supermarket_id,unit,price_cents,updated_at) VALUES(17,'Filetes',3,1,'kg',500,?)", (now(),))
    connection.execute("INSERT INTO price_history(product_id,supermarket_id,price_cents,recorded_at,source) VALUES(17,1,500,?,'alta')", (now(),))
    connection.execute("INSERT INTO dishes(id,name) VALUES(8,'Receta anterior')")
    connection.execute("INSERT INTO dish_ingredients(dish_id,product_id,quantity) VALUES(8,17,'0.5')")
    connection.execute("INSERT INTO menu_entries(id,date,slot,text,dish_id) VALUES(31,'2026-11-12','lunch','Filetes',8)")
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as migrated:
        assert week(migrated) == [{"id": 31, "date": "2026-11-12", "slot": "lunch", "text": "Filetes", "dish_id": 8, "position": 0}]
        assert migrated.get("/api/products/17").json()["price_cents"] == 500
        assert migrated.get("/api/dishes").json()[0]["ingredients"][0]["quantity"] == 0.5
        second = plate(migrated, "Patatas")
        assert second["id"] > 31 and second["position"] == 1
        assert len(week(migrated)) == 2
        with migrated.app.state.database.connect() as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
            assert conn.execute("PRAGMA foreign_key_check").fetchone() is None
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as restarted:
        assert len(week(restarted)) == 2


def test_new_routes_require_csrf_and_real_target(client):
    e = plate(client)
    assert client.post(f"/api/menu/{e['id']}/shopping", json={}, headers={"X-Menu-Compra": "0"}).status_code == 403
    assert client.get("/api/menu/999/matches").status_code == 404
    assert client.post("/api/menu/999/shopping", json={}).status_code == 404
