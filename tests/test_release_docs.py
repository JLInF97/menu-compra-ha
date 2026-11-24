"""Los enlaces de las guías distribuidas deben funcionar dentro de cada ZIP."""
from pathlib import PurePosixPath
import posixpath
import re
from urllib.parse import unquote, urlsplit
import zipfile

from tools.build_release import ROOT, build_archive, collect_files


def missing_links(archive):
    names = set(archive.namelist())
    missing = []
    for name in sorted(names):
        if not name.endswith('.md'):
            continue
        text = archive.read(name).decode('utf-8')
        for url in re.findall(r'\]\(([^)]+)\)', text):
            parts = urlsplit(url)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            target = posixpath.normpath(str(PurePosixPath(name).parent / unquote(parts.path)))
            if target not in names:
                missing.append((name, target))
    return missing


def test_installer_docs_have_no_missing_relative_files(tmp_path):
    target = tmp_path / 'app.zip'
    files = [p for p in collect_files() if p.is_relative_to(ROOT/'menu_compra')]
    build_archive(target, files)
    with zipfile.ZipFile(target) as archive:
        assert missing_links(archive) == []


def test_integration_docs_have_no_missing_relative_files(tmp_path):
    target = tmp_path / 'ha.zip'
    files = [p for p in collect_files() if p.is_relative_to(ROOT/'custom_components')
             or p.is_relative_to(ROOT/'blueprints') or p.name in {'HA_TELEGRAM.md','ENLACE_AUTOMATICO.md'} or p == ROOT/'LICENSE']
    build_archive(target, files, kind='ha')
    with zipfile.ZipFile(target) as archive:
        assert missing_links(archive) == []
        assert {'HA_TELEGRAM.md','ENLACE_AUTOMATICO.md','LICENSE'} <= set(archive.namelist())
