"""Real HTTP against an explicit Supervisor fixture; no live HA is claimed."""
import asyncio
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import socket
from threading import Thread
import time

from fastapi.testclient import TestClient
import httpx
import pytest
import uvicorn

from app.ha_bridge import BridgeState
from app.main import create_app
from app.supervisor_discovery import (
    INTERVAL, RESPONSE_LIMIT, SupervisorDiscovery, SupervisorError,
    SupervisorTransport, UnixHTTPConnection, valid_record,
)
from supervisor_fixture_app import SupervisorFixture, create_fixture_app, FIXTURE_TOKEN

CSRF = {"X-Menu-Compra": "1"}


def eventually(check, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for fixture/app state")


def status_is(client, state):
    status = client.get("/api/ha/status").json()
    return status if status["discovery_state"] == state else None


@contextmanager
def real_app(app):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error",
                                           access_log=False, proxy_headers=False))
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    try:
        eventually(lambda: server.started, timeout=15)
        port = server.servers[0].sockets[0].getsockname()[1]
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=CSRF, timeout=3, trust_env=False) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


def test_real_tcp_full_lifecycle_keys_disable_reenable_and_restart(tmp_path, caplog):
    app = create_fixture_app(tmp_path, discovery_interval=0.08)
    with real_app(app) as client:
        state = eventually(lambda: status_is(client, "announced"))
        assert state == {"enabled": True, "has_token": True, "base_url": "http://cafebabe-menu-compra:8099",
                         "protocol_version": 1, "automatic": True, "discovery_state": "announced"}
        fixture = app.state.supervisor_fixture
        token = client.post("/api/ha/token").json()["token"]
        assert client.get("/bridge/v1/health", headers={"Authorization": "Bearer " + token}).json() == {
            "status": "ok", "version": "1.1.0"}
        with fixture.lock:
            payload = next(iter(fixture.announcements.values()))
            assert payload == {"service": "menu_compra", "config": {
                "base_url": state["base_url"], "api_key": token, "protocol_version": 1}}
            assert all(req[3] == "Bearer " + FIXTURE_TOKEN for req in fixture.requests)
        assert token not in client.get("/api/ha/status").text
        assert token not in client.get("/api/bootstrap").text
        assert token not in client.get("/api/backup").text
        assert client.post("/api/ha/config", json={"enabled": False}, headers={"X-Menu-Compra": ""}).status_code == 403
        disabled = client.post("/api/ha/config", json={"enabled": False}).json()
        assert disabled["discovery_state"] == "disabled"
        eventually(lambda: not fixture.announcements)
        assert client.get("/bridge/v1/health", headers={"Authorization": "Bearer " + token}).status_code == 404
        client.post("/api/ha/config", json={"enabled": True}).raise_for_status()
        eventually(lambda: status_is(client, "announced"))
        assert client.post("/api/ha/token").json()["token"] == token
        rotated = client.post("/api/ha/rotate").json()["token"]
        assert rotated != token
        eventually(lambda: status_is(client, "announced"))
        assert next(iter(fixture.announcements.values()))["config"]["api_key"] == rotated
        assert client.get("/bridge/v1/health", headers={"Authorization": "Bearer " + token}).status_code == 401
        assert client.get("/bridge/v1/health", headers={"Authorization": "Bearer " + rotated}).status_code == 200
        client.post("/api/ha/config", json={"enabled": False}).raise_for_status()
        eventually(lambda: not fixture.announcements)
        requests = list(fixture.requests)
        assert any(method == "DELETE" for method, *_ in requests)
        assert len([r for r in requests if r[0] == "POST"]) >= 3
    assert app.state.supervisor_discovery.task.done()
    with real_app(create_fixture_app(tmp_path)) as restarted:
        eventually(lambda: status_is(restarted, "disabled"))
        assert restarted.get("/api/ha/status").json()["has_token"]
        assert not restarted.get("/api/ha/status").json()["enabled"]
    assert token not in caplog.text and rotated not in caplog.text and FIXTURE_TOKEN not in caplog.text


