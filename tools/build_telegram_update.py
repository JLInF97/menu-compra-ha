"""Empaqueta SOLO la integración 0.6.1; conserva app/ZIP 0.6.0.

--verify ejecuta la suite sobre la integración realmente extraída, con app real.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_release import PRIVATE_NAMES, validate_ha_archive  # noqa: E402

VERSION = '0.6.1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'custom_components/menu_compra/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != VERSION:
        raise SystemExit('Herramienta histórica 0.6.1; no se sobrescriben paquetes anteriores. Usa build_release.py para el cierre estable.')
    files = [p for p in (ROOT / 'custom_components' / 'menu_compra').rglob('*')
             if p.is_file() and not p.is_symlink() and p.suffix in {'.py', '.json', '.yaml', '.md'}
             and '__pycache__' not in p.parts and p.name not in PRIVATE_NAMES]
    files += [ROOT / 'blueprints/automation/menu_compra/telegram.yaml', ROOT / 'HA_TELEGRAM.md',
              ROOT / 'CHANGES-0.6.1.md', ROOT / 'VERIFICACION-0.6.1.md']
    output = ROOT / 'dist' / f'menu-compra-ha-{VERSION}-integracion.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in sorted(files):
            info = zipfile.ZipInfo(p.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, p.read_bytes())
    count = validate_ha_archive(output, expected_version=VERSION)
    if args.verify:
        scratch_root = os.environ.get('TMPDIR')
        if not scratch_root:
            raise SystemExit('Indica TMPDIR explícito para los datos y extracción de prueba')
        with tempfile.TemporaryDirectory(prefix='mc-telegram-061-', dir=scratch_root) as directory:
            target = Path(directory)
            with zipfile.ZipFile(output) as archive:
                archive.extractall(target)
                for name in archive.namelist():
                    assert (target / name).read_bytes() == (ROOT / name).read_bytes()
            env = dict(os.environ, MENU_COMPRA_TEST_COMPONENT_DIR=str(target / 'custom_components/menu_compra'),
                       PYTHONDONTWRITEBYTECODE='1')
            subprocess.run([sys.executable, '-m', 'pytest', '-q',
                            '--junitxml=' + str(ROOT / 'evidencias/0.6.1/zip-tests.xml')],
                           cwd=ROOT, env=env, check=True)
    digest = sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    print(json.dumps({'archive': str(output.resolve()), 'integration_version': VERSION, 'app_version': '0.6.0',
                      'files': count, 'crc': 'ok', 'sha256': digest, 'extracted_tests': args.verify,
                      'requires_app_update': False, 'real_home_assistant_tested': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
