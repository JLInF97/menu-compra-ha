"""Prueba UI en Chromium con servidor real y datos temporales.

Requiere Node y npm ci + npx playwright install chromium. No usa Home Assistant.
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def stop_server(server, *, windows=None):
    """Cierra también el hijo del launcher de un venv Windows, no solo su padre."""
    if server.poll() is not None:
        return
    is_windows = os.name == 'nt' if windows is None else windows
    if is_windows:
        # terminate() mata solo el launcher en algunos venvs de Windows y deja
        # Uvicorn vivo, reteniendo server.log y bloqueando borrar los temporales.
        result = subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'],
                                capture_output=True, text=True, timeout=15, check=False)
        if result.returncode and server.poll() is None:
            raise RuntimeError('No se pudo cerrar el árbol del servidor de prueba: ' + result.stderr)
    else:
        server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', type=Path, default=ROOT / 'menu_compra')
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'browser-evidence')
    parser.add_argument('--script', type=Path, default=ROOT / 'tests' / 'browser_v5_1.js')
    parser.add_argument('--supervisor-fixture', action='store_true',
                        help='App real con Supervisor HTTP fixture explícita, nunca un HA real.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="menu-ui-051-", dir=os.environ.get("TMPDIR")) as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, MENU_COMPRA_DEV="1", MENU_COMPRA_DATA_DIR=str(Path(directory) / "data"))
        module = 'app.main:app'
        factory_args = []
        if args.supervisor_fixture:
            module = 'supervisor_fixture_app:create_test_app'
            factory_args = ['--factory']
            env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(ROOT / 'tests'), env.get('PYTHONPATH')]))
        with (Path(directory) / "server.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", module, *factory_args, "--app-dir", str(args.app_dir.resolve()),
                 "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers", "--log-level", "warning"],
                env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("El servidor de prueba terminó prematuramente")
                    try:
                        with urlopen(base + "/api/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("El servidor de prueba no arrancó")
                subprocess.run(["node", str(args.script.resolve()), base,
                                str(args.output.resolve()),
                                *(['--supervisor-fixture'] if args.supervisor_fixture else [])], env=env, check=True)
            finally:
                stop_server(server)
    print("Prueba UI real terminada; servidor detenido y datos temporales eliminados.")


if __name__ == "__main__":
    main()