def test_disabling_during_inflight_post_never_restores_enabled_or_announced(tmp_path):
    with SupervisorFixture() as fixture:
        fixture.faults[("POST", "/discovery")] = ["slow"]
        app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport(timeout=3), discovery_interval=30)
        with TestClient(app, headers=CSRF) as client:
            eventually(lambda: any(req[0] == "POST" for req in fixture.requests))
            token = client.post("/api/ha/token").json()["token"]
            client.post("/api/ha/config", json={"enabled": False}).raise_for_status()
            assert status_is(client, "disabled")
            assert client.get("/bridge/v1/health", headers={"Authorization": "Bearer " + token}).status_code == 404
            eventually(lambda: any(req[0] == "DELETE" for req in fixture.requests))
            eventually(lambda: not fixture.announcements)
            assert status_is(client, "disabled")
            assert not (tmp_path / "ha_discovery.json").exists()


def test_automatic_mode_does_not_relax_production_ingress_or_csrf(tmp_path):
    with SupervisorFixture() as fixture:
        app = create_app(tmp_path, development=False, supervisor_transport=fixture.transport())
        with TestClient(app, client=("172.30.32.2", 1234), headers=CSRF) as ingress:
            eventually(lambda: status_is(ingress, "announced"))
            token = ingress.post("/api/ha/token").json()["token"]
            assert ingress.post("/api/ha/config", json={"enabled": False}, headers={"X-Menu-Compra": ""}).status_code == 403
            # Use a bare client without another lifespan, sharing the real app.
            core = TestClient(app, client=("172.30.32.1", 1234))
            try:
                for path in ("/", "/api/ha/status", "/api/bootstrap"):
                    assert core.get(path, headers={"Authorization": "Bearer " + token, "X-Forwarded-For": "172.30.32.2"}).status_code == 403
                assert core.get("/bridge/v1/health", headers={"Authorization": "Bearer " + token}).status_code == 200
            finally:
                core.close()


def test_restart_keeps_token_uuid_and_no_duplicate_announcements(tmp_path):
    with SupervisorFixture() as fixture:
        for _ in range(2):
            app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport(), discovery_interval=0.04)
            with TestClient(app, headers=CSRF) as client:
                eventually(lambda: status_is(client, "announced"))
                current = client.post("/api/ha/token").json()["token"]
                if _ == 0:
                    token = current
                    uuid = next(iter(fixture.announcements))
                    eventually(lambda: len([r for r in fixture.requests if r[0] == "POST"]) >= 2)
                else:
                    assert current == token
                    assert list(fixture.announcements) == [uuid]
            assert app.state.supervisor_discovery.task.done()
        assert len(fixture.announcements) == 1  # clean shutdown does not withdraw


@pytest.mark.parametrize("enabled", [True, False])
def test_existing_private_config_preserves_enabled_and_key(tmp_path, enabled):
    bridge = BridgeState(tmp_path)
    bridge.configure(True)
    token = bridge.reveal()["token"]
    bridge.configure(enabled)
    with SupervisorFixture() as fixture:
        with TestClient(create_app(tmp_path, development=True, supervisor_transport=fixture.transport(),
                                   discovery_interval=0.03), headers=CSRF) as client:
            eventually(lambda: status_is(client, "announced" if enabled else "disabled"))
            assert client.get("/api/ha/status").json()["enabled"] is enabled
            assert json.loads(bridge.path.read_text())["token"] == token
            assert bool(fixture.announcements) is enabled


@pytest.mark.parametrize("contents", ["{bad", "{}", "[]", "x" * 9000,
                                      '{"version":1,"enabled":true,"token":"invalid"}'])
