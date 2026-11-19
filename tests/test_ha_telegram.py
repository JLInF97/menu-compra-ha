"""Router puro con cliente real y sink Telegram explícitamente FIXTURE.

No contacta Telegram ni simula Home Assistant. Todas las compras/platos y las
restauraciones usan FastAPI/SQLite reales a través del cliente aiohttp.
"""
import asyncio
from datetime import date

import pytest
from test_ha_support import create_product, pure_module, real_backend, ui
from test_ha_support import anyio_backend as anyio_backend

tg = pure_module("telegram")


class TelegramSinkFixture:
    """Captura payloads del servicio; NO equivale a entrega en Telegram real."""
    def __init__(self):
        self.messages = []
        self.fail_next = False

    async def __call__(self, update, payload):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Fixture: entrega Telegram perdida")
        self.messages.append(payload)

    def button(self, contains, *, message=None):
        payload = self.messages[-1] if message is None else message
        return next(data for row in payload.get("inline_keyboard", []) for label, data in row if contains in label)


class Driver:
    def __init__(self, client, clock=None):
        self.sink = TelegramSinkFixture()
        kwargs = {"clock": clock} if clock else {}
        self.router = tg.TelegramRouter(client, "event.mi_bot", {-100987, 123}, self.sink,
                                       today=lambda: date(2026, 11, 16), **kwargs)
        self.sequence = 0

    def update(self, command=None, args=(), callback=None, chat=-100987, actor=77, entity="event.mi_bot", thread=45, msgid=None):
        self.sequence += 1
        attrs = {"chat_id": chat, "user_id": actor, "id": msgid if msgid is not None else self.sequence,
                 "bot": {"username": "mi_bot", "config_entry_id": "telegram-entry-2"}}
        if callback is None:
            kind = "telegram_command"
            attrs.update(command=command, args=list(args), message_thread_id=thread)
        else:
            kind = "telegram_callback"
            attrs.update(data=callback, message={"message_thread_id": thread})
        return tg.Update(entity, f"timestamp-{self.sequence}", kind, attrs, "telegram-entry-2")

    async def command(self, command, *args, **kwargs):
        return await self.router.handle(self.update(command, args, **kwargs))

    async def click(self, nonce, **kwargs):
        return await self.router.handle(self.update(callback=nonce, **kwargs))


def rows(data):
    return tg.shopping_rows(data)


@pytest.mark.anyio
async def test_allowlist_entity_other_commands_other_bots_and_external_callbacks():
    async with real_backend() as b:
        d = Driver(b.client)
        for update in [d.update("/otro"), d.update("/comprar", ["Pan"], chat=999),
                       d.update("/comprar", ["Pan"], entity="event.otro"), d.update("/comprar@otro_bot", ["Pan"]),
                       d.update(callback="another:nonce"), d.update("/comprar", ["Pan"], actor=None)]:
            assert await d.router.handle(update) is False
        assert d.sink.messages == [] and (await b.client.shopping())["count"] == 0
        assert await d.command("/comprar@mi_bot", "Pan") is True
        assert (await b.client.shopping())["count"] == 1
        payload = d.sink.messages[-1]
        assert payload["config_entry_id"] == "telegram-entry-2"
        assert payload["chat_id"] == -100987 and payload["message_thread_id"] == 45
        assert payload["parse_mode"] == "plain_text"


@pytest.mark.anyio
async def test_repeated_update_concurrent_does_not_duplicate_shopping_or_menu():
    async with real_backend() as b:
        d = Driver(b.client)
        update = d.update("/comprar", ["2", "Pan"], msgid=500)
        await asyncio.gather(*(d.router.handle(update) for _ in range(12)))
        await d.router.handle(d.update("/comprar", ["2", "Pan"], msgid=500))
        assert float(rows(await b.client.shopping())[0]["quantity"]) == 2
        update = d.update("/plato", ["hoy", "comida", "Sopa", "y", "pan"], msgid=501)
        await asyncio.gather(*(d.router.handle(update) for _ in range(10)))
        entries = (await b.client.menu("2026-11-16"))["entries"]
        assert len(entries) == 1 and entries[0]["text"] == "Sopa y pan"


@pytest.mark.anyio
async def test_check_is_explicit_set_adjust_single_use_and_minimum_does_not_delete():
    async with real_backend() as b:
        await b.client.quick_add("Pan")
        d = Driver(b.client)
        await d.command("/compra")
        check, plus, minus = (d.sink.button(label) for label in ("Marcar", "+1", "−1"))
        row_id = rows(await b.client.shopping())[0]["id"]
        # Cambio concurrente: el botón antiguo Marcar NO debe hacer toggle.
        await b.client.update_shopping(row_id, checked=True)
        await d.click(check)
        assert rows(await b.client.shopping())[0]["checked"] is True
        await d.click(plus)
        await d.click(plus)
        assert float(rows(await b.client.shopping())[0]["quantity"]) == 2
        assert "caducado" in d.sink.messages[-1]["message"]
        await d.click(minus)
        assert float(rows(await b.client.shopping())[0]["quantity"]) == 1
        await d.command("/compra")
        await d.click(d.sink.button("−1"))
        assert (await b.client.shopping())["count"] == 1
        assert "No se ha podido" in d.sink.messages[-1]["message"]


