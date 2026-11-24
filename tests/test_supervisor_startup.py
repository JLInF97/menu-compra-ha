"""El anuncio de producción debe esperar al listener HTTP local."""
import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

from app.ha_bridge import BridgeState
from app.supervisor_discovery import SupervisorDiscovery, local_http_ready
from supervisor_fixture_app import SupervisorFixture


@contextmanager
def health_server(payload, status=200):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self):
            assert self.path == '/api/health'
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_local_readiness_uses_real_http():
    with health_server({'status':'ok','version':'1.1.0'}) as port:
        assert local_http_ready(port) is True
    with health_server({'status':'error'}, status=503) as port:
        assert local_http_ready(port) is False
    with health_server(['wrong shape']) as port:
        assert local_http_ready(port) is False
    assert local_http_ready(0) is False


def test_announcement_waits_until_readiness_without_network_side_effects(tmp_path):
    with SupervisorFixture() as fixture:
        async def scenario():
            bridge = BridgeState(tmp_path)
            bridge.load(automatic=True)
            ready = False
            worker = SupervisorDiscovery(bridge, fixture.transport(), interval=0.02, ready_check=lambda: ready)
            worker.start()
            try:
                await asyncio.sleep(0.08)
                assert not fixture.requests and not fixture.announcements
                assert bridge.status()['discovery_state'] == 'pending'
                ready = True
                for _ in range(150):
                    if bridge.status()['discovery_state'] == 'announced':
                        break
                    await asyncio.sleep(0.02)
                assert bridge.status()['discovery_state'] == 'announced'
                assert len(fixture.announcements) == 1
            finally:
                await worker.close()
        asyncio.run(scenario())