def test_existing_bad_config_is_not_new_supervised_install(tmp_path, contents):
    path = tmp_path / "ha_bridge.json"
    path.write_text(contents)
    with SupervisorFixture() as fixture:
        with TestClient(create_app(tmp_path, development=True, supervisor_transport=fixture.transport())) as client:
            eventually(lambda: status_is(client, "disabled"))
            assert client.get("/api/health").status_code == 200
            assert client.get("/bridge/v1/health").status_code == 404
            assert not fixture.announcements
    assert path.read_text() == contents


def test_no_supervisor_no_network_no_invented_url_or_key(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("SUPERVISOR_SOCKET", raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("Network must not be used without Supervisor transport")
    monkeypatch.setattr(http.client.HTTPConnection, "connect", forbidden)
    app = create_app(tmp_path, development=True)
    with TestClient(app, headers=CSRF) as client:
        assert client.get("/api/ha/status").json() == {
            "enabled": False, "has_token": False, "base_url": "", "protocol_version": 1,
            "automatic": False, "discovery_state": "unavailable"}
        assert not (tmp_path / "ha_bridge.json").exists()
        client.post("/api/ha/config", json={"enabled": True}).raise_for_status()
        assert client.get("/api/ha/status").json()["discovery_state"] == "unavailable"
        assert client.get("/api/ha/status").json()["base_url"] == ""


@pytest.mark.parametrize("fault", ["error", "invalid_json", "oversized", "oversized_chunkless", "redirect", "disconnect"])
def test_real_transport_safe_errors_and_bounded_response(fault, caplog):
    with SupervisorFixture() as fixture:
        fixture.faults[("GET", "/addons/self/info")] = [fault]
        transport = fixture.transport()
        try:
            with pytest.raises(SupervisorError) as error:
                transport.request("GET", "/addons/self/info")
            assert "SECRET" not in str(error.value) and FIXTURE_TOKEN not in str(error.value)
            assert len(fixture.requests) == 1  # redirects not followed, no hidden retry
            assert transport.request("GET", "/addons/self/info")["slug"] == fixture.slug
        finally:
            transport.close()
    assert "SECRET-REMOTE-RESPONSE" not in caplog.text and FIXTURE_TOKEN not in caplog.text


@pytest.mark.parametrize("fault", ["error", "drop_after_post", "bad_uuid"])
def test_retry_does_not_rotate_key_and_recovers_uncertain_post(tmp_path, fault):
    with SupervisorFixture() as fixture:
        fixture.faults[("POST", "/discovery")] = [fault]
        app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport(), discovery_interval=0.25)
        with TestClient(app, headers=CSRF) as client:
            eventually(lambda: status_is(client, "error"))
            first = client.post("/api/ha/token").json()["token"]
            eventually(lambda: status_is(client, "announced"))
            assert client.post("/api/ha/token").json()["token"] == first
            assert len(fixture.announcements) == 1
            assert all(req[2]["config"]["api_key"] == first for req in fixture.requests if req[0] == "POST")


def test_disable_after_lost_response_recovers_uuid_and_deletes(tmp_path):
    with SupervisorFixture() as fixture:
        fixture.faults[("POST", "/discovery")] = ["drop_after_post"]
        app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport(), discovery_interval=10)
        with TestClient(app, headers=CSRF) as client:
            eventually(lambda: status_is(client, "error"))
            assert fixture.announcements
            journal = json.loads((tmp_path / "ha_discovery.json").read_text())
            assert journal["uuid"] == ""
            client.post("/api/ha/config", json={"enabled": False}).raise_for_status()
            eventually(lambda: not fixture.announcements)
            assert not (tmp_path / "ha_discovery.json").exists()
            assert status_is(client, "disabled")


