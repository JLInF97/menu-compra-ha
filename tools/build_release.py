"""Distribuye fuentes e instalador HA; valida los archivos DENTRO de cada ZIP."""
from hashlib import sha256
from pathlib import Path
import ast
import argparse
import json
from io import BytesIO
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
REQUIRED = [
    "menu_compra/config.yaml", "menu_compra/Dockerfile", "menu_compra/run.sh", "menu_compra/LICENSE",
    "menu_compra/requirements.txt", "menu_compra/app/__init__.py", "menu_compra/app/main.py", "menu_compra/app/db.py",
    "menu_compra/app/models.py", "menu_compra/app/backup.py",
    "menu_compra/app/ha_bridge.py",
    "menu_compra/app/static/index.html", "menu_compra/app/static/app.js", "menu_compra/app/static/style.css",
    "menu_compra/DOCS.md",
    "menu_compra/icon.png", "menu_compra/logo.png", "menu_compra/app/static/favicon.ico",
    "menu_compra/app/static/icons/icon-32.png", "menu_compra/app/static/icons/icon-180.png",
    "menu_compra/app/static/icons/icon-192.png", "menu_compra/app/static/icons/icon-512.png",
]
SUFFIXES = {".py", ".html", ".js", ".css", ".yaml", ".yml", ".txt", ".md", ".sh", ".toml", ".cmd", ".json", ".xml", ".png", ".ico"}
PRIVATE_NAMES = {"ha_bridge.json", "secrets.yaml", "options.json"}
HA_REQUIRED = ["custom_components/menu_compra/__init__.py", "custom_components/menu_compra/config_flow.py",
               "custom_components/menu_compra/manifest.json", "custom_components/menu_compra/services.yaml", "custom_components/menu_compra/LICENSE",
               "custom_components/menu_compra/strings.json", "custom_components/menu_compra/translations/es.json",
               "blueprints/automation/menu_compra/telegram.yaml", "HA_TELEGRAM.md"]


def collect_files(root=ROOT):
    files = []
    for folder in ("menu_compra", "custom_components", "blueprints", "artwork", "tests", "tools", ".github"):
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.name not in PRIVATE_NAMES and (path.suffix in SUFFIXES or path.name in {"Dockerfile", ".dockerignore", "LICENSE", "NOTICE"}) and "__pycache__" not in path.parts:
                files.append(path)
    for filename in ("README.md", "CONTRACT.md", "CHANGES-0.2.0.md", "CHANGES-0.3.0.md", "CHANGES-0.4.0.md", "CHANGES-0.5.0.md", "CHANGES-0.5.1.md", "CHANGES-0.6.0.md", "CHANGES-0.6.1.md", "CHANGES-1.0.0.md", "CIERRE-1.0.0.md", "HA_TELEGRAM.md", "requirements-dev.txt", "requirements-ci.lock", "package.json", "package-lock.json", "PRUEBAS.md", "PREPUBLICACION.md", "pyproject.toml", "iniciar-local.cmd", "VERIFICACION.md", ".gitignore", ".gitattributes", "repository.yaml", "CONTRIBUTING.md", "LICENSE", "LICENSE.md", "LICENSE.txt"):
        path = root / filename
        if path.exists():
            files.append(path)
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def validate_archive(path, prefix=""):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("El ZIP no supera la comprobación CRC")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("El ZIP contiene rutas duplicadas")
        missing = sorted(prefix + name for name in REQUIRED if prefix + name not in names)
        if missing:
            raise ValueError("Faltan archivos DENTRO del ZIP: " + ", ".join(missing))
        if any(name.endswith((".sqlite3", ".db", ".pyc")) or Path(name).name in PRIVATE_NAMES or "/.venv/" in name or ".." in Path(name).parts for name in names):
            raise ValueError("El ZIP contiene datos privados o rutas no admitidas")
        shell = archive.read(prefix + "menu_compra/run.sh")
        if b"\r" in shell or not shell.startswith(b"#!/bin/sh\n"):
            raise ValueError("run.sh debe conservar shebang y finales LF")
        dockerfile = archive.read(prefix + "menu_compra/Dockerfile").decode("utf-8")
        for instruction in ("FROM python:3.12-slim", "COPY requirements.txt", "COPY app", "COPY run.sh"):
            if instruction not in dockerfile:
                raise ValueError("Dockerfile incompleto: " + instruction)
        from PIL import Image
        icons = {'menu_compra/icon.png': (128,128), 'menu_compra/logo.png': (512,160),
                 **{f'menu_compra/app/static/icons/icon-{n}.png': (n,n) for n in (32,180,192,512)}}
        for name, size in icons.items():
            with Image.open(BytesIO(archive.read(prefix + name))) as image:
                if image.format != 'PNG' or image.size != size:
                    raise ValueError('Icono no válido DENTRO del ZIP: ' + name)
                image.verify()
        with Image.open(BytesIO(archive.read(prefix + 'menu_compra/app/static/favicon.ico'))) as image:
            if image.format != 'ICO' or not {(16,16),(32,32),(48,48),(64,64)} <= image.ico.sizes():
                raise ValueError('Favicon no válido DENTRO del ZIP')
        return len(names)


