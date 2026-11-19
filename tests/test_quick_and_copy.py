"""Alta rápida y duplicado seguro de semanas para la versión 0.3.0."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import app.main as backend
from test_app import HEADERS, product, items
from test_menu_v2 import plate


@pytest.fixture
def client(tmp_path):
    with TestClient(backend.create_app(tmp_path, development=True), headers=HEADERS) as session:
        yield session


def quick(client, name, **kwargs):
    response = client.post("/api/shopping/quick-add", json={"name": name, **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


def menu(client, week="2026-11-12"):
    return client.get("/api/menu", params={"week": week}).json()["entries"]


def test_new_name_creates_generic_product_and_shopping_atomically(client):
    data = quick(client, "Leche sin lactosa")
    p = data["product"]
    assert data["created"] is True
    assert p["name"] == "Leche sin lactosa"
    assert p["price_cents"] == 0
    assert p["unit"] == "ud"
    assert p["category_name"] == "Sin especificar"
    assert p["supermarket_name"] == "Sin especificar"
    assert p["notes"] == ""
    assert len(p["price_history"]) == 1 and p["price_history"][0]["price_cents"] == 0
    assert items(data["shopping"])[0]["unit_price_cents"] == 0
    exact = client.get(f"/api/products/{p['id']}").json()
    assert exact["name"] == p["name"] and exact["price_cents"] == 0
    assert client.get("/api/shopping").json()["count"] == 1


def test_new_name_does_not_inherit_price_from_previous_query(client):
    data = quick(client, "Producto nuevo", quantity="2.5", price_cents=999)
    assert data["product"]["price_cents"] == 0
    assert data["shopping"]["total_cents"] == 0
    assert items(data["shopping"])[0]["quantity"] == 2.5


def test_second_quick_add_reuses_product_and_accumulates(client):
    first = quick(client, "Nuevo")
    second = quick(client, "NUEVO")
    assert second["created"] is False
    assert first["product"]["id"] == second["product"]["id"]
    assert len(client.get("/api/products").json()) == 1
    assert items(second["shopping"])[0]["quantity"] == 2
    assert len(second["product"]["price_history"]) == 1


@pytest.mark.parametrize("stored,query", [("Atún", "ATÚN"), ("Filetes de cerdo", "Filetes"), ("Arroz integral", "integral")])
def test_unique_existing_product_needs_only_typed_name(client, stored, query):
    p = product(client, stored)
    matches = client.get("/api/products/matches", params={"name": query})
    assert matches.status_code == 200
    assert matches.json()["status"] == "unique"
    result = quick(client, query)
    assert result["created"] is False
    assert result["product"]["id"] == p["id"]
    assert items(result["shopping"])[0]["unit_price_cents"] == p["price_cents"]


def test_exact_match_has_priority_over_other_partial_names(client):
    exact = product(client, "Arroz")
    product(client, "Arroz integral")
    assert quick(client, "Arroz")["product"]["id"] == exact["id"]


@pytest.mark.parametrize("number", [2, 3])
def test_multiple_matches_require_selection_and_do_not_create(client, number):
    for index in range(number):
        product(client, f"Filetes variedad {index}")
    before = client.get("/api/backup").json()["tables"]
    matches = client.get("/api/products/matches?name=Filetes").json()
    assert matches["status"] == "choose" and len(matches["matches"]) == number
    response = client.post("/api/shopping/quick-add", json={"name": "Filetes"})
    assert response.status_code == 409
    assert response.json()["status"] == "choose" and len(response.json()["matches"]) == number
    assert client.get("/api/backup").json()["tables"] == before
    chosen = matches["matches"][-1]
    result = quick(client, "Filetes", product_id=chosen["id"])
    assert result["product"]["id"] == chosen["id"]


def test_identical_names_in_different_shops_require_choice(client):
    product(client, "Leche")
    shop = client.post("/api/supermarkets", json={"name": "Otra tienda"}).json()
    chosen = product(client, "Leche", supermarket_id=shop["id"], price=200)
    assert client.get("/api/products/matches?name=Leche").json()["status"] == "choose"
    result = quick(client, "Leche", product_id=chosen["id"], quantity=2)
    assert result["shopping"]["total_cents"] == 400
    assert items(result["shopping"])[0]["supermarket_name"] == "Otra tienda"


def test_matches_search_is_read_only_literal_and_name_only(client):
    p = product(client, "Zumo 100%")
    with client.app.state.database.connect(write=True) as connection:
        connection.execute("UPDATE products SET notes='Palabra exclusiva' WHERE id=?", (p["id"],))
    before = client.get("/api/backup").json()["tables"]
    assert client.get("/api/products/matches", params={"name": "%"}).json()["status"] == "unique"
    assert client.get("/api/products/matches?name=exclusiva").json()["status"] == "missing"
    assert client.get("/api/products/matches?name=Ausente").json()["matches"] == []
    assert client.get("/api/backup").json()["tables"] == before


def test_existing_price_can_be_changed_without_repricing_other_lines(client):
    p = product(client)
    result = quick(client, p["name"], price_cents=600)
    assert result["product"]["price_cents"] == 600
    assert [h["price_cents"] for h in result["product"]["price_history"]] == [600, 525]
    assert items(result["shopping"])[0]["unit_price_cents"] == 600


def test_quick_add_rechecks_catalog_after_search(client):
    product(client, "Leche")
    assert client.get("/api/products/matches?name=Leche").json()["status"] == "unique"
    shop = client.post("/api/supermarkets", json={"name": "Nueva tienda"}).json()
    product(client, "Leche", supermarket_id=shop["id"])
    response = client.post("/api/shopping/quick-add", json={"name": "Leche"})
    assert response.status_code == 409 and len(response.json()["matches"]) == 2
    assert client.get("/api/shopping").json()["count"] == 0


def test_quick_add_does_not_save_menu_drafts(client):
    quick(client, "Plato todavía no guardado")
    assert menu(client) == []


def test_generic_creation_rolls_back_if_shopping_write_fails(client, monkeypatch):
    original = client.get("/api/backup").json()["tables"]
    def fail(*args, **kwargs):
        raise HTTPException(409, "Fallo deliberado de almacenamiento para verificar rollback")
    monkeypatch.setattr(backend, "add_shopping", fail)
    response = client.post("/api/shopping/quick-add", json={"name": "No persistir"})
    assert response.status_code == 409
    assert client.get("/api/backup").json()["tables"] == original


def test_deleted_product_can_be_recreated_without_old_history(client):
    p = product(client, "Eliminado", price=700)
    client.delete(f"/api/products/{p['id']}")
    response = client.post("/api/shopping/quick-add", json={"name": p["name"]})
    assert response.status_code == 201 and response.json()["created"] is True
    new = response.json()["product"]
    assert new["id"] != p["id"] and new["price_cents"] == 0
    assert [h["price_cents"] for h in new["price_history"]] == [0]
    assert client.get(f"/api/products/{p['id']}").status_code == 404


def test_concurrent_quick_creation_creates_one_catalog_record(client):
    def worker(_):
        return client.post("/api/shopping/quick-add", json={"name": "Producto concurrente"}).status_code
    with ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(worker, range(10)))
    assert statuses == [201] * 10
    assert len(client.get("/api/products").json()) == 1
    data = client.get("/api/shopping").json()
    assert data["count"] == 1 and items(data)[0]["quantity"] == 10


@pytest.mark.parametrize("payload", [{"name": ""}, {"name": "   "}, {"name": "x" * 181}, {"name": "Nuevo", "quantity": 0}, {"name": "Nuevo", "price_cents": -1}, {"name": "Nuevo", "note": "No se admite nota"}])
def test_invalid_quick_add_never_creates_data(client, payload):
    before = client.get("/api/backup").json()["tables"]
    assert client.post("/api/shopping/quick-add", json=payload).status_code == 422
    assert client.get("/api/backup").json()["tables"] == before


@pytest.mark.parametrize("name", ["", "  ", "x" * 181])
def test_invalid_match_query(client, name):
    assert client.get("/api/products/matches", params={"name": name}).status_code == 422


def test_copy_keeps_source_and_maps_each_day_and_slot_to_next_week(client):
    source = [plate(client, "Filetes", "lunch", "2026-11-09"), plate(client, "Patatas", "lunch", "2026-11-09"), plate(client, "Pollo", "dinner", "2026-11-15")]
    quick(client, "Compra intacta")
    before = client.get("/api/backup").json()["tables"]
    response = client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["source_week"] == "2026-11-09" and data["target_week"] == "2026-11-16"
    assert data["copied"] == len(source) and data["skipped"] == 0
    assert menu(client) == source
    target = menu(client, "2026-11-16")
    assert [(e["date"], e["slot"], e["text"]) for e in target] == [((date.fromisoformat(e["date"]) + timedelta(days=7)).isoformat(), e["slot"], e["text"]) for e in source]
    after = client.get("/api/backup").json()["tables"]
    assert {k: v for k, v in after.items() if k != "menu_entries"} == {k: v for k, v in before.items() if k != "menu_entries"}


def test_copy_preserves_existing_destination_and_skips_already_present(client):
    plate(client, "Filetes", day="2026-11-12")
    plate(client, "Patatas", day="2026-11-12")
    destination = plate(client, "Ensalada", day="2026-11-19")
    exact = plate(client, "FILETES", day="2026-11-19")
    result = client.post("/api/menu/duplicate-week", json={"week": "2026-11-09"}).json()
    assert result["copied"] == 1 and result["skipped"] == 1
    target = menu(client, "2026-11-16")
    assert [e["id"] for e in target[:2]] == [destination["id"], exact["id"]]
    assert [e["text"] for e in target] == ["Ensalada", "FILETES", "Patatas"]
    repeated = client.post("/api/menu/duplicate-week", json={"week": "2026-11-09"}).json()
    assert repeated["copied"] == 0 and repeated["skipped"] == 2
    assert menu(client, "2026-11-16") == target


def test_copy_respects_multiplicity_of_identical_source_plates(client):
    plate(client, "Pollo")
    plate(client, "Pollo")
    plate(client, "POLLO", day="2026-11-19")
    first = client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"}).json()
    assert first["copied"] == 1 and first["skipped"] == 1
    assert len(menu(client, "2026-11-19")) == 2
    second = client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"}).json()
    assert second["copied"] == 0 and second["skipped"] == 2


def test_full_destination_rolls_back_the_entire_week(client):
    plate(client, "Primero", day="2026-11-09")
    plate(client, "Segundo", day="2026-11-12")
    response = client.post("/api/menu/batch", json={"date": "2026-11-19", "slot": "lunch", "texts": [f"Existente {n}" for n in range(20)]})
    assert response.status_code == 201
    before = client.get("/api/backup").json()["tables"]
    response = client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"})
    assert response.status_code == 409
    assert client.get("/api/backup").json()["tables"] == before


def test_empty_week_does_not_touch_existing_destination(client):
    plate(client, "Destino", day="2026-11-19")
    before = deepcopy(client.get("/api/backup").json()["tables"])
    assert client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"}).status_code == 409
    assert client.get("/api/backup").json()["tables"] == before


def test_copy_across_year_boundary(client):
    plate(client, "Cena", "dinner", "2026-12-31")
    result = client.post("/api/menu/duplicate-week", json={"week": "2026-12-31"})
    assert result.status_code == 201
    assert result.json()["target_week"] == "2027-01-04"
    assert result.json()["entries"][0]["date"] == "2027-01-07"


def test_concurrent_week_copies_do_not_duplicate_data(client):
    plate(client, "Filetes")
    plate(client, "Patatas")
    def worker(_):
        return client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"})
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, range(2)))
    assert all(r.status_code == 201 for r in results)
    assert sum(r.json()["copied"] for r in results) == 2
    assert len(menu(client, "2026-11-19")) == 2


@pytest.mark.parametrize("week", ["9999-12-31", "9999-12-25", "no-es-fecha"])
def test_copy_extreme_or_invalid_dates_returns_validation_error(client, week):
    assert client.post("/api/menu/duplicate-week", json={"week": week}).status_code == 422


def test_new_endpoints_require_csrf(client):
    assert client.post("/api/shopping/quick-add", json={"name": "No autorizado"}, headers={"X-Menu-Compra": "0"}).status_code == 403
    assert client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"}, headers={"X-Menu-Compra": "0"}).status_code == 403
    assert client.get("/api/products").json() == []
