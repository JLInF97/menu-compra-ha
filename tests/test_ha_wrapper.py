"""Wrapper HA con fixtures explícitas; no instala ni suplanta Home Assistant."""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_ha_support import pure_module


@pytest.mark.parametrize('ack_fails', [False, True])
def test_callback_ack_has_explicit_bot_and_never_repeats_a_write(ack_fails):
    tg = pure_module('telegram')
    path = Path(__file__).resolve().parents[1] / 'custom_components/menu_compra/services.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'telegram_update')
    class HAFixtureError(Exception):
        pass
    now = datetime.now(timezone.utc)
    event_timestamp = now.isoformat()
    data = {'event_type': 'telegram_callback', 'id': 'callback-fixture', 'chat_id': 77, 'user_id': 77,
            'data': 'mc:fixture', 'bot': {'config_entry_id': 'bot-fixture', 'username': 'bot'}}
    calls, writes = [], []
    async def handle(update):
        writes.append(update)
        return True
    async def async_call(domain, service, payload, **kwargs):
        calls.append((domain, service, payload, kwargs))
        if ack_fails:
            raise HAFixtureError('fixture: expired acknowledgement')
    state = SimpleNamespace(state=event_timestamp, attributes=data)
    bot = SimpleNamespace(domain='telegram_bot', entry_id='bot-fixture')
    registry = SimpleNamespace(async_get=lambda entity: SimpleNamespace(config_entry_id='bot-fixture', platform='telegram_bot'))
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity: state),
                           config_entries=SimpleNamespace(async_get_entry=lambda key: bot),
                           services=SimpleNamespace(async_call=async_call))
    namespace = {'datetime': datetime, 'timezone': timezone, 'event_payload': tg.event_payload,
                 'Update': tg.Update, 'er': SimpleNamespace(async_get=lambda h: registry),
                 'HomeAssistantError': HAFixtureError, 'ServiceValidationError': HAFixtureError,
                 '_LOGGER': logging.getLogger('test-ha-callback-fixture')}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<actual-wrapper-with-ha-fixtures>', 'exec'), namespace)
    runtime = SimpleNamespace(router=SimpleNamespace(event_entity='event.fixture', handle=handle))
    result = asyncio.run(namespace['telegram_update'](hass, runtime, {
        'event_entity': 'event.fixture', 'event_timestamp': event_timestamp,
        'previous_timestamp': (now - timedelta(seconds=1)).isoformat(), 'event_data': tg.event_payload(data)}))
    assert result == {'handled': True}
    assert len(writes) == 1
    assert calls == [('telegram_bot', 'answer_callback_query',
                      {'config_entry_id': 'bot-fixture', 'callback_query_id': 'callback-fixture'}, {'blocking': True})]
