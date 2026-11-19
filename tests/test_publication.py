"""Metadatos públicos y licencia en los paquetes de app/integración."""
import json
import zipfile

import yaml

from tools.build_release import ROOT, REQUIRED, HA_REQUIRED, build_archive, collect_files


def test_mit_is_included_in_both_distributed_components():
    root_license = (ROOT / 'LICENSE').read_text(encoding='utf-8').strip()
    assert root_license.startswith('MIT License') and 'Copyright (c) 2026 Jesús' in root_license
    for name in ['menu_compra/LICENSE', 'custom_components/menu_compra/LICENSE']:
        assert (ROOT / name).read_text(encoding='utf-8').strip() == root_license
    assert 'menu_compra/LICENSE' in REQUIRED
    assert 'custom_components/menu_compra/LICENSE' in HA_REQUIRED
    assert 'COPY LICENSE ./LICENSE' in (ROOT / 'menu_compra/Dockerfile').read_text(encoding='utf-8')


def test_public_repository_metadata_and_documentation():
    repo = yaml.safe_load((ROOT / 'repository.yaml').read_text(encoding='utf-8'))
    url = repo['url']
    assert repo['name'] == 'Menú y Compra' and url == 'https://github.com/JLInF97/menu-compra-ha'
    config = yaml.safe_load((ROOT / 'menu_compra/config.yaml').read_text(encoding='utf-8'))
    assert config['url'] == url and config['slug'] == 'menu_compra'
    manifest = json.loads((ROOT / 'custom_components/menu_compra/manifest.json').read_text(encoding='utf-8'))
    assert manifest['documentation'] == url + '/blob/main/HA_TELEGRAM.md'
    assert manifest['issue_tracker'] == url + '/issues' and manifest['codeowners'] == ['@JLInF97']
    assert json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['license'] == 'MIT'


def test_source_collection_includes_repository_and_license():
    names = {file.relative_to(ROOT).as_posix() for file in collect_files()}
    assert {'LICENSE','repository.yaml','CONTRIBUTING.md'} <= names


def test_installer_archive_really_contains_mit(tmp_path):
    target = tmp_path / 'installer.zip'
    build_archive(target, [ROOT / name for name in REQUIRED])
    with zipfile.ZipFile(target) as archive:
        assert archive.read('menu_compra/LICENSE').decode('utf-8').strip() == (ROOT / 'LICENSE').read_text(encoding='utf-8').strip()
