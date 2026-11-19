"""TCP real en modo producción: no HA, ni respuestas de API simuladas."""
import json
from threading import Thread
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import uvicorn

from app.main import create_app


@pytest.fixture
def tcp_bridge(tmp_path):
    application = create_app(tmp_path, development=False)
    application.state.ha_bridge.configure(True)
    token = application.state.ha_bridge.reveal()['token']
    server = uvicorn.Server(uvicorn.Config(application, host='127.0.0.1', port=0, log_level='warning', access_log=False, proxy_headers=False))
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    try:
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        yield application, f'http://127.0.0.1:{port}', token
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=10)
        assert not thread.is_alive(), 'El servidor TCP de pruebas no se ha detenido'


def http(base, path, token=None, method='GET', data=None, headers=None):
    combined = dict(headers or {})
    if token:
        combined['Authorization'] = 'Bearer ' + token
    body = None
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        combined['Content-Type'] = 'application/json'
    req = Request(base + path, data=body, headers=combined, method=method)
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


@pytest.mark.parametrize('_repeat', range(5))
def test_tcp_authentication_writes_and_ui_isolation(tcp_bridge, _repeat):
    app, base, token = tcp_bridge
    assert http(base, '/api/health')[0] == 200
    assert http(base, '/api/shopping', token)[0] == 403
    assert http(base, '/api/ha/status', token)[0] == 403
    # This secret endpoint has no request body; probe the real protocol as defined.
    assert http(base, '/api/ha/token', token, method='POST')[0] == 403
    assert http(base, '/api/shopping', headers={'X-Forwarded-For': '172.30.32.2', 'X-Menu-Compra': '1'})[0] == 403
    assert http(base, '/bridge/v1/health')[0] == 401
    assert http(base, '/bridge/v1/health', token)[0] == 200
    status, result = http(base, '/bridge/v1/shopping/quick-add', token, 'POST', {'name': 'Leche TCP', 'quantity': 2})
    assert status == 201
    product_id = result['product']['id']
    status, shopping = http(base, '/bridge/v1/shopping', token)
    assert status == 200 and shopping['count'] == 1
    assert shopping['groups'][0]['items'][0]['quantity'] == 2
    assert http(base, '/bridge/v1/restore', token, 'POST', {})[0] == 404
    assert http(base, '/bridge/v1/backup', token)[0] == 404
    assert http(base, f'/bridge/v1/products/{product_id}', token, 'DELETE')[0] == 404
    assert http(base, '/bridge/v1/health?token=' + token)[0] == 401
    new_token = app.state.ha_bridge.rotate()['token']
    assert http(base, '/bridge/v1/health', token)[0] == 401
    assert http(base, '/bridge/v1/health', new_token)[0] == 200
    app.state.ha_bridge.configure(False)
    assert http(base, '/bridge/v1/health', new_token)[0] == 404
