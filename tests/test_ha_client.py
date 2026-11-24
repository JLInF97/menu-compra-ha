"""Cliente aiohttp y acciones contra FastAPI/SQLite reales (no API simulada)."""
import asyncio
from contextlib import asynccontextmanager
import math

import pytest

from test_ha_support import aiohttp, api, create_product, pure_module, real_backend, ui
from test_ha_support import anyio_backend as anyio_backend

actions = pure_module("actions")
settings = pure_module("settings")


@pytest.mark.anyio
async def test_client_real_shopping_menu_and_catalogue():
    async with real_backend() as b:
        assert (await b.client.health())["version"] == "1.1.0"
        product = await create_product(b)
        assert (await b.client.products("Lech"))["matches"][0]["id"] == product["id"]
        assert (await b.client.product(product["id"]))["name"] == "Leche"
        added = await b.client.quick_add("Leche", 2, product["id"])
        row = added["shopping"]["groups"][0]["items"][0]
        row_id = row["id"]
        await b.client.update_shopping(row_id, checked=True, quantity=3)
        await b.client.adjust_shopping(row_id, -1)
        data = await b.client.shopping()
        assert data["checked_count"] == 1
        assert float(data["groups"][0]["items"][0]["quantity"]) == 2
        await b.client.clear_shopping(True)
        assert (await b.client.shopping())["count"] == 0
        await b.client.quick_add("Otro producto")
        row = (await b.client.shopping())["groups"][0]["items"][0]
        await b.client.remove_shopping(row["id"])
        one = await b.client.add_menu("2026-11-16", "lunch", "Sopa y pan")
        two = await b.client.add_menu("2026-11-16", "lunch", "Ensalada")
        assert (await b.client.menu_entry(one["id"]))["text"] == "Sopa y pan"
        await b.client.update_menu(one["id"], one["date"], one["slot"], "Crema")
        assert len((await b.client.menu("2026-11-16"))["entries"]) == 2
        await b.client.remove_menu(one["id"])
        assert (await b.client.menu_entry(two["id"]))["text"] == "Ensalada"
        await b.client.add_menu_batch("2026-11-17", "dinner", ["Tortilla", "Fruta"])
        duplicated = await b.client.duplicate_week("2026-11-16")
        assert duplicated["copied"] == 3
        assert len((await b.client.menu("2026-11-23"))["entries"]) == 3
        assert (await b.client.shopping())["count"] == 0
        assert len(await b.client.products()) == 2


@pytest.mark.anyio
async def test_ambiguity_requires_id_and_does_not_write():
    async with real_backend() as b:
        first = await create_product(b)
        shop = await ui(b, "POST", "supermarkets", {"name": "Segunda tienda"})
        second = await create_product(b, shop_id=shop["id"])
        with pytest.raises(api.ChoiceRequired) as caught:
            await b.client.quick_add("Leche", 2)
        assert {p["id"] for p in caught.value.data["matches"]} == {first["id"], second["id"]}
        assert (await b.client.shopping())["count"] == 0
        result = await actions.execute(b.client, "add_shopping", {"name": "Leche"})
        assert result["status"] == "choose" and result["written"] is False
        await actions.execute(b.client, "add_shopping", {"name": "Leche", "product_id": second["id"]})
        row = (await b.client.shopping())["groups"][0]["items"][0]
        assert row["product_id"] == second["id"]


@pytest.mark.anyio
async def test_real_errors_rotation_disable_and_actions_confirmations():
    async with real_backend() as b:
        with pytest.raises(api.AuthenticationError):
            await api.BridgeClient(b.session, b.url, "x" * 43).health()
        with pytest.raises(api.BridgeError) as missing:
            await b.client.menu_entry(9999)
        assert missing.value.status == 404
        await actions.execute(b.client, "add_shopping", {"name": "Nuevo"})
        with pytest.raises(ValueError, match="confirm"):
            await actions.execute(b.client, "clear_shopping", {"checked_only": False})
        assert (await b.client.shopping())["count"] == 1
        await actions.execute(b.client, "clear_shopping", {"checked_only": False, "confirm": True})
        assert (await b.client.shopping())["count"] == 0
        await ui(b, "POST", "ha/rotate", {})
        with pytest.raises(api.AuthenticationError):
            await b.client.health()
        token = (await ui(b, "POST", "ha/token", {}))["token"]
        await api.BridgeClient(b.session, b.url, token).health()
        await ui(b, "POST", "ha/config", {"enabled": False})
        with pytest.raises(api.BridgeError):
            await api.BridgeClient(b.session, b.url, token).health()


