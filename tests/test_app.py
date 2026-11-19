from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

HEADERS = {"X-Menu-Compra": "1"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as session:
        yield session


def product(client, name="Filetes de cerdo", price=525, category="Carne", supermarket_id=1):
    categories = client.get("/api/categories").json()
    category_id = next(c["id"] for c in categories if c["name"] == category)
    response = client.post("/api/products", json={"name": name, "category_id": category_id,
        "supermarket_id": supermarket_id, "price_cents": price, "unit": "kg"})
    assert response.status_code == 201, response.text
    return response.json()


def add(client, p, quantity=1, price=None):
    data = {"product_id": p["id"], "quantity": quantity}
    if price is not None:
        data["price_cents"] = price
    result = client.post("/api/shopping/items", json=data)
    assert result.status_code == 201, result.text
    return result.json()


def items(data):
    return [item for group in data["groups"] for item in group["items"]]


def dish(client, products):
    result = client.post("/api/dishes", json={"name": "Filetes de cerdo empanados", "ingredients": [
        {"product_id": p["id"], "quantity": q} for p, q in products]})
    assert result.status_code == 201, result.text
    return result.json()


def entry(client, dish_id=None, **kwargs):
    payload = {"date": "2026-11-12", "slot": "lunch", "text": "Filetes de cerdo empanados", "dish_id": dish_id, **kwargs}
    result = client.put("/api/menu", json=payload)
    assert result.status_code == 200, result.text
    return result.json()


def test_empty_bootstrap_and_categories(client):
    data = client.get("/api/bootstrap").json()
    assert data["products"] == data["dishes"] == []
    assert data["supermarkets"] == [{"id": 1, "name": "Sin especificar", "is_system": True}]
    assert data["categories"][-1]["name"] == "Congelados"
    assert data["categories"][-1]["is_frozen"] is True
    assert client.get("/api/health").json() == {"status": "ok", "version": "1.0.0"}
    assert client.get("/api/shopping").json()["total_cents"] == 0


def test_product_history_initial_edit_and_no_repeated_same_price(client):
    p = product(client)
    assert len(p["price_history"]) == 1
    assert p["price_history"][0]["price_cents"] == 525
    changed = client.post(f"/api/products/{p['id']}/price", json={"price_cents": 599}).json()
    assert changed["price_cents"] == 599
    assert [h["price_cents"] for h in changed["price_history"]] == [599, 525]
    assert changed["price_history"][0]["source"] == "ficha"
    assert len(client.post(f"/api/products/{p['id']}/price", json={"price_cents": 599}).json()["price_history"]) == 2
    assert client.get(f"/api/products/{p['id']}").json()["price_cents"] == 599


def test_history_preserves_supermarket_when_moving_product(client):
    p = product(client)
    shop = client.post("/api/supermarkets", json={"name": "Tienda de prueba"}).json()
    payload = {k: p[k] for k in ("name", "category_id", "supermarket_id", "unit", "notes", "price_cents")}
    payload["supermarket_id"] = shop["id"]
    changed = client.put(f"/api/products/{p['id']}", json=payload)
    assert changed.status_code == 200
    history = changed.json()["price_history"]
    assert [h["supermarket_name"] for h in history] == ["Tienda de prueba", "Sin especificar"]


def test_product_duplicates_are_per_supermarket(client):
    p = product(client)
    payload = {k: p[k] for k in ("name", "category_id", "supermarket_id", "unit", "notes", "price_cents")}
    payload["name"] = payload["name"].upper()
    assert client.post("/api/products", json=payload).status_code == 409
    shop = client.post("/api/supermarkets", json={"name": "Otra tienda"}).json()
    payload["supermarket_id"] = shop["id"]
    assert client.post("/api/products", json=payload).status_code == 201


def test_product_search_filter_and_literal_wildcards(client):
    p = product(client)
    product(client, "Leche 100%", category="Lácteos y huevos")
    assert len(client.get("/api/products", params={"q": "%"}).json()) == 1
    assert len(client.get("/api/products", params={"q": "cerdo"}).json()) == 1
    assert len(client.get("/api/products", params={"category_id": p["category_id"]}).json()) == 1
    assert client.get("/api/products", params={"supermarket_id": 999}).json() == []


def test_add_to_shopping_updates_price_and_history(client):
    p = product(client)
    data = add(client, p, quantity="0.5", price=600)
    item = items(data)[0]
    assert item["quantity"] == 0.5
    assert item["unit_price_cents"] == 600
    assert item["subtotal_cents"] == data["total_cents"] == 300
    updated = client.get(f"/api/products/{p['id']}").json()
    assert [h["price_cents"] for h in updated["price_history"]] == [600, 525]
    assert updated["price_history"][0]["source"] == "lista"


def test_catalog_change_reprices_existing_shopping_line(client):
    p = product(client, price=500)
    add(client, p, quantity=2)
    client.post(f"/api/products/{p['id']}/price", json={"price_cents": 650})
    data = client.get("/api/shopping").json()
    assert data["total_cents"] == 650 * 2
    assert items(data)[0]["unit_price_cents"] == 650


def test_group_order_frozen_always_last_even_sort_zero(client):
    frozen = product(client, "Guisantes", category="Congelados")
    meat = product(client, "Pollo", category="Carne")
    fruit = product(client, "Manzanas", category="Fruta")
    for p in (frozen, meat, fruit):
        add(client, p)
    data = client.get("/api/shopping").json()
    assert [g["name"] for g in data["groups"]] == ["Fruta", "Carne", "Congelados"]
    assert data["groups"][-1]["is_frozen"] is True


def test_shopping_updates_unit_supermarket_and_price_from_catalog(client):
    p = product(client)
    add(client, p)
    shop = client.post("/api/supermarkets", json={"name": "Nueva tienda"}).json()
    payload = {k: p[k] for k in ("name", "category_id", "supermarket_id", "unit", "notes", "price_cents")}
    payload.update(supermarket_id=shop["id"], unit="ud", price_cents=900)
    assert client.put(f"/api/products/{p['id']}", json=payload).status_code == 200
    item = items(client.get("/api/shopping").json())[0]
    assert item["unit"] == "ud"
    assert item["supermarket_name"] == "Nueva tienda"
    assert item["unit_price_cents"] == 900
    response = client.post("/api/shopping/items", json={"product_id": p["id"], "quantity": 1})
    assert response.status_code == 201
    assert items(client.get("/api/shopping").json())[0]["quantity"] == 2


def test_add_custom_frozen_category_is_sorted_last(client):
    category = client.post("/api/categories", json={"name": "Helados", "sort_order": 0, "is_frozen": True}).json()
    fresh = product(client)
    p = client.post("/api/products", json={"name": "Helado", "category_id": category["id"], "supermarket_id": 1, "price_cents": 300}).json()
    add(client, p)
    add(client, fresh)
    assert client.get("/api/shopping").json()["groups"][-1]["name"] == "Helados"


def test_duplicate_shopping_sums_quantity_and_uses_current_price(client):
    p = product(client, price=100)
    add(client, p, 1)
    data = add(client, p, 2, price=150)
    assert data["count"] == 1
    assert items(data)[0]["quantity"] == 3
    assert data["total_cents"] == 450


def test_readding_purchased_item_restarts_quantity(client):
    p = product(client)
    item_id = items(add(client, p, 3))[0]["id"]
    data = client.patch(f"/api/shopping/items/{item_id}", json={"checked": True}).json()
    assert data["checked_count"] == 1
    assert data["pending_total_cents"] == 0
    data = add(client, p, 1)
    assert items(data)[0]["quantity"] == 1
    assert items(data)[0]["checked"] is False


def test_shopping_edit_delete_and_clear_only_checked(client):
    p = product(client)
    second = product(client, "Arroz", category="Despensa")
    first_id = items(add(client, p))[0]["id"]
    add(client, second)
    changed = client.patch(f"/api/shopping/items/{first_id}", json={"checked": True, "quantity": 2, "note": "Corte fino"})
    assert changed.status_code == 200
    assert next(i for i in items(changed.json()) if i["id"] == first_id)["note"] == "Corte fino"
    data = client.delete("/api/shopping/checked").json()
    assert data["count"] == 1
    assert items(data)[0]["product_id"] == second["id"]
    assert client.delete(f"/api/shopping/items/{items(data)[0]['id']}").json()["count"] == 0


def test_rounding_half_up_and_fractional_quantities(client):
    p = product(client, price=1)
    data = add(client, p, "0.5")
    assert data["total_cents"] == 1


def test_shopping_overflow_rolls_back_price_history(client):
    p = product(client, price=100)
    add(client, p, 100000)
    response = client.post("/api/shopping/items", json={"product_id": p["id"], "quantity": 1, "price_cents": 200})
    assert response.status_code == 422
    unchanged = client.get(f"/api/products/{p['id']}").json()
    assert unchanged["price_cents"] == 100
    assert len(unchanged["price_history"]) == 1


def test_menu_manual_week_normalization_and_slots(client):
    lunch = entry(client)
    entry(client, text="Sopa", slot="dinner")
    data = client.get("/api/menu?week=2026-11-12").json()
    assert data["week"] == "2026-11-09"
    assert len(data["entries"]) == 2
    assert {i["slot"] for i in data["entries"]} == {"lunch", "dinner"}
    entry(client, text="Nuevo menú")
    assert len(client.get("/api/menu?week=2026-11-09").json()["entries"]) == 2
    assert client.delete(f"/api/menu/{lunch['id']}").status_code == 200
    entry(client, text="", slot="dinner")
    assert client.get("/api/menu?week=2026-11-12").json()["entries"] == []


def test_week_boundary_has_seven_days_only(client):
    monday = date(2026, 11, 9)
    for offset in (-1, 0, 6, 7):
        entry(client, date=(monday + timedelta(days=offset)).isoformat())
    assert len(client.get("/api/menu?week=2026-11-09").json()["entries"]) == 2


def test_dish_selected_ingredients_add_only_requested(client):
    pork = product(client)
    breadcrumbs = product(client, "Pan rallado", category="Despensa", price=100)
    recipe = dish(client, [(pork, "0.5"), (breadcrumbs, "0.1")])
    menu_entry = entry(client, recipe["id"])
    response = client.post(f"/api/menu/{menu_entry['id']}/ingredients", json={"product_ids": [pork["id"]]})
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert items(response.json())[0]["product_id"] == pork["id"]
    assert items(response.json())[0]["quantity"] == 0.5
    assert client.get("/api/dishes").json()[0]["ingredients"]


def test_empty_ingredient_selection_and_invalid_selection(client):
    pork = product(client)
    other = product(client, "Leche", category="Lácteos y huevos")
    recipe = dish(client, [(pork, 1)])
    menu_entry = entry(client, recipe["id"])
    route = f"/api/menu/{menu_entry['id']}/ingredients"
    assert client.post(route, json={"product_ids": []}).json()["count"] == 0
    assert client.post(route, json={"product_ids": [pork["id"], other["id"]]}).status_code == 422
    assert client.get("/api/shopping").json()["count"] == 0


def test_ingredients_selection_of_deleted_product_is_rejected_atomically(client):
    pork = product(client)
    other = product(client, "Pan rallado", category="Despensa")
    recipe = dish(client, [(pork, 1), (other, 1)])
    menu_entry = entry(client, recipe["id"])
    client.delete(f"/api/products/{other['id']}")
    response = client.post(f"/api/menu/{menu_entry['id']}/ingredients", json={"product_ids": [pork["id"], other["id"]]})
    assert response.status_code == 422
    assert client.get("/api/shopping").json()["count"] == 0


def test_dish_deletion_preserves_menu_text(client):
    p = product(client)
    recipe = dish(client, [(p, 1)])
    saved = entry(client, recipe["id"], text="")
    assert saved["text"] == recipe["name"]
    assert client.delete(f"/api/dishes/{recipe['id']}").status_code == 200
    current = client.get("/api/menu?week=2026-11-12").json()["entries"][0]
    assert current["text"] == recipe["name"]
    assert current["dish_id"] is None


def test_dish_edit_replaces_ingredients_and_keeps_menu_link(client):
    pork = product(client)
    other = product(client, "Pan rallado", category="Despensa")
    recipe = dish(client, [(pork, 1)])
    saved = entry(client, recipe["id"])
    response = client.put(f"/api/dishes/{recipe['id']}", json={"name": "Filetes empanados", "ingredients": [{"product_id": other["id"], "quantity": "0.2"}]})
    assert response.status_code == 200
    data = client.post(f"/api/menu/{saved['id']}/ingredients", json={"product_ids": [other["id"]]}).json()
    assert items(data)[0]["quantity"] == 0.2


def test_hard_delete_removes_product_history_and_existing_list(client):
    p = product(client)
    add(client, p)
    assert client.delete(f"/api/products/{p['id']}").status_code == 200
    assert client.get("/api/products").json() == []
    assert client.get("/api/products?include_archived=true").json() == []
    assert client.get(f"/api/products/{p['id']}").status_code == 404
    assert client.get("/api/shopping").json()["count"] == 0
    assert client.post("/api/shopping/items", json={"product_id": p["id"]}).status_code == 404
    tables = client.get("/api/backup").json()["tables"]
    assert tables["products"] == tables["price_history"] == tables["shopping_items"] == []


def test_text_export_and_json_backup(client):
    p = product(client)
    add(client, p, "0.5")
    response = client.get("/api/shopping/export")
    assert response.headers["content-type"].startswith("text/plain")
    assert "Filetes de cerdo" in response.text
    assert "2,63 €" in response.text
    backup = client.get("/api/backup")
    assert backup.json()["format"] == "menu-compra"
    assert "attachment" in backup.headers["content-disposition"]


def test_backup_round_trip_preserves_all_tables(client):
    p = product(client)
    recipe = dish(client, [(p, "0.5")])
    entry(client, recipe["id"])
    add(client, p, price=550)
    backup = client.get("/api/backup").json()
    product(client, "Extra", price=100)
    response = client.post("/api/restore", json=backup)
    assert response.status_code == 200, response.text
    assert response.json()["restored"] is True
    restored = client.get("/api/backup").json()
    assert restored["tables"] == backup["tables"]
    assert len(client.get("/api/products").json()) == 1


@pytest.mark.parametrize("damage", ["format", "version", "missing_table", "extra_column", "dangling_reference", "negative_price", "bad_quantity", "duplicate_id", "bad_history", "bad_menu_date"])
def test_invalid_restore_never_modifies_data(client, damage):
    p = product(client)
    add(client, p)
    entry(client)
    backup = client.get("/api/backup").json()
    invalid = deepcopy(backup)
    tables = invalid["tables"]
    if damage == "format":
        invalid["format"] = "otro"
    elif damage == "version":
        invalid["version"] = 99
    elif damage == "missing_table":
        del tables["dishes"]
    elif damage == "extra_column":
        tables["products"][0]["sql"] = "DROP TABLE products"
    elif damage == "dangling_reference":
        tables["products"][0]["category_id"] = 999
    elif damage == "negative_price":
        tables["products"][0]["price_cents"] = -1
    elif damage == "bad_quantity":
        tables["shopping_items"][0]["quantity"] = "NaN"
    elif damage == "duplicate_id":
        tables["products"].append(deepcopy(tables["products"][0]))
    elif damage == "bad_history":
        tables["price_history"][0]["price_cents"] = 1
    elif damage == "bad_menu_date":
        tables["menu_entries"][0]["date"] = "2026-30-90"
    response = client.post("/api/restore", json=invalid)
    assert response.status_code == 422, response.text
    assert client.get("/api/backup").json()["tables"] == backup["tables"]


@pytest.mark.parametrize("price", [-1, 1.5, "200", True, 100000001])
def test_invalid_prices(client, price):
    p = product(client)
    response = client.post(f"/api/products/{p['id']}/price", json={"price_cents": price})
    assert response.status_code == 422
    assert client.get(f"/api/products/{p['id']}").json()["price_cents"] == 525


@pytest.mark.parametrize("quantity", [0, -1, "NaN", "Infinity", "0.0001", 100001])
def test_invalid_quantities(client, quantity):
    p = product(client)
    assert client.post("/api/shopping/items", json={"product_id": p["id"], "quantity": quantity}).status_code == 422
    assert client.get("/api/shopping").json()["count"] == 0


@pytest.mark.parametrize("payload", [{}, {"checked": None}, {"quantity": None}, {"quantity": 0}, {"unexpected": 1}])
def test_invalid_shopping_patch(client, payload):
    p = product(client)
    item_id = items(add(client, p))[0]["id"]
    assert client.patch(f"/api/shopping/items/{item_id}", json=payload).status_code == 422


def test_invalid_menu_slot_and_missing_resources(client):
    assert client.put("/api/menu", json={"date": "2026-11-12", "slot": "breakfast", "text": "Pan"}).status_code == 422
    assert client.get("/api/products/999").status_code == 404
    assert client.delete("/api/menu/999").status_code == 404
    assert client.post("/api/shopping/items", json={"product_id": 999}).status_code == 404
    assert client.post("/api/menu/999/ingredients", json={"product_ids": []}).status_code == 404
    saved = entry(client)
    assert client.post(f"/api/menu/{saved['id']}/ingredients", json={"product_ids": []}).status_code == 400


def test_empty_names_and_duplicate_ingredients(client):
    assert client.post("/api/supermarkets", json={"name": "   "}).status_code == 422
    assert client.post("/api/categories", json={"name": ""}).status_code == 422
    p = product(client)
    assert client.post("/api/dishes", json={"name": "Plato", "ingredients": [{"product_id": p["id"]}, {"product_id": p["id"]}]}).status_code == 422


def test_csrf_header_required_for_every_mutation(client):
    response = client.post("/api/supermarkets", json={"name": "Ataque"}, headers={"X-Menu-Compra": "0"})
    assert response.status_code == 403
    assert client.get("/api/supermarkets").json() == [{"id": 1, "name": "Sin especificar", "is_system": True}]


def test_security_headers(client):
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]


