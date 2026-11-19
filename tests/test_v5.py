"""Valores reservados, migración de nombres y contador de clasificación 0.5."""
from copy import deepcopy
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from test_app import HEADERS


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as session:
        yield session


def generic(client, kind):
    return next(r for r in client.get(f"/api/{kind}").json() if r["name"] == "Sin especificar")


def tables(client):
    return client.get("/api/backup").json()["tables"]


def new(client, name):
    response = client.post("/api/shopping/quick-add", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["product"]


@pytest.mark.parametrize("kind", ["categories", "supermarkets"])
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("used", [False, True])
def test_reserved_values_cannot_be_changed_or_removed_even_when_empty(client, kind, method, used):
    if used:
        new(client, "Producto pendiente")
    reserved = generic(client, kind)
    assert reserved["is_system"] is True
    before = tables(client)
    kwargs = {"json": {"name": "No modificar"}} if method == "PUT" else {}
    response = client.request(method, f"/api/{kind}/{reserved['id']}", **kwargs)
    assert response.status_code == 409, response.text
    assert tables(client) == before
    assert generic(client, kind)["id"] == reserved["id"]


def test_reserved_category_cannot_change_order_or_frozen_flag(client):
    reserved = generic(client, "categories")
    before = tables(client)
    response = client.put(f"/api/categories/{reserved['id']}", json={"name": "Sin especificar", "sort_order": 1, "is_frozen": True})
    assert response.status_code == 409
    assert tables(client) == before


def test_uncategorized_counter_tracks_classify_delete_and_ignores_generic_shop(client):
    assert client.get("/api/bootstrap").json()["uncategorized_count"] == 0
    first = new(client, "Pendiente A")
    second = new(client, "Pendiente B")
    assert first["category_name"] == second["category_name"] == "Sin especificar"
    assert client.get("/api/bootstrap").json()["uncategorized_count"] == 2
    meat = next(c for c in client.get("/api/categories").json() if c["name"] == "Carne")
    payload = {k: first[k] for k in ("name", "category_id", "supermarket_id", "unit", "price_cents", "notes")}
    payload["category_id"] = meat["id"]
    assert client.put(f"/api/products/{first['id']}", json=payload).status_code == 200
    assert client.get(f"/api/products/{first['id']}").json()["supermarket_name"] == "Sin especificar"
    assert client.get("/api/bootstrap").json()["uncategorized_count"] == 1
    assert client.delete(f"/api/products/{second['id']}").status_code == 200
    assert client.get("/api/bootstrap").json()["uncategorized_count"] == 0


def test_counter_counts_product_records_in_different_shops(client):
    category = generic(client, "categories")
    shops = [generic(client, "supermarkets"), client.post("/api/supermarkets", json={"name": "Otra"}).json()]
    for shop in shops:
        assert client.post("/api/products", json={"name": "Mismo nombre", "category_id": category["id"], "supermarket_id": shop["id"], "unit": "ud", "price_cents": 0}).status_code == 201
    assert client.get("/api/bootstrap").json()["uncategorized_count"] == 2


@pytest.mark.parametrize("both", [False, True])
def test_sqlite_v3_generic_category_is_renamed_or_merged_without_product_loss(tmp_path, both):
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as original:
        p = new(original, "Producto de migración")
        original.post(f"/api/shopping/items/{original.get('/api/shopping').json()['groups'][0]['items'][0]['id']}/adjust", json={"delta": 1})
        before = tables(original)
        category_id = p["category_id"]
    with sqlite3.connect(tmp_path / "menu_compra.sqlite3") as connection:
        connection.execute("UPDATE categories SET name='Sin categoría' WHERE id=?", (category_id,))
        expected_id = category_id
        if both:
            expected_id = connection.execute("INSERT INTO categories(name,sort_order,is_frozen) VALUES('Sin especificar',1,1)").lastrowid
        connection.execute("PRAGMA user_version=3")
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as migrated:
        after = tables(migrated)
        reserved = generic(migrated, "categories")
        assert reserved["id"] == expected_id
        assert reserved["sort_order"] == 110 and reserved["is_frozen"] is False
        assert all(c["name"] != "Sin categoría" for c in after["categories"])
        expected_products = deepcopy(before["products"])
        expected_products[0]["category_id"] = expected_id
        assert after["products"] == expected_products
        for table in ("price_history", "shopping_items", "menu_entries", "dishes", "dish_ingredients"):
            assert after[table] == before[table]
        assert migrated.get("/api/bootstrap").json()["uncategorized_count"] == 1
        with migrated.app.state.database.connect() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_restore_normalizes_old_generic_and_reports_actual_counts(client):
    p = new(client, "Restaurar genérico")
    backup = client.get("/api/backup").json()
    old = deepcopy(backup)
    next(c for c in old["tables"]["categories"] if c["id"] == p["category_id"])["name"] = "Sin categoría"
    response = client.post("/api/restore", json=old)
    assert response.status_code == 200, response.text
    after = tables(client)
    assert response.json()["counts"] == {name: len(rows) for name, rows in after.items()}
    assert client.get(f"/api/products/{p['id']}").json()["category_name"] == "Sin especificar"
    assert after["price_history"] == backup["tables"]["price_history"]
    assert client.get("/api/bootstrap").json()["uncategorized_count"] == 1


def test_restore_empty_legacy_keeps_reserved_values_available(client):
    backup = client.get("/api/backup").json()
    backup["tables"]["categories"] = []
    backup["tables"]["supermarkets"] = []
    response = client.post("/api/restore", json=backup)
    assert response.status_code == 200, response.text
    assert generic(client, "categories")["is_system"]
    assert generic(client, "supermarkets")["is_system"]
    assert response.json()["counts"]["categories"] == 1
    assert response.json()["counts"]["supermarkets"] == 1
    assert client.get("/api/bootstrap").json()["uncategorized_count"] == 0


def test_legacy_category_name_is_not_reintroduced_by_crud(client):
    before = tables(client)
    assert client.post("/api/categories", json={"name": "Sin categoría"}).status_code == 409
    assert tables(client) == before
