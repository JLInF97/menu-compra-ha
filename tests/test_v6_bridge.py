"""Seguridad opt-in, persistencia y protocolo real de conexión HA 0.6."""
from concurrent.futures import ThreadPoolExecutor
import json
import os

from fastapi.testclient import TestClient
import pytest

from app.ha_bridge import BridgeState, bridge_target, BODY_LIMIT
from app.main import create_app

CSRF = {"X-Menu-Compra": "1"}
SUPERVISOR = ("172.30.32.2", 1234)
CORE = ("172.30.32.1", 1234)


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, development=False)


def enable(app):
    with TestClient(app, client=SUPERVISOR, headers=CSRF) as ui:
        response = ui.post('/api/ha/config', json={"enabled": True})
        assert response.status_code == 200
        token = ui.post('/api/ha/token', json={}).json()['token']
    return {"Authorization": "Bearer " + token}


def test_default_disabled_and_cannot_be_bypassed_even_in_dev(tmp_path):
    for development in (True, False):
        with TestClient(create_app(tmp_path, development=development), client=SUPERVISOR) as client:
            assert client.get('/api/ha/status').json() == {
                "enabled": False, "has_token": False, "base_url": "http://local-menu-compra:8099", "protocol_version": 1}
            assert client.get('/bridge/v1/health').status_code == 404
            assert client.get('/bridge/v1/health', headers={"Authorization": "Bearer invalid"}).status_code == 404
    assert not (tmp_path / 'ha_bridge.json').exists()


@pytest.mark.parametrize('path', ['/api/ha/status', '/api/ha/config', '/api/ha/token', '/api/ha/rotate', '/api/bootstrap', '/'])
def test_normal_core_requests_cannot_read_or_manage_ui(app, path):
    headers = enable(app)
    with TestClient(app, client=CORE, headers=headers | CSRF) as core:
        method = 'GET' if path in ['/api/ha/status', '/api/bootstrap', '/'] else 'POST'
        assert core.request(method, path, json={"enabled": True}).status_code == 403


@pytest.mark.parametrize('path', ['/api/ha/config', '/api/ha/token', '/api/ha/rotate'])
def test_ingress_security_and_csrf_are_preserved(app, path):
    with TestClient(app, client=SUPERVISOR) as ui:
        assert ui.post(path, json={"enabled": True}).status_code == 403


@pytest.mark.parametrize('value', [None, 1, 0, 'true', '', [], {}])
def test_configuration_requires_strict_boolean(app, value):
    with TestClient(app, client=SUPERVISOR, headers=CSRF) as ui:
        assert ui.post('/api/ha/config', json={"enabled": value}).status_code == 422
        assert ui.get('/api/ha/status').json()['enabled'] is False


def test_unknown_configuration_fields_rejected(app):
    with TestClient(app, client=SUPERVISOR, headers=CSRF) as ui:
        assert ui.post('/api/ha/config', json={"enabled": True, "token": "manual"}).status_code == 422
        assert ui.post('/api/ha/token', json={}).status_code == 409
        assert ui.post('/api/ha/rotate', json={}).status_code == 409


@pytest.mark.parametrize('authorization', ['', 'Bearer invalid', 'Basic invalid', 'bearer ', 'Token invalid'])
def test_bridge_requires_own_bearer_from_all_peers(app, authorization):
    enable(app)
    for peer in (CORE, SUPERVISOR, ("127.0.0.1", 1234), ("192.0.2.1", 1234)):
        with TestClient(app, client=peer) as core:
            response = core.get('/bridge/v1/health', headers={"Authorization": authorization, **CSRF})
            assert response.status_code == 401
            assert response.headers['www-authenticate'] == 'Bearer'