def test_restart_disabled_deletes_previously_accepted_announcement(tmp_path):
    with SupervisorFixture() as fixture:
        first = create_app(tmp_path, development=True, supervisor_transport=fixture.transport())
        with TestClient(first) as client:
            eventually(lambda: status_is(client, "announced"))
        # Persist explicit disable while the worker is offline.
        state = BridgeState(tmp_path)
        state.load()
        state.configure(False)
        assert fixture.announcements
        with TestClient(create_app(tmp_path, development=True, supervisor_transport=fixture.transport())) as client:
            eventually(lambda: not fixture.announcements)
            assert status_is(client, "disabled")


def test_delete_failure_is_retried_without_reenabling(tmp_path):
    with SupervisorFixture() as fixture:
        app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport(), discovery_interval=0.1)
        with TestClient(app, headers=CSRF) as client:
            eventually(lambda: status_is(client, "announced"))
            uuid = next(iter(fixture.announcements))
            fixture.faults[("DELETE", "/discovery/" + uuid)] = ["error"]
            client.post("/api/ha/config", json={"enabled": False}).raise_for_status()
            eventually(lambda: not fixture.announcements)
            assert status_is(client, "disabled")
            deletes = [req for req in fixture.requests if req[0] == "DELETE"]
            assert len(deletes) == 2


def test_uncertain_reannouncement_after_supervisor_reset_is_deleted(tmp_path):
    with SupervisorFixture() as fixture:
        app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport(), discovery_interval=0.3)
        with TestClient(app, headers=CSRF) as client:
            eventually(lambda: status_is(client, "announced"))
            with fixture.lock:
                old_uuid = next(iter(fixture.announcements))
                fixture.announcements.clear()
                fixture.faults[("POST", "/discovery")] = ["drop_after_post"]
            eventually(lambda: status_is(client, "error"))
            assert fixture.announcements and old_uuid not in fixture.announcements
            assert json.loads((tmp_path / "ha_discovery.json").read_text())["uuid"] == ""
            client.post("/api/ha/config", json={"enabled": False}).raise_for_status()
            eventually(lambda: not fixture.announcements)
            assert status_is(client, "disabled")


def test_stale_uuid_delete_404_is_idempotent(tmp_path):
    with SupervisorFixture() as fixture:
        app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport())
        with TestClient(app, headers=CSRF) as client:
            eventually(lambda: status_is(client, "announced"))
            fixture.announcements.clear()
            client.post("/api/ha/config", json={"enabled": False}).raise_for_status()
            eventually(lambda: not (tmp_path / "ha_discovery.json").exists())
            assert status_is(client, "disabled")


@pytest.mark.parametrize("hostname", ["evil.example", "127.0.0.1", "cafebabe-menu-compra:80/path", "http://evil", "LOCAL"])
def test_invalid_identity_never_publishes_credentials(tmp_path, hostname):
    with SupervisorFixture() as fixture:
        fixture.hostname = hostname
        with TestClient(create_app(tmp_path, development=True, supervisor_transport=fixture.transport())) as client:
            eventually(lambda: status_is(client, "error"))
            assert client.get("/api/ha/status").json()["base_url"] == ""
            assert not fixture.announcements
            assert not any(req[0] == "POST" for req in fixture.requests)


def test_nonblocking_ui_and_shutdown_bounds_pending_http_by_timeout(tmp_path):
    with SupervisorFixture() as fixture:
        fixture.faults[("GET", "/addons/self/info")] = ["slow"]
        # Native Windows recv may finish only at the socket timeout, even after
        # shutdown from another thread; lifecycle must still remain bounded.
        app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport(timeout=0.3))
        started = time.monotonic()
        with TestClient(app) as client:
            eventually(lambda: fixture.requests)
            before = time.monotonic()
            assert client.get("/api/health").status_code == 200
            assert client.get("/api/ha/status").json()["discovery_state"] == "pending"
            assert time.monotonic() - before < 1
        assert time.monotonic() - started < 1.5
        assert app.state.supervisor_discovery.task.done()
        count = len(fixture.requests)
        time.sleep(0.1)
        assert len(fixture.requests) == count


