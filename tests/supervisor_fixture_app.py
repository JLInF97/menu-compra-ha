"""Explicit local Supervisor fixture + real app factory, NOT Home Assistant.

Browser runner (repository root, PYTHONPATH=menu_compra;tests):
    uvicorn supervisor_fixture_app:create_fixture_app --factory --host 127.0.0.1 --port 8099
Set MENU_COMPRA_DATA_DIR to a fresh scratch directory. No production endpoint,
secret, DNS destination, permissions or Ingress rules are changed by this module.
"""
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from threading import RLock, Thread
import time
from uuid import uuid4

from app.main import create_app
from app.supervisor_discovery import SupervisorTransport, RESPONSE_LIMIT

FIXTURE_TOKEN = "fixture-supervisor-token-not-a-production-credential"


class FixtureTransport(SupervisorTransport):
    def __init__(self, fixture, *, timeout=0.5):
        super().__init__(token=FIXTURE_TOKEN, timeout=timeout)
        self.fixture = fixture

    def _connection(self, unix):
        assert not unix
        return http.client.HTTPConnection("127.0.0.1", self.fixture.port, timeout=self.timeout)


class SupervisorFixture:
    """Threaded TCP fixture matching Supervisor 2026.11.0 response envelopes.

    faults[(method, path)] = [fault, ...] consumes one injected fault per call.
    announcements and requests may be inspected under lock by local tests only.
    """

    def __init__(self, *, slug="cafebabe_menu_compra"):
        self.slug = slug
        self.hostname = slug.replace("_", "-")
        self.lock = RLock()
        self.requests = []
        self.announcements = {}
        self.faults = {}
        self.port = 0
        self.server = None
        self.thread = None

    def transport(self, *, timeout=0.5):
        return FixtureTransport(self, timeout=timeout)

    def __enter__(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def do_DELETE(self):
                self.handle_request()

            def handle_request(self):
                body = None
                if self.headers.get("Content-Length"):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with fixture.lock:
                    fixture.requests.append((self.command, self.path, body, self.headers.get("Authorization")))
                    faults = fixture.faults.get((self.command, self.path), [])
                    fault = faults.pop(0) if faults else None
                if fault == "slow":
                    time.sleep(2)
                if fault == "drip_headers":
                    try:
                        for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(0.04)
                    except OSError:
                        pass
                    return
                if fault == "disconnect":
                    self.close_connection = True
                    return
                if self.headers.get("Authorization") != "Bearer " + FIXTURE_TOKEN:
                    self.respond(401, {"result": "error", "message": "fixture auth failure"})
                    return
                if fault == "redirect":
                    self.respond(302, {}, headers={"Location": "http://127.0.0.1:1/leak"})
                    return
                if fault == "error":
                    self.respond(503, {"result": "error", "message": "SECRET-REMOTE-RESPONSE"})
                    return
                if fault == "invalid_json":
                    self.respond(200, None, raw=b"SECRET-REMOTE-RESPONSE")
                    return
                if fault == "oversized":
                    self.respond(200, None, raw=b"x" * (RESPONSE_LIMIT + 1))
                    return
                if fault == "oversized_chunkless":
                    self.respond(200, None, raw=b"x" * (RESPONSE_LIMIT + 1), no_length=True)
                    return
                with fixture.lock:
                    if self.command == "GET" and self.path == "/addons/self/info":
                        data = {"slug": fixture.slug, "hostname": fixture.hostname}
                    elif self.command == "POST" and self.path == "/discovery":
                        assert set(body) == {"service", "config"} and body["service"] == "menu_compra"
                        # Supervisor has a single message per app/service; changed
                        # config updates that message instead of duplicating it.
                        uuid = next(iter(fixture.announcements), uuid4().hex)
                        fixture.announcements[uuid] = body
                        data = {"uuid": uuid if fault != "bad_uuid" else "../../unsafe"}
                    elif self.command == "DELETE" and self.path.startswith("/discovery/"):
                        if fixture.announcements.pop(self.path.split("/")[-1], None) is None:
                            self.respond(404, {"result": "error"})
                            return
                        data = None
                    else:
                        self.respond(403, {"result": "error"})
                        return
                if fault == "drop_after_post":
                    self.close_connection = True
                    return
                self.respond(200, {"result": "ok", **({"data": data} if data is not None else {})})

            def respond(self, status, data, *, raw=None, headers=None, no_length=False):
                payload = json.dumps(data).encode() if raw is None else raw
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Connection", "close")
                    if not no_length:
                        self.send_header("Content-Length", str(len(payload)))
                    for key, value in (headers or {}).items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(payload)
                except (OSError, ConnectionError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()


def create_fixture_app(data_dir=None, *, discovery_interval=0.2):
    """Real development app + fixture TCP Supervisor, scoped to app lifespan."""
    fixture = SupervisorFixture()
    app = create_app(data_dir or os.environ["MENU_COMPRA_DATA_DIR"], development=True,
                     supervisor_transport=fixture.transport(), discovery_interval=discovery_interval)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        with fixture:
            async with original_lifespan(application):
                yield

    app.router.lifespan_context = lifespan
    app.state.supervisor_fixture = fixture
    return app


# Alias retained for the parent's shared browser runner.
create_test_app = create_fixture_app
