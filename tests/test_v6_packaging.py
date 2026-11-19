"""Exclusión de secretos y estructura del paquete HA, con fixtures explícitas."""
import json
from pathlib import Path
import zipfile

import pytest

from tools.build_release import HA_REQUIRED, PRIVATE_NAMES, VERSION, collect_files, validate_ha_archive


def test_collect_files_excludes_private_config(tmp_path):
    folder = tmp_path / 'menu_compra' / 'app'
    folder.mkdir(parents=True)
    for name in PRIVATE_NAMES:
        (folder / name).write_text('test fixture: never distribute', encoding='utf-8')
    (folder / 'ha_bridge.py').write_text('# module fixture\n', encoding='utf-8')
    collected = collect_files(tmp_path)
    assert collected == [folder / 'ha_bridge.py']


def fixture_archive(tmp_path, omitted=None, bad_version=False, private=None):
    result = tmp_path / 'fixture-ha.zip'
    with zipfile.ZipFile(result, 'w') as archive:
        for name in HA_REQUIRED:
            if name == omitted:
                continue
            text = json.dumps({'domain': 'menu_compra', 'version': '0.0.0' if bad_version else VERSION, 'config_flow': True}) if name.endswith('manifest.json') else '{}'
            archive.writestr(name, text)
        if private:
            archive.writestr('custom_components/menu_compra/' + private, 'private fixture')
    return result


@pytest.mark.parametrize('omitted', HA_REQUIRED)
def test_ha_archive_requires_each_installed_file(tmp_path, omitted):
    with pytest.raises(ValueError, match='Faltan archivos DENTRO'):
        validate_ha_archive(fixture_archive(tmp_path, omitted=omitted))


def test_ha_archive_checks_manifest_version(tmp_path):
    with pytest.raises(ValueError, match='Manifiesto'):
        validate_ha_archive(fixture_archive(tmp_path, bad_version=True))


@pytest.mark.parametrize('private', sorted(PRIVATE_NAMES))
def test_ha_archive_rejects_private_files(tmp_path, private):
    with pytest.raises(ValueError, match='privados'):
        validate_ha_archive(fixture_archive(tmp_path, private=private))


def test_ha_archive_accepts_correct_required_fixture(tmp_path):
    assert validate_ha_archive(fixture_archive(tmp_path)) == len(HA_REQUIRED)


def test_expected_ha_paths_are_config_relative():
    assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in HA_REQUIRED)