def validate_ha_archive(path, prefix="", expected_version=None):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP HA con error CRC")
        names = archive.namelist()
        missing = [prefix + name for name in HA_REQUIRED if prefix + name not in names]
        if missing:
            raise ValueError("Faltan archivos DENTRO del ZIP HA: " + ", ".join(missing))
        if len(names) != len(set(names)) or any(".." in Path(name).parts or Path(name).name in PRIVATE_NAMES or name.endswith((".pyc", ".db", ".sqlite3")) for name in names):
            raise ValueError("ZIP HA con datos privados o rutas inválidas")
        manifest = json.loads(archive.read(prefix + "custom_components/menu_compra/manifest.json"))
        if manifest.get("domain") != "menu_compra" or manifest.get("version") != (expected_version or VERSION) or manifest.get("config_flow") is not True:
            raise ValueError("Manifiesto HA no válido o versión incorrecta")
        return len(names)


def build_archive(output, files, root=ROOT, prefix="", kind="app"):
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(prefix + relative, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100755 if path.name == "run.sh" else 0o100644) << 16
            archive.writestr(info, path.read_bytes())
    count = (validate_ha_archive if kind == "ha" else validate_archive)(output, prefix)
    return {"archive": str(output), "files": count, "bytes": output.stat().st_size,
            "sha256": sha256(output.read_bytes()).hexdigest(), "crc": "ok", "dockerfile_in_zip": kind != "ha", "contains_user_data": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build' / 'dist',
                        help='Destino nuevo de paquetes; por defecto build/dist, no releases previas de dist/.')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'custom_components/menu_compra/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != VERSION:
        raise SystemExit('Versiones de app/integración distintas: utiliza tools/build_telegram_update.py; no se sobrescriben ZIP anteriores.')
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            raise SystemExit("Falta un archivo fuente obligatorio: " + relative)
    files = collect_files()
    for path in files:
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    source = build_archive(args.output_dir / f"menu-compra-ha-{VERSION}.zip", files, prefix="menu-compra-ha/")
    addon_files = [path for path in files if path.is_relative_to(ROOT / "menu_compra")]
    installer = build_archive(args.output_dir / f"menu-compra-ha-{VERSION}-instalar.zip", addon_files)
    ha_files = [path for path in files if path.is_relative_to(ROOT / "custom_components") or path.is_relative_to(ROOT / "blueprints") or path.name == "HA_TELEGRAM.md"]
    ha = build_archive(args.output_dir / f"menu-compra-ha-{VERSION}-integracion.zip", ha_files, kind="ha")
    print(json.dumps({"version": VERSION, "artifacts": [installer, ha, source]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