def test_persist_rotate_disable_reenable_restart_no_token_in_exports(app, tmp_path):
    auth = enable(app)
    with TestClient(app, client=CORE, headers=auth) as core:
        assert core.get('/bridge/v1/health').json() == {"status": "ok", "version": "1.0.0"}
    original_token = auth['Authorization'].split(' ', 1)[1]
    with TestClient(app, client=SUPERVISOR, headers=CSRF) as ui:
        assert original_token not in ui.get('/api/ha/status').text
        assert original_token not in ui.get('/api/bootstrap').text
        assert original_token not in ui.get('/api/backup').text
        backup = ui.get('/api/backup').json()
        assert ui.post('/api/restore', json=backup).status_code == 200
        assert ui.post('/api/ha/token', json={}).json()['token'] == original_token
    restarted = create_app(tmp_path, development=False)
    with TestClient(restarted, client=CORE, headers=auth) as core:
        assert core.get('/bridge/v1/health').status_code == 200
    with TestClient(restarted, client=SUPERVISOR, headers=CSRF) as ui:
        rotated = ui.post('/api/ha/rotate', json={}).json()['token']
        assert rotated != original_token
    with TestClient(restarted, client=CORE, headers=auth) as core:
        assert core.get('/bridge/v1/health').status_code == 401
        new_auth = {"Authorization": 'Bearer ' + rotated}
        assert core.get('/bridge/v1/health', headers=new_auth).status_code == 200
    with TestClient(restarted, client=SUPERVISOR, headers=CSRF) as ui:
        assert ui.post('/api/ha/config', json={"enabled": False}).json()['enabled'] is False
    with TestClient(restarted, client=CORE, headers=new_auth) as core:
        assert core.get('/bridge/v1/health').status_code == 404
    with TestClient(restarted, client=SUPERVISOR, headers=CSRF) as ui:
        assert ui.post('/api/ha/config', json={"enabled": True}).status_code == 200
        assert ui.post('/api/ha/token', json={}).json()['token'] == rotated
    state = json.loads((tmp_path / 'ha_bridge.json').read_text())
    assert state == {"version": 1, "enabled": True, "token": rotated}


@pytest.mark.parametrize('method,path', [
    ('GET', 'backup'), ('POST', 'restore'), ('GET', 'ha/status'), ('POST', 'ha/token'), ('POST', 'ha/rotate'),
    ('POST', 'ha/config'), ('GET', '../api/ha/token'), ('GET', 'static/app.js'), ('GET', ''), ('GET', 'health/'),
    ('PUT', 'products/1'), ('DELETE', 'products/1'), ('POST', 'products'), ('POST', 'categories'),
    ('DELETE', 'categories/1'), ('GET', 'dishes'), ('GET', 'menu/duplicate-week'), ('GET', 'api/backup'),
    ('POST', 'shopping/items'), ('PUT', 'menu'), ('PATCH', 'menu/1'), ('HEAD', 'health'), ('OPTIONS', 'shopping'),
])
def test_route_and_method_allowlist(app, method, path):
    auth = enable(app)
    with TestClient(app, client=CORE, headers=auth) as core:
        response = core.request(method, '/bridge/v1/' + path, json={})
        assert response.status_code in (403, 404), response.text


@pytest.mark.parametrize('path', ['ha/token', 'ha/config', 'backup', 'restore', 'products/1', 'dishes'])
def test_pure_allowlist_never_accepts_unsafe_route_combinations(path):
    assert bridge_target('/bridge/v1/' + path, 'POST') is None


def test_machine_and_ui_share_transactions_without_csrf_header(app):
    auth = enable(app)
    with TestClient(app, client=CORE, headers=auth) as core, TestClient(app, client=SUPERVISOR, headers=CSRF) as ui:
        result = core.post('/bridge/v1/shopping/quick-add', json={"name": "Leche del bot", "quantity": 2})
        assert result.status_code == 201, result.text
        product = result.json()['product']
        assert ui.get('/api/bootstrap').json()['uncategorized_count'] == 1
        line = ui.get('/api/shopping').json()['groups'][0]['items'][0]
        assert line['product_id'] == product['id'] and line['quantity'] == 2
        patched = core.patch(f"/bridge/v1/shopping/items/{line['id']}", json={"checked": True, "quantity": 3.5})
        assert patched.status_code == 200
        assert ui.get('/api/shopping').json()['checked_count'] == 1
        assert core.post(f"/bridge/v1/shopping/items/{line['id']}/adjust", json={"delta": 1}).status_code == 200
        assert ui.get('/api/shopping').json()['groups'][0]['items'][0]['quantity'] == 4.5
        p1 = core.post('/bridge/v1/menu', json={"date": "2026-11-16", "slot": "lunch", "text": "Tortilla"}).json()
        p2 = core.post('/bridge/v1/menu', json={"date": "2026-11-16", "slot": "lunch", "text": "Ensalada"}).json()
        assert core.get(f"/bridge/v1/menu/{p1['id']}").json()['text'] == 'Tortilla'
        assert core.put(f"/bridge/v1/menu/{p1['id']}", json={"date": "2026-11-16", "slot": "dinner", "text": "Arroz"}).status_code == 200
        entries = ui.get('/api/menu?week=2026-11-16').json()['entries']
        assert len(entries) == 2 and next(e for e in entries if e['id'] == p2['id'])['text'] == 'Ensalada'
        assert core.delete(f"/bridge/v1/menu/{p1['id']}").status_code == 200
        assert core.get(f"/bridge/v1/menu/{p1['id']}").status_code == 404
        assert len(ui.get('/api/menu?week=2026-11-16').json()['entries']) == 1
        assert core.delete('/bridge/v1/shopping').json()['count'] == 0
        assert ui.get(f"/api/products/{product['id']}").status_code == 200
        assert len(ui.get('/api/menu?week=2026-11-16').json()['entries']) == 1


