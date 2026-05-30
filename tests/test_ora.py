from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from orasync.errors import ArchiveFormatError, UnsafeArchiveError
from orasync.ora import export_ora_archive, import_ora_archive


def make_ora(path: Path, *, layer_text: bytes = b"fake-png") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), "image/openraster", compress_type=zipfile.ZIP_STORED)
        archive.writestr("stack.xml", "<image><stack><layer src=\"data/layer.png\"/></stack></image>")
        archive.writestr("data/layer.png", layer_text)


def test_import_and_export_round_trip(tmp_path: Path):
    ora = tmp_path / "image.ora"
    project = tmp_path / "project"
    exported = tmp_path / "exported.ora"
    make_ora(ora)

    imported = import_ora_archive(ora, project)
    assert (project / "mimetype").read_text(encoding="ascii") == "image/openraster"
    assert (project / "stack.xml").exists()
    assert "data/layer.png" in imported.entries

    result = export_ora_archive(project, exported)
    assert result.fingerprint is not None
    with zipfile.ZipFile(exported, "r") as archive:
        infos = archive.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("data/layer.png") == b"fake-png"


def test_import_rejects_unsafe_paths(tmp_path: Path):
    ora = tmp_path / "bad.ora"
    with zipfile.ZipFile(ora, "w") as archive:
        archive.writestr("mimetype", "image/openraster")
        archive.writestr("stack.xml", "<image/>")
        archive.writestr("../escape.txt", "bad")

    with pytest.raises(UnsafeArchiveError):
        import_ora_archive(ora, tmp_path / "project")


def test_import_requires_openraster_mimetype(tmp_path: Path):
    ora = tmp_path / "bad.ora"
    with zipfile.ZipFile(ora, "w") as archive:
        archive.writestr("mimetype", "application/zip")
        archive.writestr("stack.xml", "<image/>")

    with pytest.raises(ArchiveFormatError):
        import_ora_archive(ora, tmp_path / "project")