@pytest.mark.anyio
async def test_remove_confirm_bound_to_actor_chat_and_thread_and_one_shot():
    async with real_backend() as b:
        await b.client.quick_add("Pan")
        d = Driver(b.client)
        await d.command("/compra")
        await d.click(d.sink.button("Quitar"))
        confirm = d.sink.button("confirmar")
        assert (await b.client.shopping())["count"] == 1
        for kwargs in ({"actor": 88}, {"chat": 123}, {"thread": 46}):
            await d.click(confirm, **kwargs)
            assert (await b.client.shopping())["count"] == 1
        await d.click(confirm)
        assert (await b.client.shopping())["count"] == 0
        await b.client.quick_add("Pan")
        await d.click(confirm)
        assert (await b.client.shopping())["count"] == 1
        assert "caducado" in d.sink.messages[-1]["message"]


@pytest.mark.anyio
async def test_ambiguity_has_shop_buttons_by_id_and_no_arbitrary_selection():
    async with real_backend() as b:
        await create_product(b)
        shop = await ui(b, "POST", "supermarkets", {"name": "Tienda elegida"})
        second = await create_product(b, shop_id=shop["id"])
        d = Driver(b.client)
        await d.command("/comprar", "2,5", "Leche")
        assert (await b.client.shopping())["count"] == 0
        choice = d.sink.button("Tienda elegida")
        assert choice.startswith("mc:") and len(choice.encode()) <= 64
        await d.click("mc:choose:12345")
        assert (await b.client.shopping())["count"] == 0
        await d.click(choice)
        row = rows(await b.client.shopping())[0]
        assert row["product_id"] == second["id"] and float(row["quantity"]) == 2.5
        await d.click(choice)
        assert float(rows(await b.client.shopping())[0]["quantity"]) == 2.5


@pytest.mark.anyio
async def test_menu_add_navigation_edit_confirmation_delete_one_entry():
    async with real_backend() as b:
        d = Driver(b.client)
        await d.command("/plato", "hoy", "comida", "Sopa")
        await d.command("/plato", "hoy", "comida", "Ensalada")
        await d.command("/menu", "semana")
        assert "Sopa" in d.sink.messages[-1]["message"] and "Ensalada" in d.sink.messages[-1]["message"]
        entries = (await b.client.menu("2026-11-16"))["entries"]
        first, second = entries
        await d.click(d.sink.button('Gestionar platos'))
        await d.click(d.sink.button(f"Editar #{first['id']}"))
        assert "/editarplato" in d.sink.messages[-1]["message"]
        await d.command("/editarplato", str(first["id"]), "Crema", "de", "verduras")
        assert (await b.client.menu_entry(first["id"]))["text"] == "Sopa"
        await d.click(d.sink.button("confirmar"))
        assert (await b.client.menu_entry(first["id"]))["text"] == "Crema de verduras"
        assert (await b.client.menu_entry(second["id"]))["text"] == "Ensalada"
        await d.command("/menu", "hoy")
        await d.click(d.sink.button("Semana siguiente"))
        assert "23/11/26" in d.sink.messages[-1]["message"]
        await d.click(d.sink.button("Añadir plato"))
        assert "/plato 23/11/26 comida" in d.sink.messages[-1]["message"]
        await d.command("/quitarplato", str(first["id"]))
        assert len((await b.client.menu("2026-11-16"))["entries"]) == 2
        await d.click(d.sink.button("confirmar"))
        assert [r["id"] for r in (await b.client.menu("2026-11-16"))["entries"]] == [second["id"]]
        await d.command("/menu", "9999-12-31")
        assert "31/12/99" in d.sink.messages[-1]["message"]
        assert not any("Semana siguiente" in label for row in d.sink.messages[-1]["inline_keyboard"] for label, _ in row)
        await d.command("/menu", "2026-02-30")
        assert "Fecha no válida" in d.sink.messages[-1]["message"]


@pytest.mark.anyio
async def test_old_row_and_menu_buttons_after_real_json_restore_reject_reused_ids():
    async with real_backend() as b:
        await b.client.quick_add("Pan")
        other = await create_product(b, "Fruta")
        entry = await b.client.add_menu("2026-11-16", "lunch", "Sopa")
        d = Driver(b.client)
        await d.command("/compra")
        mark = d.sink.button("Marcar")
        await d.command("/menu", "hoy")
        await d.click(d.sink.button('Gestionar platos'))
        remove = d.sink.button(f"Quitar #{entry['id']}")
        backup = await ui(b, "GET", "backup")
        backup["tables"]["shopping_items"][0]["product_id"] = other["id"]
        backup["tables"]["menu_entries"][0]["text"] = "Otro plato restaurado"
        await ui(b, "POST", "restore", backup)
        await d.click(mark)
        assert "ya no es la misma" in d.sink.messages[-1]["message"]
        assert rows(await b.client.shopping())[0]["checked"] is False
        await d.click(remove)
        assert "ha cambiado" in d.sink.messages[-1]["message"]
        assert (await b.client.menu_entry(entry["id"]))["text"] == "Otro plato restaurado"


