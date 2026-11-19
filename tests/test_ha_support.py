"""Infraestructura local REAL. Único doble: salida Telegram en test_ha_telegram.

No registra stubs de Home Assistant ni reemplaza rutas/respuestas del backend.
Usa un puerto loopback efímero, datos scratch explícitos y cierra el servidor.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib
import os
from pathlib import Path
import socket
import sys
import tempfile
import types

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="Pruebas HA puras requieren aiohttp; no requieren Home Assistant")
uvicorn = pytest.importorskip("uvicorn")
create_app = importlib.import_module("app.main").create_app


@pytest.fixture
def anyio_backend():
    return "asyncio"

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get("MENU_COMPRA_TEST_TMPDIR") or tempfile.gettempdir())


def pure_module(name):
    namespace = "_mc_ha_pure_tests"
    if namespace not in sys.modules:
        package = types.ModuleType(namespace)
        package.__path__ = [os.environ.get('MENU_COMPRA_TEST_COMPONENT_DIR', str(ROOT / "custom_components" / "menu_compra"))]
        sys.modules[namespace] = package
    return importlib.import_module(f"{namespace}.{name}")


api = pure_module("api")


@asynccontextmanager
async def real_backend():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mc-ha-backend-", dir=SCRATCH) as directory:
        app = create_app(Path(directory), development=True)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        config = uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on")
        server = uvicorn.Server(config)
        # Uvicorn instala signal handlers en el hilo principal; su context manager
        # los restaura al salir. No se lanzan procesos ni servidores permanentes.
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            for _ in range(250):
                if task.done():
                    await task
                    raise RuntimeError("El servidor terminó antes de arrancar")
                if server.started:
                    break
                await asyncio.sleep(0.02)
            else:
                raise RuntimeError("El backend no arrancó a tiempo")
            url = f"http://127.0.0.1:{port}"
            async with aiohttp.ClientSession() as session:
                async with session.post(url + "/api/ha/config", json={"enabled": True}, headers={"X-Menu-Compra": "1"}) as response:
                    assert response.status == 200
                async with session.post(url + "/api/ha/token", json={}, headers={"X-Menu-Compra": "1"}) as response:
                    assert response.status == 200
                    token = (await response.json())["token"]
                yield types.SimpleNamespace(app=app, url=url, token=token, session=session,
                                            client=api.BridgeClient(session, url, token))
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)
            sock.close()


async def ui(backend, method, path, data=None):
    async with backend.session.request(method, backend.url + "/api/" + path,
                                       json=data, headers={"X-Menu-Compra": "1"}) as response:
        result = await response.json()
        assert response.status < 400, result
        return result


async def create_product(backend, name="Leche", shop_id=1):
    return await ui(backend, "POST", "products", {"name": name, "category_id": 1,
                   "supermarket_id": shop_id, "price_cents": 125, "unit": "l"})
