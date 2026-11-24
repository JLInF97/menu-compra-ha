"""Narrow stdlib Supervisor client and asynchronous discovery controller.

Protocol: Supervisor 2026.11.0 /addons/self/info, POST /discovery and
DELETE /discovery/{uuid}; no hassio_api permission or Core API access.
The client never follows redirects, uses proxies, or logs remote responses.

Tests may inject a transport implementing request(method, path, body=None)
and close(), via create_app(..., supervisor_transport=transport,
discovery_interval=seconds). No user-configurable endpoint exists in production.
"""
import asyncio
from collections.abc import Callable
from contextlib import suppress
import http.client
import json
import os
import re
import socket
from threading import Lock, Timer

RESPONSE_LIMIT = 64 * 1024
INTERVAL = 30.0
UUID_PATTERN = re.compile(r"[a-f0-9]{32}\Z")
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*\Z")
ORIGIN_PATTERN = re.compile(r"http://[a-z0-9]+(?:-[a-z0-9]+)*:8099\Z")
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")


class SupervisorError(Exception):
    """Safe error; remote response bodies and credentials never reach callers."""


def local_http_ready(port=8099):
    """No anunciar antes de que Uvicorn atienda: evita el fallo del primer health."""
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=0.5)
    try:
        connection.request('GET', '/api/health', headers={'Connection': 'close'})
        response = connection.getresponse()
        data = response.read(1025)
        return response.status == 200 and len(data) <= 1024 and json.loads(data).get('status') == 'ok'
    except (OSError, http.client.HTTPException, ValueError, AttributeError):
        return False
    finally:
        connection.close()