@pytest.mark.anyio
async def test_every_action_against_real_backend():
    async with real_backend() as b:
        async def run(action, **data):
            return await actions.execute(b.client, action, data)
        assert (await run("get_shopping"))["count"] == 0
        result = await run("add_shopping", name="Pan", quantity=2)
        row = result["shopping"]["groups"][0]["items"][0]
        await run("update_shopping", item_id=row["id"], checked=True)
        await run("adjust_shopping", item_id=row["id"], delta=1)
        assert (await run("get_products", name="Pan"))["status"] == "unique"
        await run("remove_shopping", item_id=row["id"], confirm=True)
        one = await run("add_menu", date="2026-11-16", slot="dinner", text="Arroz")
        await run("update_menu", entry_id=one["id"], date="2026-11-16", slot="dinner", text="Arroz integral")
        await run("add_menu_batch", date="2026-11-16", slot="lunch", texts=["Sopa", "Pan"])
        assert len((await run("get_menu", week="2026-11-16"))["entries"]) == 3
        await run("duplicate_week", week="2026-11-16", confirm=True)
        await run("remove_menu", entry_id=one["id"], confirm=True)
        assert len((await run("get_menu", week="2026-11-16"))["entries"]) == 2
        assert len((await run("get_menu", week="2026-11-23"))["entries"]) == 3
        assert isinstance((await run("get_products"))["result"], list)
        for name, data in [("remove_shopping", {"item_id": 1}), ("remove_menu", {"entry_id": 1}),
                           ("duplicate_week", {"week": "2026-11-16"})]:
            with pytest.raises(ValueError, match="confirm"):
                await actions.execute(b.client, name, data)
        with pytest.raises(ValueError):
            await run("arbitrary_http", url="http://example.org")


@pytest.mark.parametrize("url", ["ftp://host", "http://user:password@host", "http://host/api", "http://host?token=secret", "http://host#x", "http://host:invalid", "http://host:0", "http://host\\evil", "http://ho st"])
def test_rejects_unsafe_base_urls(url):
    with pytest.raises(ValueError):
        api.normalize_url(url)


@pytest.mark.parametrize("action,path", [("GET", "backup"), ("POST", "restore"), ("GET", "../api/ha/token"),
    ("POST", "products"), ("PUT", "menu"), ("GET", "health?token=x"), ("DELETE", "menu/0"), ("GET", "menu/1/matches")])
@pytest.mark.anyio
async def test_client_does_not_offer_arbitrary_proxy(action, path):
    async with aiohttp.ClientSession() as session:
        client = api.BridgeClient(session, "http://127.0.0.1:1", "x" * 43)
        with pytest.raises(ValueError, match="permitido"):
            await client._request(action, path)
        with pytest.raises(ValueError, match="32 KiB"):
            await client._request("POST", "menu/batch", body={"texts": ["a" * 33000]})


@pytest.mark.parametrize("value", [True, 0, -1, "1/../../ha/token", 1.5])
def test_identifiers_are_literal_positive_integers(value):
    with pytest.raises(ValueError):
        api.identifier(value)


@pytest.mark.parametrize("value", [True, 0, -1, math.nan, math.inf, 100001])
def test_action_quantity_rejects_invalid(value):
    with pytest.raises(ValueError):
        actions.quantity(value)


def test_settings_allow_explicit_negative_groups_and_disable_by_default():
    key = "x" * 43
    result = settings.normalize_settings({"api_key": key})
    assert result["allowed_chats"] == [] and result["telegram_event_entity"] == ""
    result = settings.normalize_settings({"api_key": key, "telegram_event_entity": "event.bot_update", "allowed_chats": "123,-100987,123"})
    assert result["allowed_chats"] == [-100987, 123]
    assert settings.normalize_settings({"api_key": "", "allowed_chats": ""}, result)["api_key"] == key
    for value in ["0", "12.5", "bad", "1;2", [True]]:
        with pytest.raises(ValueError):
            settings.allowed_chats(value)
    with pytest.raises(ValueError):
        settings.normalize_settings({"api_key": key, "allowed_chats": "123"})


# Fixtures de transporte adversario: NO pretenden ser la API de la aplicación.
@asynccontextmanager
async def wire_fixture(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.anyio
@pytest.mark.parametrize("method,path,body", [("POST", "menu", {"text": "a"}), ("PATCH", "shopping/items/1", {"checked": True}),
                                              ("PUT", "menu/1", {"text": "b"}), ("DELETE", "menu/1", None)])
async def test_response_lost_does_not_retry_any_write(method, path, body):
    received = []
    async def drop(reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        length = next((int(line.split(b":", 1)[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length:")), 0)
        payload = await reader.readexactly(length) if length else b""
        received.append((head, payload))
        writer.close()
        await writer.wait_closed()
    async with wire_fixture(drop) as url, aiohttp.ClientSession() as session:
        client = api.BridgeClient(session, url, "secret-fixture-" + "x" * 43)
        with pytest.raises(api.BridgeError, match="no se ha reintentado") as caught:
            await client._request(method, path, body=body)
        assert "secret-fixture" not in str(caught.value)
        await asyncio.sleep(0.05)
        assert len(received) == 1


@pytest.mark.anyio
async def test_redirect_is_not_followed_and_does_not_leak_bearer():
    target_received, redirect_received = [], []
    async def target(reader, writer):
        target_received.append(await reader.readuntil(b"\r\n\r\n"))
        writer.close()
        await writer.wait_closed()
    async with wire_fixture(target) as target_url:
        async def redirect(reader, writer):
            redirect_received.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(f"HTTP/1.1 307 Temporary Redirect\r\nLocation: {target_url}/stolen\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        async with wire_fixture(redirect) as url, aiohttp.ClientSession() as session:
            with pytest.raises(api.BridgeError, match="redirigido"):
                await api.BridgeClient(session, url, "x" * 43).health()
        assert len(redirect_received) == 1 and target_received == []
        assert b"Authorization: Bearer " in redirect_received[0]
        assert b"?" not in redirect_received[0].split(b"\r\n")[0]