def test_timeout_bounds_entire_exchange():
    with SupervisorFixture() as fixture:
        fixture.faults[("GET", "/addons/self/info")] = ["slow"]
        transport = fixture.transport(timeout=0.1)
        started = time.monotonic()
        try:
            with pytest.raises(SupervisorError):
                transport.request("GET", "/addons/self/info")
        finally:
            transport.close()
        assert time.monotonic() - started < 1


def test_failed_delete_survives_restart_while_disabled(tmp_path):
    with SupervisorFixture() as fixture:
        app = create_app(tmp_path, development=True, supervisor_transport=fixture.transport(), discovery_interval=30)
        with TestClient(app, headers=CSRF) as client:
            eventually(lambda: status_is(client, "announced"))
            uuid = next(iter(fixture.announcements))
            fixture.faults[("DELETE", "/discovery/" + uuid)] = ["error"]
            client.post("/api/ha/config", json={"enabled": False}).raise_for_status()
            eventually(lambda: any(req[0] == "DELETE" for req in fixture.requests))
            assert fixture.announcements
        assert json.loads((tmp_path / "ha_discovery.json").read_text())["uuid"] == uuid
        private_config = json.loads((tmp_path / "ha_bridge.json").read_text())
        assert set(private_config) == {"version", "enabled", "token"}
        assert private_config["enabled"] is False
        with TestClient(create_app(tmp_path, development=True, supervisor_transport=fixture.transport())) as client:
            eventually(lambda: not fixture.announcements)
            assert status_is(client, "disabled")
            assert client.get("/api/ha/status").json()["has_token"] is True
        assert not (tmp_path / "ha_discovery.json").exists()


def test_deadline_bounds_slow_drip_headers():
    with SupervisorFixture() as fixture:
        fixture.faults[("GET", "/addons/self/info")] = ["drip_headers"]
        transport = fixture.transport(timeout=0.2)
        started = time.monotonic()
        try:
            with pytest.raises(SupervisorError):
                transport.request("GET", "/addons/self/info")
        finally:
            transport.close()
        assert time.monotonic() - started < 1


def test_retries_are_interval_bounded_and_never_regenerate_credentials(tmp_path):
    with SupervisorFixture() as fixture:
        fixture.faults[("GET", "/addons/self/info")] = ["error"] * 20
        with TestClient(create_app(tmp_path, development=True, supervisor_transport=fixture.transport(),
                                   discovery_interval=0.3), headers=CSRF) as client:
            eventually(lambda: status_is(client, "error"))
            key = client.post("/api/ha/token").json()["token"]
            initial_count = len(fixture.requests)
            time.sleep(0.12)
            assert len(fixture.requests) == initial_count
            eventually(lambda: len(fixture.requests) > initial_count)
            assert client.post("/api/ha/token").json()["token"] == key


def test_invalid_journal_stops_announcements_without_disabling_ui_or_changing_key(tmp_path):
    state = BridgeState(tmp_path)
    state.configure(True)
    key = state.reveal()["token"]
    state.discovery_path.write_text("{bad")
    with SupervisorFixture() as fixture:
        with TestClient(create_app(tmp_path, development=True, supervisor_transport=fixture.transport()), headers=CSRF) as client:
            eventually(lambda: status_is(client, "error"))
            assert client.post("/api/ha/token").json()["token"] == key
            assert client.get("/api/health").status_code == 200
            assert not fixture.requests


def test_environment_fixed_host_and_no_credentials_or_proxy_leaks(monkeypatch):
    assert SupervisorTransport.from_environment({}) is None
    assert SupervisorTransport.from_environment({"SUPERVISOR_TOKEN": "bad\r\nheader"}) is None
    transport = SupervisorTransport.from_environment({"SUPERVISOR_TOKEN": "secret", "SUPERVISOR_URL": "http://evil"})
    connection = transport._connection(False)
    assert connection.host == "supervisor" and connection.port == 80
    transport.close()
    with pytest.raises(SupervisorError):
        transport.request("GET", "/addons/self/info")
    assert INTERVAL == 30