def valid_record(record):
    """Validate the separate private write-ahead journal in ha_discovery.json."""
    if not isinstance(record, dict) or set(record) != {"uuid", "config"}:
        return False
    uuid, config = record["uuid"], record["config"]
    if not isinstance(uuid, str) or (uuid and not UUID_PATTERN.fullmatch(uuid)):
        return False
    return (isinstance(config, dict) and set(config) == {"base_url", "api_key", "protocol_version"}
            and type(config["protocol_version"]) is int and config["protocol_version"] == 1
            and isinstance(config["base_url"], str) and len(config["base_url"]) <= 200
            and ORIGIN_PATTERN.fullmatch(config["base_url"]) is not None
            and isinstance(config["api_key"], str) and KEY_PATTERN.fullmatch(config["api_key"]) is not None)


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("supervisor", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(getattr(socket, "AF_UNIX"), socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class SupervisorTransport:
    """Fixed-host authenticated HTTP; Unix first, token TCP compatibility second."""

    def __init__(self, *, socket_path=None, token="", timeout=5.0):
        self.socket_path = socket_path
        self._token = token
        self.timeout = timeout
        self._lock = Lock()
        self._active = set()
        self._closed = False

    @classmethod
    def from_environment(cls, environ=None):
        env = os.environ if environ is None else environ
        path = env.get("SUPERVISOR_SOCKET", "")
        # AF_UNIX availability alone does not imply usable Unix sockets on Windows.
        if os.name != "posix" or not hasattr(socket, "AF_UNIX") or not os.path.isabs(path):
            path = None
        token = env.get("SUPERVISOR_TOKEN", "")
        # Reject control characters instead of passing them to HTTP headers.
        if not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            token = ""
        return cls(socket_path=path, token=token) if path or token else None

    def _connection(self, unix):
        if unix:
            return UnixHTTPConnection(self.socket_path, self.timeout)
        return http.client.HTTPConnection("supervisor", 80, timeout=self.timeout)

    @staticmethod
    def _abort(connection):
        # HTTPConnection.getresponse() detaches sock for Connection: close,
        # although HTTPResponse.fp can still be blocked reading that socket.
        sock = getattr(connection, "_supervisor_socket", None) or connection.sock
        if sock is not None:
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
        connection.close()

    def close(self):
        with self._lock:
            self._closed = True
            connections = tuple(self._active)
        for connection in connections:
            self._abort(connection)

    def request(self, method, path, body=None):
        allowed = ((method == "GET" and path == "/addons/self/info" and body is None)
                   or (method == "POST" and path == "/discovery")
                   or (method == "DELETE" and path.startswith("/discovery/")
                       and UUID_PATTERN.fullmatch(path[len("/discovery/"):]) and body is None))
        if not allowed:
            raise SupervisorError("Operación Supervisor no permitida")
        payload = json.dumps(body, ensure_ascii=True, allow_nan=False).encode("ascii") if body is not None else None
        if payload is not None and len(payload) > RESPONSE_LIMIT:
            raise SupervisorError("Solicitud Supervisor demasiado grande")
        modes = ([True] if self.socket_path else []) + ([False] if self._token else [])
        for unix in modes:
            connection = self._connection(unix)
            with self._lock:
                if self._closed:
                    raise SupervisorError("Conexión Supervisor cerrada")
                self._active.add(connection)
            # Bound the entire exchange, not only inactivity between received bytes.
            timer = Timer(self.timeout, self._abort, args=(connection,))
            timer.daemon = True
            timer.start()
            try:
                headers = {"Accept": "application/json", "Connection": "close"}
                if not unix:
                    headers["Authorization"] = "Bearer " + self._token
                if payload is not None:
                    headers["Content-Type"] = "application/json"
                connection.request(method, path, body=payload, headers=headers)
                setattr(connection, "_supervisor_socket", connection.sock)
                response = connection.getresponse()
                if method == "DELETE" and response.status == 404:
                    return {}
                if response.status != 200:
                    raise SupervisorError("Supervisor ha rechazado la solicitud")
                length = response.getheader("Content-Length")
                if length is not None and (not length.isdecimal() or int(length) > RESPONSE_LIMIT):
                    raise SupervisorError("Respuesta Supervisor no válida")
                raw = response.read(RESPONSE_LIMIT + 1)
                if len(raw) > RESPONSE_LIMIT:
                    raise SupervisorError("Respuesta Supervisor demasiado grande")
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("result") != "ok":
                    raise SupervisorError("Respuesta Supervisor no válida")
                result = data.get("data", {})
                if not isinstance(result, dict):
                    raise SupervisorError("Respuesta Supervisor no válida")
                return result
            except (OSError, http.client.HTTPException):
                # Only the fixed authenticated alternative can be attempted.
                if not unix or not self._token:
                    raise SupervisorError("Supervisor no disponible") from None
            except (ValueError, UnicodeError, RecursionError):
                raise SupervisorError("Respuesta Supervisor no válida") from None
            finally:
                timer.cancel()
                self._abort(connection)
                with self._lock:
                    self._active.discard(connection)
        raise SupervisorError("Supervisor no disponible")


class SupervisorDiscovery:
    """Single serialized worker. UI writes signal it without waiting for the network.

    The private journal is saved *before* POST. An uncertain POST is retried with
    the same config to recover its idempotent UUID, including after restart or
    disable. GET /discovery is Core-only, so it is deliberately never used here.
    A clean shutdown keeps accepted discovery for Supervisor/Core restarts.
    """

    def __init__(self, bridge, transport, *, interval=INTERVAL, ready_check: Callable[[], bool] | None = None):
        if interval <= 0:
            raise ValueError("El intervalo debe ser positivo")
        self.bridge = bridge
        self.transport = transport
        self.interval = interval
        self.task = None
        self._loop = None
        self._wake = asyncio.Event()
        self._base_url = ""
        self._closed = False
        self._ready_check = ready_check
        self._ready = ready_check is None

    def start(self):
        if self.transport is None or self.task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self.bridge.on_change = self.notify
        self.task = asyncio.create_task(self._run(), name="menu-compra-supervisor-discovery")

    def notify(self):
        if not self._closed and self._loop is not None:
            with suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._wake.set)

    async def close(self):
        self._closed = True
        self.bridge.on_change = None
        if self.transport is not None:
            self.transport.close()
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def _request(self, method, path, body=None):
        return await asyncio.to_thread(self.transport.request, method, path, body)

    async def _post(self, config):
        # Even a periodic reannouncement can get a new UUID if Supervisor's
        # discovery store was reset. Journal every POST before sending it.
        self.bridge.record_discovery({"uuid": "", "config": config})
        data = await self._request("POST", "/discovery", {"service": "menu_compra", "config": config})
        uuid = data.get("uuid")
        if not isinstance(uuid, str) or not UUID_PATTERN.fullmatch(uuid):
            raise SupervisorError("Identificador de anuncio no válido")
        record = {"uuid": uuid, "config": config}
        self.bridge.record_discovery(record)
        return record

    async def reconcile(self):
        """One bounded reconciliation; public for deterministic injected tests."""
        if self.bridge.discovery_error:
            raise SupervisorError("Registro de descubrimiento no legible")
        enabled, token, record = self.bridge.discovery_snapshot()
        expected = enabled, token
        if not self._base_url:
            info = await self._request("GET", "/addons/self/info")
            slug, hostname = info.get("slug"), info.get("hostname")
            if (not isinstance(slug, str) or len(slug) > 100 or not SLUG_PATTERN.fullmatch(slug)
                    or not isinstance(hostname, str) or hostname != slug.replace("_", "-")):
                raise SupervisorError("Identidad de aplicación no válida")
            self._base_url = f"http://{hostname}:8099"
            self.bridge.discovery_status("pending" if enabled else "disabled", self._base_url, expected=expected)
        config = {"base_url": self._base_url, "api_key": token, "protocol_version": 1} if enabled else None
        # Recover UUID after a response was lost, before deleting or changing it.
        if record is not None and not record["uuid"]:
            record = await self._post(record["config"])
        if record is not None and (not enabled or record["config"] != config):
            await self._request("DELETE", "/discovery/" + record["uuid"])
            self.bridge.record_discovery(None)
            record = None
        # The key or enabled flag may have changed while HTTP was in progress.
        if self.bridge.discovery_snapshot()[:2] != expected:
            self._wake.set()
            return
        if not enabled:
            self.bridge.discovery_status("disabled", expected=expected)
            return
        await self._post(config)
        self.bridge.discovery_status("announced", expected=expected)

    async def _run(self):
        while not self._closed:
            self._wake.clear()
            try:
                ready_check = self._ready_check
                if not self._ready and ready_check is not None:
                    self._ready = await asyncio.to_thread(ready_check)
                    if not self._ready:
                        await asyncio.sleep(min(1.0, self.interval))
                        continue
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never log exception text, response bodies, URLs or credentials.
                enabled, token, _ = self.bridge.discovery_snapshot()
                self.bridge.discovery_status("error" if enabled else "disabled", expected=(enabled, token))
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
            except TimeoutError:
                pass
