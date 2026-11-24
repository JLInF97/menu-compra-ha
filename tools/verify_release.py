"""Extrae los tres ZIP y ejecuta las pruebas usando su contenido, no el árbol fuente."""
import argparse
from hashlib import sha256
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import zipfile

VERSION = "1.1.0"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SMOKE = r'''
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
from app.main import create_app
import app.main
assert Path(app.main.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
with TestClient(create_app(sys.argv[2], development=True), headers={"X-Menu-Compra": "1"}) as client:
    assert client.get("/api/health").json() == {"status": "ok", "version": "1.1.0"}
    assert client.get("/").status_code == 200
    assert "menu/batch" in client.get("/static/app.js").text
    categories = client.get("/api/categories").json()
    reserved = next(c for c in categories if c.get("is_system"))
    reserved_shop = next(s for s in client.get("/api/supermarkets").json() if s.get("is_system"))
    assert client.put(f"/api/categories/{reserved['id']}", json={"name": "No cambiar"}).status_code == 409
    assert client.delete(f"/api/categories/{reserved['id']}").status_code == 409
    assert client.put(f"/api/supermarkets/{reserved_shop['id']}", json={"name": "No cambiar"}).status_code == 409
    assert client.delete(f"/api/supermarkets/{reserved_shop['id']}").status_code == 409
    meat = next(c["id"] for c in categories if c["name"] == "Carne")
    created = client.post("/api/products", json={"name": "Filetes de cerdo", "category_id": meat, "supermarket_id": 1, "unit": "kg", "price_cents": 525})
    assert created.status_code == 201
    product_id = created.json()["id"]
    assert client.get(f"/api/products/{product_id}").json()["price_cents"] == 525
    result = client.post("/api/menu/batch", json={"date": "2026-11-12", "slot": "lunch", "texts": ["Filetes de cerdo", "Patatas"]})
    assert result.status_code == 201
    entry_id = result.json()["entries"][0]["id"]
    assert len(client.get("/api/menu?week=2026-11-12").json()["entries"]) == 2
    assert client.get(f"/api/menu/{entry_id}/matches").json()["status"] == "exact"
    assert client.post(f"/api/menu/{entry_id}/shopping", json={}).status_code == 201
    shopping = client.get("/api/shopping").json()
    assert shopping["count"] == 1 and shopping["total_cents"] == 525
    assert shopping["groups"][0]["items"][0]["product_id"] == product_id
    quick = client.post("/api/shopping/quick-add", json={"name": "Producto nuevo rápido"})
    assert quick.status_code == 201 and quick.json()["created"] is True
    assert quick.json()["product"]["price_cents"] == 0
    assert quick.json()["product"]["category_name"] == "Sin especificar"
    assert client.get("/api/bootstrap").json()["uncategorized_count"] == 1
    assert client.get("/api/products/matches", params={"name": "Producto nuevo rápido"}).json()["status"] == "unique"
    copied = client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"})
    assert copied.status_code == 201 and copied.json()["copied"] == 2
    assert len(client.get("/api/menu?week=2026-11-19").json()["entries"]) == 2
    assert client.post("/api/menu/duplicate-week", json={"week": "2026-11-12"}).json()["copied"] == 0
    shopping = client.get("/api/shopping").json()
    assert client.get("/api/bootstrap").json()["version"] == "1.1.0"
    assert client.post(f"/api/products/{product_id}/price", json={"price_cents": 600}).status_code == 200
    line = next(i for g in client.get("/api/shopping").json()["groups"] for i in g["items"] if i["product_id"] == product_id)
    assert line["unit_price_cents"] == 600
    assert client.post(f"/api/shopping/items/{line['id']}/adjust", json={"delta": 1}).status_code == 200
    category = client.post("/api/categories", json={"name": "Categoría del ZIP"}).json()
    store = client.post("/api/supermarkets", json={"name": "Tienda del ZIP"}).json()
    payload = {"name": "Filetes de cerdo", "category_id": category["id"], "supermarket_id": store["id"], "unit": "kg", "price_cents": 650}
    assert client.put(f"/api/products/{product_id}", json=payload).status_code == 200
    line = next(i for g in client.get("/api/shopping").json()["groups"] for i in g["items"] if i["product_id"] == product_id)
    assert line["quantity"] == 2 and line["unit_price_cents"] == 650 and line["supermarket_id"] == store["id"]
    assert client.put(f"/api/categories/{category['id']}", json={"name": "Categoría editada del ZIP"}).status_code == 200
    assert client.put(f"/api/supermarkets/{store['id']}", json={"name": "Tienda editada del ZIP"}).status_code == 200
    assert client.delete(f"/api/categories/{category['id']}").status_code == 200
    assert client.delete(f"/api/supermarkets/{store['id']}").status_code == 200
    current = client.get(f"/api/products/{product_id}").json()
    assert current["category_name"] == "Sin especificar" and current["supermarket_name"] == "Sin especificar"
    assert any(h["supermarket_deleted"] for h in current["price_history"])
    assert client.delete(f"/api/products/{product_id}").json()["deleted"] is True
    assert client.get(f"/api/products/{product_id}").status_code == 404
    assert not any(h["product_id"] == product_id for h in client.get("/api/backup").json()["tables"]["price_history"])
    assert client.delete("/api/shopping").json()["count"] == 0
    assert client.get(f"/api/products/{quick.json()['product']['id']}").status_code == 200
    assert client.get("/api/backup").json()["version"] == 3
    assert client.get('/api/ha/status').json()['enabled'] is False
    assert client.get('/bridge/v1/health').status_code == 404
    assert client.post('/api/ha/config', json={'enabled': True}).status_code == 200
    key = client.post('/api/ha/token', json={}).json()['token']
    auth = {'Authorization': 'Bearer ' + key}
    assert client.get('/bridge/v1/health').status_code == 401
    assert client.get('/bridge/v1/health', headers=auth).json()['version'] == '1.1.0'
    assert client.get('/bridge/v1/backup', headers=auth).status_code == 404
    assert client.post('/bridge/v1/shopping/quick-add', headers=auth, json={'name': 'Alta desde HA'}).status_code == 201
    assert client.get('/api/shopping').json()['count'] == 1
    assert client.post('/api/ha/config', json={'enabled': False}).status_code == 200
    assert client.get('/bridge/v1/shopping', headers=auth).status_code == 404
    print(json.dumps({"installer_smoke": "passed", "v4_sync_crud_adjust_delete_clear": "passed", "copied_plates": copied.json()["copied"], "module": app.main.__file__}, ensure_ascii=False))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist-dir', type=Path, default=ROOT / 'build' / 'dist')
    parser.add_argument('--evidence-dir', type=Path, default=ROOT / 'build' / 'release-evidence')
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    installer = args.dist_dir / f"menu-compra-ha-{VERSION}-instalar.zip"
    sources = args.dist_dir / f"menu-compra-ha-{VERSION}.zip"
    integration = args.dist_dir / f"menu-compra-ha-{VERSION}-integracion.zip"
    with tempfile.TemporaryDirectory(prefix="menu-compra-release-", dir=os.environ.get("TMPDIR")) as directory:
        scratch = Path(directory)
        for archive_path, target, prefix in ((installer, scratch / "installer", ""), (sources, scratch / "sources", "menu-compra-ha/")):
            with zipfile.ZipFile(archive_path) as archive:
                assert archive.testzip() is None
                assert prefix + "menu_compra/Dockerfile" in archive.namelist()
                assert prefix + "menu_compra/config.yaml" in archive.namelist()
                assert not any(name.endswith((".sqlite3", ".db", ".pyc")) for name in archive.namelist())
                archive.extractall(target)
            print(json.dumps({"zip": str(archive_path), "dockerfile": "present", "crc": "ok", "sha256": sha256(archive_path.read_bytes()).hexdigest()}, ensure_ascii=False), flush=True)
        from tools.build_release import validate_ha_archive
        validate_ha_archive(integration)
        with zipfile.ZipFile(integration) as archive:
            archive.extractall(scratch / 'ha')
            for name in archive.namelist():
                if name.startswith('custom_components/') or name.startswith('blueprints/'):
                    assert (scratch / 'sources' / 'menu-compra-ha' / name).read_bytes() == (scratch / 'ha' / name).read_bytes()
        print(json.dumps({'zip': str(integration), 'crc': 'ok', 'manifest': '1.1.0', 'matches_source': True,
                          'sha256': sha256(integration.read_bytes()).hexdigest()}), flush=True)
        subprocess.run([sys.executable, "-c", SMOKE, str(scratch / "installer" / "menu_compra"), str(scratch / "probe-data")], check=True)
        subprocess.run([sys.executable, "-m", "pytest", "-q", '--junitxml', str((args.evidence_dir / 'pytest-extracted.xml').resolve())],
                       cwd=scratch / "sources" / "menu-compra-ha", check=True)
        if os.environ.get("MENU_COMPRA_VERIFY_UI") == "1":
            subprocess.run([sys.executable, str(ROOT / "tools" / "verify_ui_v5_1.py"),
                            "--app-dir", str(scratch / "installer" / "menu_compra"),
                            "--output", str((args.evidence_dir / "regresion").resolve())], check=True)
            subprocess.run([sys.executable, str(ROOT / "tools" / "verify_ui_v5_1.py"),
                            "--app-dir", str(scratch / "installer" / "menu_compra"),
                            "--script", str(ROOT / "tests" / "browser_v6.js"),
                            "--output", str((args.evidence_dir / "conexion-ha").resolve())], check=True)
            subprocess.run([sys.executable, str(ROOT / "tools" / "verify_ui_v5_1.py"),
                            "--app-dir", str(scratch / "installer" / "menu_compra"),
                            "--script", str(ROOT / "tests" / "browser_icon_v1.js"),
                            "--output", str((args.evidence_dir / "branding").resolve())], check=True)
            subprocess.run([sys.executable, str(ROOT / "tools" / "verify_ui_v5_1.py"),
                            "--app-dir", str(scratch / "installer" / "menu_compra"),
                            "--script", str(ROOT / "tests" / "browser_auto_setup.js"), '--supervisor-fixture',
                            "--output", str((args.evidence_dir / "enlace-automatico").resolve())], check=True)
    print("ZIP de app, integración HA y fuentes extraídos: verificados. No es una prueba de Docker/Supervisor/HA real.", flush=True)


if __name__ == "__main__":
    main()
