"""Regresión: Dockerfile sin extensión debe viajar DENTRO del instalador."""
from pathlib import Path
import zipfile

import pytest

from tools.build_release import ROOT, REQUIRED, build_archive, collect_files, validate_archive


def test_extensionless_dockerfile_is_collected():
    assert ROOT / "menu_compra/Dockerfile" in collect_files()


def test_missing_dockerfile_inside_zip_is_rejected_even_if_source_exists(tmp_path):
    assert (ROOT / "menu_compra/Dockerfile").is_file()
    output = tmp_path / "roto.zip"
    with zipfile.ZipFile(output, "w") as archive:
        for relative in REQUIRED:
            if Path(relative).name != "Dockerfile":
                archive.write(ROOT / relative, relative)
    with pytest.raises(ValueError, match="DENTRO.*Dockerfile"):
        validate_archive(output)


def test_installer_zip_contains_required_files_at_exact_root(tmp_path):
    files = [ROOT / relative for relative in REQUIRED]
    output = tmp_path / "instalar.zip"
    result = build_archive(output, files)
    assert result["dockerfile_in_zip"] is True
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert set(REQUIRED) <= names
        assert "menu_compra/Dockerfile" in names
        assert "menu_compra/config.yaml" in names
        assert all(name.startswith("menu_compra/") for name in names)
        assert archive.getinfo("menu_compra/run.sh").external_attr >> 16 & 0o111


def test_source_archive_checks_required_paths_with_prefix(tmp_path):
    output = tmp_path / "fuentes.zip"
    build_archive(output, [ROOT / relative for relative in REQUIRED], prefix="menu-compra-ha/")
    assert validate_archive(output, "menu-compra-ha/") == len(REQUIRED)