def test_ambiguity_is_conflict_without_partial_purchase(app):
    auth = enable(app)
    with TestClient(app, client=CORE, headers=auth) as core, TestClient(app, client=SUPERVISOR, headers=CSRF) as ui:
        first = core.post('/bridge/v1/shopping/quick-add', json={"name": "Leche"}).json()['product']
        shop = ui.post('/api/supermarkets', json={"name": "Otra tienda"}).json()
        assert ui.post('/api/products', json={"name": "Leche", "category_id": first['category_id'], "supermarket_id": shop['id'], "price_cents": 120, "unit": "ud"}).status_code == 201
        before = ui.get('/api/backup').json()['tables']
        response = core.post('/bridge/v1/shopping/quick-add', json={"name": "Leche"})
        assert response.status_code == 409 and response.json()['status'] == 'choose'
        assert ui.get('/api/backup').json()['tables'] == before


def test_bridge_body_limits_and_bad_json(app):
    auth = enable(app)
    with TestClient(app, client=CORE, headers=auth) as core:
        assert core.post('/bridge/v1/shopping/quick-add', content=b'x' * (BODY_LIMIT + 1)).status_code == 413
        response = core.post('/bridge/v1/shopping/quick-add', content=iter([b'x' * BODY_LIMIT, b'x']))
        assert response.status_code == 413
        assert core.post('/bridge/v1/shopping/quick-add', content=b'{bad', headers={'Content-Type': 'application/json'}).status_code == 422
        assert core.post('/bridge/v1/shopping/quick-add', json={"name": ""}).status_code == 422


@pytest.mark.parametrize('contents', ['{bad', '{}', 'null', '[]', '{"version":2,"enabled":true,"token":"x"}', '{"version":1,"enabled":"false","token":""}', 'x' * 9000])
def test_corrupt_private_config_fails_closed_but_does_not_break_ui(tmp_path, contents):
    (tmp_path / 'ha_bridge.json').write_text(contents)
    with TestClient(create_app(tmp_path, development=True), headers=CSRF) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/ha/status').json()['enabled'] is False
        assert client.get('/bridge/v1/health').status_code == 404
    assert (tmp_path / 'ha_bridge.json').read_text() == contents


def test_atomic_save_failure_keeps_old_key_and_cleans_temporary(tmp_path, monkeypatch):
    state = BridgeState(tmp_path)
    state.configure(True)
    token = state.reveal()['token']
    old = state.path.read_bytes()
    def fail(*args):
        raise OSError('simulated disk error')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        state.rotate()
    assert state.path.read_bytes() == old and state.reveal()['token'] == token
    assert not list(tmp_path.glob('.ha-bridge-*'))


def test_concurrent_rotations_persist_one_complete_key(tmp_path):
    state = BridgeState(tmp_path)
    state.configure(True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        tokens = list(pool.map(lambda _: state.rotate()['token'], range(10)))
    stored = json.loads(state.path.read_text())['token']
    assert stored in tokens and len(set(tokens)) == 10
    assert state.authorized('Bearer ' + stored)
    assert sum(state.authorized('Bearer ' + token) for token in tokens) == 1
    assert not state.authorized('Bearer no-ascii-\u00f1')
