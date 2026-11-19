"""Regresiones detectadas durante la revisión independiente."""
from fastapi.testclient import TestClient
import pytest

from app.db import now
from app.main import create_app
from test_app import HEADERS, product, add, dish, entry


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as session:
        yield session


def test_unit_change_cannot_silently_change_recipe_quantities(client):
    p = product(client)
    recipe = dish(client, [(p, "0.5")])
    payload = {key: p[key] for key in ("name", "category_id", "supermarket_id", "unit", "notes", "price_cents")}
    payload["unit"] = "saco 10 kg"
    response = client.put(f"/api/products/{p['id']}", json=payload)
    assert response.status_code == 409
    assert client.get(f"/api/products/{p['id']}").json()["unit"] == "kg"
    ingredients = client.get("/api/dishes").json()[0]["ingredients"]
    assert ingredients[0]["quantity"] == 0.5
    assert ingredients[0]["unit"] == "kg"
    saved = entry(client, recipe["id"])
    assert client.post(f"/api/menu/{saved['id']}/ingredients", json={"product_ids": [p["id"]]}).status_code == 200


@pytest.mark.parametrize("name,query", [("Atún", "ATÚN"), ("Salmón", "SALMÓN"), ("PIÑA", "piña")])
def test_spanish_unicode_product_search_and_uniqueness(client, name, query):
    p = product(client, name)
    result = client.get("/api/products", params={"q": query})
    assert [row["id"] for row in result.json()] == [p["id"]]
    payload = {key: p[key] for key in ("name", "category_id", "supermarket_id", "unit", "notes", "price_cents")}
    payload["name"] = query
    assert client.post("/api/products", json=payload).status_code == 409


def test_spanish_unicode_dish_search_and_uniqueness(client):
    response = client.post("/api/dishes", json={"name": "Salmón con piña"})
    assert response.status_code == 201
    assert len(client.get("/api/dishes", params={"q": "SALMÓN"}).json()) == 1
    assert client.post("/api/dishes", json={"name": "SALMÓN CON PIÑA"}).status_code == 409


def test_restore_inserts_normalized_fields_and_remains_restorable(client):
    p = product(client)
    backup = client.get("/api/backup").json()
    backup["tables"]["products"][0]["name"] = "   Filetes de cerdo   "
    backup["tables"]["products"][0]["unit"] = "kg" + " " * 21
    assert client.post("/api/restore", json=backup).status_code == 200
    restored = client.get(f"/api/products/{p['id']}").json()
    assert restored["name"] == "Filetes de cerdo"
    assert restored["unit"] == "kg"
    add(client, restored)
    second_backup = client.get("/api/backup").json()
    assert client.post("/api/restore", json=second_backup).status_code == 200


def test_backup_over_eight_megabytes_can_be_restored(client):
    p = product(client)
    timestamp = now()
    with client.app.state.database.connect(write=True) as connection:
        for number in range(2100):
            row_id = connection.execute("INSERT INTO products(name,category_id,supermarket_id,unit,notes,price_cents,updated_at) VALUES(?,?,?,?,?,?,?)",
                (f"Producto grande {number}", p["category_id"], 1, "ud", "x" * 4000, 100, timestamp)).lastrowid
            connection.execute("INSERT INTO price_history(product_id,supermarket_id,price_cents,recorded_at,source) VALUES(?,?,?,?,?)",
                (row_id, 1, 100, timestamp, "alta"))
    backup = client.get("/api/backup")
    assert backup.status_code == 200
    assert len(backup.content) > 8 * 1024 * 1024
    response = client.post("/api/restore", content=backup.content, headers={"Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["products"] == 2101
    assert len(client.get("/api/products").json()) == 2101


def test_oversized_identifiers_are_validation_errors(client):
    enormous = 9_223_372_036_854_775_808
    assert client.get(f"/api/products/{enormous}").status_code == 422
    assert client.get("/api/products", params={"category_id": enormous}).status_code == 422
    assert client.post("/api/shopping/items", json={"product_id": enormous}).status_code == 422


def test_last_representable_week_does_not_overflow(client):
    response = client.get("/api/menu?week=9999-12-31")
    assert response.status_code == 200
    assert response.json() == {"week": "9999-12-27", "entries": []}