@pytest.mark.parametrize("method,path,body", [
    ("GET", "http://evil/discovery", None), ("GET", "/discovery", None),
    ("POST", "/addons/self/info", {}), ("DELETE", "/discovery/../../unsafe", None),
    ("GET", "/addons/self/info", {}),
])
def test_transport_narrow_allowlist(method, path, body):
    transport = SupervisorTransport(token="secret")
    with pytest.raises(SupervisorError):
        transport.request(method, path, body)
    transport.close()


def test_oversized_request_rejected_before_network():
    transport = SupervisorTransport(token="secret")
    with pytest.raises(SupervisorError):
        transport.request("POST", "/discovery", {"big": "x" * RESPONSE_LIMIT})
    transport.close()


def test_journal_validation_and_atomic_save_failure_keeps_key(tmp_path, monkeypatch):
    state = BridgeState(tmp_path)
    state.load(automatic=True)
    token = state.reveal()["token"]
    record = {"uuid": "a" * 32, "config": {"api_key": token, "base_url": "http://fixture-menu-compra:8099", "protocol_version": 1}}
    assert valid_record(record)
    state.record_discovery(record)
    previous = state.path.read_bytes()
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        state.rotate()
    assert state.reveal()["token"] == token and state.path.read_bytes() == previous
    assert state.discovery_snapshot()[2] == record
    assert not list(tmp_path.glob(".ha-bridge-*"))


def test_inflight_old_response_never_announces_newer_key(tmp_path):
    state = BridgeState(tmp_path)
    state.load(automatic=True)
    original = state.reveal()["token"]
    with SupervisorFixture() as fixture:
        transport = fixture.transport()
        controller = SupervisorDiscovery(state, transport)
        async def scenario():
            await controller.reconcile()
            state.rotate()
            state.discovery_status("announced", expected=(True, original))
            assert state.status()["discovery_state"] == "pending"
            await controller.reconcile()
            assert state.status()["discovery_state"] == "announced"
            assert next(iter(fixture.announcements.values()))["config"]["api_key"] == state.reveal()["token"]
            await controller.close()
        asyncio.run(scenario())


@pytest.mark.skipif(os.name != "posix" or not hasattr(socket, "AF_UNIX"), reason="Unix socket transport requires POSIX AF_UNIX")
def test_real_unix_socket_preferred_without_token_and_fixed_tcp_fallback(tmp_path, monkeypatch):
    import socketserver
    from http.server import BaseHTTPRequestHandler
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            body = b'{"result":"ok","data":{"slug":"local_menu_compra","hostname":"local-menu-compra"}}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    # Keep AF_UNIX paths short on Linux even when pytest's temp root is long.
    path = str(Path(os.environ.get("TMPDIR", str(tmp_path))) / ("mc-" + str(os.getpid()) + ".sock"))
    with socketserver.UnixStreamServer(path, Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        transport = SupervisorTransport.from_environment({"SUPERVISOR_SOCKET": path, "SUPERVISOR_TOKEN": "not-sent-on-unix"})
        try:
            assert isinstance(transport._connection(True), UnixHTTPConnection)
            assert transport.request("GET", "/addons/self/info")["slug"] == "local_menu_compra"
            assert seen == [None]
        finally:
            transport.close()
            server.shutdown()
            thread.join(timeout=5)
    os.unlink(path)
    with SupervisorFixture() as fixture:
        transport = SupervisorTransport(socket_path=path, token=FIXTURE_TOKEN)
        original = transport._connection
        monkeypatch.setattr(transport, "_connection", lambda unix: original(True) if unix else fixture.transport()._connection(False))
        try:
            assert transport.request("GET", "/addons/self/info")["slug"] == fixture.slug
        finally:
            transport.close()
