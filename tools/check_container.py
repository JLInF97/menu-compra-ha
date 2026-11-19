"""Smoke Docker real, local y sin publicación; no arranca Docker Desktop."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]

# Se ejecuta con el Python de la imagen: no instala herramientas ni abre puertos.
HTTP_PROBE = r'''
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

assert os.environ.get("MENU_COMPRA_DEV", "0") == "0", "Producción desactivada"
base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
opener = build_opener(ProxyHandler({}), NoRedirect())
def request(path, headers=None):
    try:
        response = opener.open(Request(base + path, headers=headers or {}), timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read()
status, body = request("/api/health")
assert status == 200, (status, body)
health = json.loads(body)
assert health == {"status": "ok", "version": "1.0.0"}, health
spoofs = [
    {},
    {"X-Forwarded-For": "172.30.32.2"},
    {"Forwarded": "for=172.30.32.2;proto=https"},
    {"X-Real-IP": "172.30.32.2"},
    {"X-Forwarded-For": "172.30.32.2", "Forwarded": "for=172.30.32.2", "X-Menu-Compra": "1"},
]
checks = []
for path in ("/", "/api/bootstrap", "/api/products", "/static/app.js"):
    for headers in spoofs:
        status, body = request(path, headers)
        assert status == 403, (path, headers, status, body)
        checks.append({"path": path, "headers": headers, "status": status})
status, body = request("/bridge/v1/health")
assert status == 404, (status, body)
print(json.dumps({"health": health, "denied": checks, "bridge_disabled": True}))
'''

# La BD de la app solo se lee. La escritura testigo usa OTRA BD en el volumen
# efímero; no se introducen productos ni se simula la IP del Supervisor.
DATA_PROBE = r'''
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

phase, token = sys.argv[1:3]
root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/data")
assert phase in ("prepare", "verify"), phase
app_path = root / "menu_compra.sqlite3"
assert app_path.is_file(), app_path
with sqlite3.connect(app_path.resolve().as_uri() + "?mode=ro", uri=True) as database:
    database.create_collation("NOCASE", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    assert database.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    version = database.execute("PRAGMA user_version").fetchone()[0]
    tables = [r[0] for r in database.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    assert {"products", "shopping_items", "menu_entries", "categories", "supermarkets"} <= set(tables), tables
    # Las semillas INSERT OR IGNORE avanzan sqlite_sequence en cada arranque.
    # Se compara esquema y datos reales, no esos contadores internos de SQLite.
    dump = [line for line in database.iterdump()
            if not line.startswith(('DELETE FROM "sqlite_sequence"', 'INSERT INTO "sqlite_sequence"'))]
    digest = sha256("\n".join(dump).encode()).hexdigest()
probe = root / ".ci-persistence.sqlite3"
if phase == "prepare":
    assert not probe.exists(), "El volumen debe ser nuevo y exclusivo de esta prueba"
    with sqlite3.connect(probe) as database:
        database.execute("CREATE TABLE probe (token TEXT NOT NULL)")
        database.execute("INSERT INTO probe VALUES (?)", (token,))
else:
    assert probe.is_file(), "Se perdió el testigo al reiniciar"
    with sqlite3.connect(probe.resolve().as_uri() + "?mode=ro", uri=True) as database:
        assert database.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert database.execute("SELECT token FROM probe").fetchall() == [(token,)], "Testigo alterado"
print(json.dumps({"schema_version": version, "tables": tables, "app_sha256": digest, "volume_probe": "ok"}))
'''


def docker(*args, timeout=60, check=True):
    """Todos los comandos tienen límite y nunca se ejecutan mediante shell."""
    command = ["docker", *map(str, args)]
    print("+ " + " ".join(command[:5]), flush=True)
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"Docker falló ({result.returncode}): {result.stderr[-6000:]}{result.stdout[-2000:]}")
    return result


def exec_probe(container, source, *args):
    result = docker("exec", container, "python", "-c", source, *args, timeout=45)
    return json.loads(result.stdout)


def wait_ready(container, timeout):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return exec_probe(container, HTTP_PROBE)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(f"El contenedor no superó salud/acceso en {timeout}s: {last_error}")


def smoke(args, report):
    suffix = uuid.uuid4().hex
    container = f"menu-compra-ci-{suffix}"
    volume = f"menu-compra-ci-data-{suffix}"
    image = f"menu-compra-ci:{suffix}"
    owned_volume = owned_container = owned_image = False
    try:
        # Si falta el daemon se falla explícitamente, sin intentar iniciarlo.
        docker("info", "--format", "{{.ServerVersion}}", timeout=20)
        owned_image = True
        docker("buildx", "build", "--platform", args.platform, "--load", "--push=false",
               "--provenance=false", "--tag", image, ROOT / "menu_compra", timeout=args.build_timeout)
        metadata = json.loads(docker("image", "inspect", image).stdout)[0]
        actual_platform = f"{metadata['Os']}/{metadata['Architecture']}"
        if actual_platform != args.platform:
            raise RuntimeError(f"Arquitectura incorrecta: {actual_platform}, se esperaba {args.platform}")
        report["image_platform"] = actual_platform
        docker("volume", "create", volume)
        owned_volume = True
        owned_container = True
        # Sin -p/-P, red externa, secretos, mounts del host ni overrides de entorno.
        docker("run", "--detach", "--name", container, "--platform", args.platform,
               "--pull=never", "--network=none", "--cap-drop=ALL", "--security-opt=no-new-privileges",
               "--mount", f"type=volume,source={volume},target=/data", image)
        state = json.loads(docker("inspect", container).stdout)[0]
        if state["HostConfig"].get("PortBindings") or state["HostConfig"]["PublishAllPorts"]:
            raise RuntimeError("El contenedor publicó puertos inesperadamente")
        environment = dict(item.split("=", 1) for item in state["Config"]["Env"] if "=" in item)
        if environment.get("MENU_COMPRA_DEV") != "0" or environment.get("MENU_COMPRA_DATA_DIR") != "/data":
            raise RuntimeError("La imagen no conserva el entorno de producción esperado")
        report["before_restart"] = wait_ready(container, args.startup_timeout)
        before = exec_probe(container, DATA_PROBE, "prepare", suffix)
        docker("restart", "--time", "10", container, timeout=60)
        report["after_restart"] = wait_ready(container, args.startup_timeout)
        after = exec_probe(container, DATA_PROBE, "verify", suffix)
        if before != after:
            raise RuntimeError(f"Datos de /data alterados tras reiniciar: {before!r} != {after!r}")
        report["persistence"] = after
        report["persistence_scope"] = "BD real intacta y testigo SQLite separado en /data; no se crean productos"
        report["published_ports"] = False
    except BaseException:
        if owned_container:
            try:
                logs = docker("logs", "--tail", "100", container, timeout=15, check=False)
                report["container_logs"] = (logs.stdout + logs.stderr)[-12000:]
            except (OSError, subprocess.TimeoutExpired) as error:
                report["container_logs"] = str(error)
        raise
    finally:
        cleanup_errors = []
        for owned, command in (
            (owned_container, ("rm", "--force", container)),
            (owned_volume, ("volume", "rm", "--force", volume)),
            (owned_image, ("image", "rm", "--force", image)),
        ):
            if owned:
                try:
                    result = docker(*command, timeout=30, check=False)
                    # Un build/run fallido puede no haber creado el recurso.
                    absent = "No such" in result.stderr
                    if result.returncode and not absent:
                        cleanup_errors.append(result.stderr)
                except (OSError, subprocess.TimeoutExpired) as error:
                    cleanup_errors.append(str(error))
        report["cleanup_errors"] = cleanup_errors
        if cleanup_errors and sys.exc_info()[0] is None:
            raise RuntimeError("No se pudieron limpiar todos los recursos Docker")


def positive_integer(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("Debe ser un entero positivo")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("linux/amd64", "linux/arm64"), default="linux/amd64")
    parser.add_argument("--output", type=Path, help="Informe JSON, también si falla Docker")
    parser.add_argument("--build-timeout", type=positive_integer, default=900)
    parser.add_argument("--startup-timeout", type=positive_integer, default=120)
    args = parser.parse_args(argv)
    report = {"status": "failed", "platform": args.platform}
    try:
        smoke(args, report)
        report["status"] = "passed"
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