@pytest.mark.anyio
async def test_confirmation_revalidates_menu_and_shopping_changes():
    async with real_backend() as b:
        entry = await b.client.add_menu("2026-11-16", "lunch", "Sopa")
        d = Driver(b.client)
        await d.command("/editarplato", str(entry["id"]), "Crema")
        confirm = d.sink.button("confirmar")
        await b.client.update_menu(entry["id"], entry["date"], entry["slot"], "Cambio externo")
        await d.click(confirm)
        assert "ha cambiado" in d.sink.messages[-1]["message"]
        assert (await b.client.menu_entry(entry["id"]))["text"] == "Cambio externo"
        await b.client.quick_add("Pan")
        await d.command("/compra")
        await d.click(d.sink.button("Vaciar compra"))
        confirm = d.sink.button("confirmar")
        await b.client.quick_add("Leche")
        await d.click(confirm)
        assert "ha cambiado" in d.sink.messages[-1]["message"]
        assert (await b.client.shopping())["count"] == 2
        await d.command("/compra")
        await d.click(d.sink.button("Vaciar compra"))
        await d.click(d.sink.button("Cancelar"))
        assert (await b.client.shopping())["count"] == 2


@pytest.mark.anyio
async def test_clean_checked_and_clear_all_preserve_catalogue_and_menu():
    async with real_backend() as b:
        await b.client.quick_add("Pan")
        await b.client.quick_add("Leche")
        row = rows(await b.client.shopping())[0]
        await b.client.update_shopping(row["id"], checked=True)
        await b.client.add_menu("2026-11-16", "lunch", "Sopa")
        d = Driver(b.client)
        await d.command("/compra")
        await d.click(d.sink.button("Limpiar comprados"))
        assert (await b.client.shopping())["count"] == 2
        await d.click(d.sink.button("confirmar"))
        assert (await b.client.shopping())["count"] == 1
        await d.click(d.sink.button("Vaciar compra"))
        await d.click(d.sink.button("confirmar"))
        assert (await b.client.shopping())["count"] == 0
        assert len(await b.client.products()) == 2
        assert len((await b.client.menu("2026-11-16"))["entries"]) == 1


@pytest.mark.anyio
async def test_ttl_bounded_cache_pagination_and_send_failure_no_replay():
    async with real_backend() as b:
        clock = [10.0]
        d = Driver(b.client, clock=lambda: clock[0])
        d.router.MAX_TICKETS = 32
        d.router.MAX_UPDATES = 8
        for n in range(8):
            await b.client.quick_add(f"Producto {n}")
        await d.command("/compra")
        button = d.sink.button("Marcar")
        assert len(d.sink.messages[-1]["inline_keyboard"]) <= 8
        await d.click(d.sink.button("▶"))
        assert "página 2" in d.sink.messages[-1]["message"]
        clock[0] += 601
        await d.click(button)
        assert "caducado" in d.sink.messages[-1]["message"]
        assert (await b.client.shopping())["checked_count"] == 0
        for _ in range(10):
            await d.command("/menuc")
        assert len(d.router._tickets) <= 32 and len(d.router._seen) <= 8
        d.sink.fail_next = True
        update = d.update("/comprar", ["Especial"], msgid=999)
        with pytest.raises(RuntimeError, match="entrega Telegram perdida"):
            await d.router.handle(update)
        assert await d.router.handle(update) is True
        assert float(next(r for r in rows(await b.client.shopping()) if r["product_name"] == "Especial")["quantity"]) == 1
        clock[0] += 3601
        await d.command("/menuc")
        assert len(d.router._seen) == 1


@pytest.mark.parametrize("args", [[], ["0", "Pan"], ["-1", "Pan"], ["1.0001", "Pan"], ["100001", "Pan"], ["2"], ["x" * 181]])
def test_invalid_buy_args(args):
    with pytest.raises(ValueError):
        tg.parse_buy(list(args))


def test_plain_text_and_utf16_chunks_do_not_interpret_markup():
    text = "<b>Pan & café</b> _no markdown_ 😀" * 1000 + "\u202eengaño\x00"
    chunks = tg.split_message(text)
    assert len(chunks) > 1
    assert all(len(c.encode("utf-16-le")) // 2 <= 4096 for c in chunks)
    assert "".join(chunks) == tg.plain(text)
    assert "<b>Pan & café</b>" in chunks[0] and "\u202e" not in "".join(chunks)
    assert tg.parse_day("mañana", date(2026, 11, 16)).isoformat() == "2026-11-17"
    with pytest.raises(ValueError):
        tg.parse_day("20261116", date(2026, 11, 16))
