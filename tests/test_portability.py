"""Regresión de rutas, recursos independientes y distribución de las pruebas."""
from pathlib import Path
import subprocess
import sys

from PIL import Image

from tools.build_release import ROOT, collect_files
from tools.check_portability import violations


def test_active_sources_are_not_tied_to_a_windows_user():
    assert violations() == []


def test_portability_scanner_detects_personal_paths(tmp_path):
    folder = tmp_path / 'tools'
    folder.mkdir()
    drive = chr(67) + ':'
    (folder / 'bad.py').write_text(f'p = "{drive}/Users/alguien/prueba"\n', encoding='utf-8')
    assert violations(tmp_path) == ['tools/bad.py:1']


def test_sources_include_ci_and_locked_dependencies():
    included = {file.relative_to(ROOT).as_posix() for file in collect_files()}
    assert {'package.json','package-lock.json','requirements-ci.lock','.gitattributes',
            '.github/workflows/ci.yml', 'tools/run_browser_tests.py', 'tests/browser_support.js',
            'artwork/logotipo-texto.png'} <= included
    assert not any(name.startswith(('node_modules/', 'build/', 'evidencias/')) for name in included)


def test_icons_are_reproducible_without_a_system_font(tmp_path):
    import shutil
    root = tmp_path / 'checkout'
    (root / 'tools').mkdir(parents=True)
    shutil.copy2(ROOT / 'tools/build_icons.py', root / 'tools/build_icons.py')
    shutil.copytree(ROOT / 'artwork', root / 'artwork')
    # No diseno/, directorios personales, fuentes ni archivos precompilados.
    subprocess.run([sys.executable, str(root / 'tools/build_icons.py')], check=True, capture_output=True)
    for relative in ['icon.png','logo.png','app/static/favicon.ico'] + [f'app/static/icons/icon-{n}.png' for n in [32,180,192,512]]:
        with Image.open(root / 'menu_compra' / relative) as actual, Image.open(ROOT / 'menu_compra' / relative) as expected:
            assert actual.format == expected.format and actual.size == expected.size
            # Compara píxeles, no el flujo comprimido: distintas versiones de zlib
            # pueden producir PNG binariamente distintos sin cambiar el diseño.
            assert actual.convert('RGBA').tobytes() == expected.convert('RGBA').tobytes()
            if expected.format == 'ICO':
                assert actual.ico.sizes() == expected.ico.sizes()
                for size in expected.ico.sizes():
                    assert actual.ico.getimage(size).convert('RGBA').tobytes() == expected.ico.getimage(size).convert('RGBA').tobytes()


def test_temp_data_respects_environment_without_a_personal_fallback(tmp_path):
    import os
    code = 'import test_ha_support; print(test_ha_support.SCRATCH)'
    env = dict(os.environ, MENU_COMPRA_TEST_TMPDIR=str(tmp_path),
               PYTHONPATH=os.pathsep.join([str(ROOT / 'tests'), str(ROOT / 'menu_compra')]))
    result = subprocess.run([sys.executable, '-c', code], env=env, check=True, capture_output=True, text=True)
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()
