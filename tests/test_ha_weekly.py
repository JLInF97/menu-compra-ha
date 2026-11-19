"""Formato semanal Telegram 0.6.1 contra backend real; solo entrega TG fixture."""
from datetime import date, timedelta
from pathlib import Path
import re

import pytest

from test_ha_support import real_backend, ui
from test_ha_support import anyio_backend as anyio_backend
from test_ha_telegram import Driver, tg


@pytest.mark.anyio
async def test_default_week_has_seven_days_meals_dates_order_and_no_writes():
    async with real_backend() as b:
        d = Driver(b.client)
        d.router.today = lambda: date(2026, 11, 18)
        for day, slot, text in [('2026-11-16', 'lunch', 'Sopa'), ('2026-11-16', 'lunch', 'Ensalada'),
                                ('2026-11-16', 'dinner', 'Tortilla'), ('2026-11-22', 'dinner', 'Pescado')]:
            await b.client.add_menu(day, slot, text)
        before = (await ui(b, 'GET', 'backup'))['tables']
        await d.command('/menu')
        message = d.sink.messages[-1]['message']
        assert message.startswith('Semana del 16/11/26 al 22/11/26\n\nLunes · 16/11/26\n-----\n')
        assert 'Comida:\n  • Sopa\n  • Ensalada\nCena: Tortilla' in message
        assert 'Domingo · 22/11/26\n-------\nComida: Sin planificar\nCena: Pescado' in message
        positions = [message.index(f'{name} · {tg.display_date(date(2026,11,16) + timedelta(days=n))}') for n, name in enumerate(tg.WEEKDAYS)]
        assert positions == sorted(positions)
        assert message.count('Comida:') == message.count('Cena:') == 7
        assert not re.search(r'\b\d{4}-\d{2}-\d{2}\b', message)
        assert '#' not in message and 'página' not in message
        assert (await ui(b, 'GET', 'backup'))['tables'] == before
        await d.command('/menuc')
        await d.click(d.sink.button('Menú semanal'))
        assert d.sink.messages[-1]['message'] == message


@pytest.mark.anyio
async def test_empty_week_includes_all_days_and_both_meals():
    async with real_backend() as b:
        d = Driver(b.client)
        await d.command('/menu')
        text = d.sink.messages[-1]['message']
        assert text.count('Sin planificar') == 14
        assert all(f'{name} · ' in text for name in tg.WEEKDAYS)
        assert (await b.client.menu('2026-11-16'))['entries'] == []


@pytest.mark.anyio
async def test_navigation_is_weekly_across_year_and_current_resolves_at_click_time():
    async with real_backend() as b:
        d = Driver(b.client)
        today = [date(2026,12,30)]
        d.router.today = lambda: today[0]
        await d.command('/menu')
        assert 'Semana del 28/12/26 al 03/01/27' in d.sink.messages[-1]['message']
        await d.click(d.sink.button('Semana siguiente'))
        assert 'Semana del 04/01/27 al 10/01/27' in d.sink.messages[-1]['message']
        current = d.sink.button('Semana actual')
        await d.click(d.sink.button('Semana anterior'))
        assert 'Semana del 28/12/26 al 03/01/27' in d.sink.messages[-1]['message']
        today[0] = date(2027,1,11)
        await d.click(current)
        assert 'Semana del 11/01/27 al 17/01/27' in d.sink.messages[-1]['message']


@pytest.mark.anyio
@pytest.mark.parametrize('today', [date(2026,11,22), date(2026,11,18)])
async def test_default_uses_current_week_even_on_sunday(today):
    async with real_backend() as b:
        d = Driver(b.client)
        d.router.today = lambda: today
        await d.command('/menu')
        assert 'Semana del 16/11/26 al 22/11/26' in d.sink.messages[-1]['message']


@pytest.mark.parametrize('text,expected', [('16/11/26','2026-11-16'), ('01/01/69','2069-01-01'),
                                          ('31/12/99','2099-12-31'), ('29/02/28','2028-02-29'),
                                          ('2026-11-16','2026-11-16')])
def test_spanish_dates_without_strptime_century_pivot(text, expected):
    assert tg.parse_day(text, date(2026,11,16)).isoformat() == expected


@pytest.mark.parametrize('text', ['31/02/26','29/02/26','1/1/26','16/11/2026','16-11-26'])
def test_reject_bad_dates_without_repairing_them(text):
    with pytest.raises(ValueError):
        tg.parse_day(text, date(2026,11,16))


@pytest.mark.anyio
async def test_spanish_commands_select_a_whole_week_and_keep_meal_actions():
    async with real_backend() as b:
        d = Driver(b.client)
        await d.command('/plato', '18/11/26', 'comida', 'Lentejas')
        await d.command('/menu', '19/11/26')
        assert 'Miércoles · 18/11/26\n---------\nComida: Lentejas' in d.sink.messages[-1]['message']
        await d.click(d.sink.button('Gestionar platos'))
        assert '18/11/26 · comida: Lentejas' in d.sink.messages[-1]['message']
        assert '2026-11-18' not in d.sink.messages[-1]['message']
        await d.click(d.sink.button('Quitar #'))
        assert '18/11/26' in d.sink.messages[-1]['message']
        await d.click(d.sink.button('Cancelar'))
        assert len((await b.client.menu('2026-11-16'))['entries']) == 1


@pytest.mark.anyio
async def test_long_week_does_not_drop_entries_and_tools_stay_in_same_week(tmp_path):
    async with real_backend() as b:
        d = Driver(b.client)
        texts = []
        for n in range(7):
            day = (date(2026,11,16) + timedelta(days=n)).isoformat()
            for slot in ['lunch','dinner']:
                text = f'PLATO-{n}-{slot} ' + 'café y ensalada 😀 ' * 24
                saved = await b.client.add_menu(day, slot, text)
                texts.append(saved['text'])
        await b.client.add_menu('2026-11-23','lunch','SOLO OTRA SEMANA')
        before = len(d.sink.messages)
        await d.command('/menu')
        messages = d.sink.messages[before:]
        joined = ''.join(m['message'] for m in messages)
        assert len(messages) > 1
        assert all(len(m['message'].encode('utf-16-le')) // 2 <= 4096 for m in messages)
        assert all(text in joined for text in texts)
        assert 'SOLO OTRA SEMANA' not in joined
        await d.click(d.sink.button('Gestionar platos'))
        assert 'página 1' in d.sink.messages[-1]['message']
        await d.click(d.sink.button('Más platos'))
        assert 'página 2' in d.sink.messages[-1]['message']
        assert 'SOLO OTRA SEMANA' not in d.sink.messages[-1]['message']
        await d.click(d.sink.button('Volver al menú semanal'))
        assert 'Semana del 16/11/26 al 22/11/26' in ''.join(m['message'] for m in d.sink.messages[-len(messages):])


@pytest.mark.anyio
async def test_save_preview_from_real_backend():
    async with real_backend() as b:
        d = Driver(b.client)
        await b.client.add_menu('2026-11-16','lunch','Lentejas con verduras')
        await b.client.add_menu('2026-11-16','dinner','Tortilla de patatas')
        await b.client.add_menu('2026-11-17','lunch','Arroz con pollo')
        await d.command('/menu')
        preview = Path(__file__).resolve().parents[1] / 'evidencias' / '1.0.0' / 'menu-semanal-ejemplo.txt'
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_text(d.sink.messages[-1]['message'] + '\n', encoding='utf-8')