def test_production_accepts_only_real_ingress_ip_not_headers(tmp_path):
    app = create_app(tmp_path, development=False)
    with TestClient(app, client=("198.51.100.9", 12345)) as denied:
        assert denied.get("/api/bootstrap", headers={"X-Forwarded-For": "172.30.32.2"}).status_code == 403
    with TestClient(app, client=("172.30.32.2", 12345)) as allowed:
        assert allowed.get("/api/bootstrap").status_code == 200
    with TestClient(app, client=("127.0.0.1", 12345)) as local:
        assert local.get("/api/health").status_code == 200
        assert local.get("/api/bootstrap").status_code == 403


def test_persistence_between_restarts(tmp_path):
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as first:
        p = product(first)
        entry(first)
        add(first, p)
    with TestClient(create_app(tmp_path, development=True), headers=HEADERS) as second:
        assert len(second.get("/api/products").json()) == 1
        assert second.get("/api/shopping").json()["count"] == 1
        assert len(second.get("/api/menu?week=2026-11-12").json()["entries"]) == 1
        assert len(second.get("/api/categories").json()) == 13


def test_concurrent_adds_do_not_lose_quantities(client):
    p = product(client, price=100)
    def worker(_):
        return client.post("/api/shopping/items", json={"product_id": p["id"], "quantity": "0.25"}).status_code
    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses = list(executor.map(worker, range(12)))
    assert statuses == [201] * 12
    data = client.get("/api/shopping").json()
    assert items(data)[0]["quantity"] == 3
    assert data["total_cents"] == 300
