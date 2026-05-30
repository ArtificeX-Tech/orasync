from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ArchiveFormatError, ProjectLayoutError, UnsafeArchiveError
from .paths import (
    ORA_MIME,
    archive_name_for_path,
    atomic_replace_path,
    ensure_project_dir,
    is_project_metadata,
    project_payload_paths,
    remove_payload,
    validate_archive_name,
)
from .state import load_manifest, save_manifest


@dataclass
class FileFingerprint:
    path: str
    sha256: str
    mtime_ns: int
    size: int


@dataclass
class OraResult:
    project: str
    ora_path: str
    entries: list[str]
    fingerprint: FileFingerprint | None = None


def file_fingerprint(path: Path) -> FileFingerprint | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat_result = path.stat()
    return FileFingerprint(
        path=str(path),
        sha256=digest.hexdigest(),
        mtime_ns=stat_result.st_mtime_ns,
        size=stat_result.st_size,
    )


def _reject_symlink(info: zipfile.ZipInfo) -> None:
    mode = (info.external_attr >> 16) & 0o170000
    if mode and stat.S_ISLNK(mode):
        raise UnsafeArchiveError(f"Archive entry is a symlink: {info.filename}")


def _validated_infos(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos:
        raise ArchiveFormatError("ORA archive is empty")

    names: set[str] = set()
    for info in infos:
        name = validate_archive_name(info.filename)
        _reject_symlink(info)
        if name in names and not name.endswith("/"):
            raise UnsafeArchiveError(f"Archive contains duplicate entry: {name}")
        names.add(name)

    if "mimetype" not in names:
        raise ArchiveFormatError("ORA archive is missing mimetype")
    if "stack.xml" not in names:
        raise ArchiveFormatError("ORA archive is missing stack.xml")

    try:
        mime = archive.read("mimetype").decode("ascii").strip()
    except (UnicodeDecodeError, KeyError) as exc:
        raise ArchiveFormatError("ORA mimetype entry is invalid") from exc
    if mime != ORA_MIME:
        raise ArchiveFormatError(f"Unexpected ORA mimetype: {mime}")

    return infos


def _assert_import_target(project: Path, *, ora_path: Path | None, force: bool) -> None:
    payload = project_payload_paths(project, ora_path=ora_path)
    if not payload:
        return
    if load_manifest(project):
        return
    if force:
        return
    names = ", ".join(path.name for path in payload[:5])
    raise ProjectLayoutError(
        "Project contains existing files and is not yet managed by orasync. "
        f"Use --force to replace them. Existing entries include: {names}"
    )


def import_ora_archive(
    ora_path: str | os.PathLike[str],
    project: str | os.PathLike[str],
    *,
    force: bool = False,
) -> OraResult:
    source = Path(ora_path).expanduser().resolve()
    if not source.is_file():
        raise ArchiveFormatError(f"ORA file does not exist: {source}")

    root = ensure_project_dir(project)
    _assert_import_target(root, ora_path=source, force=force)

    with zipfile.ZipFile(source, "r") as archive:
        infos = _validated_infos(archive)
        remove_payload(root, ora_path=source)
        entries: list[str] = []
        for info in infos:
            name = validate_archive_name(info.filename)
            if name.endswith("/"):
                (root / name).mkdir(parents=True, exist_ok=True)
                continue
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as src, target.open("wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            entries.append(name)

    save_manifest(root, entries)
    return OraResult(
        project=str(root),
        ora_path=str(source),
        entries=entries,
        fingerprint=file_fingerprint(source),
    )


def _iter_export_files(project: Path, *, ora_path: Path | None) -> list[Path]:
    files: list[Path] = []
    for path in project.rglob("*"):
        if path.is_dir():
            continue
        if is_project_metadata(project, path, ora_path=ora_path):
            continue
        files.append(path)
    return sorted(files, key=lambda item: archive_name_for_path(project, item))


def export_ora_archive(
    project: str | os.PathLike[str],
    ora_path: str | os.PathLike[str],
) -> OraResult:
    root = ensure_project_dir(project)
    target = Path(ora_path).expanduser().resolve()
    files = _iter_export_files(root, ora_path=target)
    names = {archive_name_for_path(root, path) for path in files}
    if "mimetype" not in names:
        raise ArchiveFormatError("Project payload is missing mimetype")
    if "stack.xml" not in names:
        raise ArchiveFormatError("Project payload is missing stack.xml")

    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    entries: list[str] = []
    try:
        with zipfile.ZipFile(tmp, "w") as archive:
            mimetype_path = root / "mimetype"
            mime = mimetype_path.read_text(encoding="ascii").strip()
            if mime != ORA_MIME:
                raise ArchiveFormatError(f"Unexpected project mimetype: {mime}")
            archive.writestr(
                zipfile.ZipInfo("mimetype"),
                ORA_MIME,
                compress_type=zipfile.ZIP_STORED,
            )
            entries.append("mimetype")

            for path in files:
                name = archive_name_for_path(root, path)
                validate_archive_name(name)
                if name == "mimetype":
                    continue
                archive.write(path, name, compress_type=zipfile.ZIP_DEFLATED)
                entries.append(name)

        atomic_replace_path(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()

    save_manifest(root, entries)
    return OraResult(
        project=str(root),
        ora_path=str(target),
        entries=entries,
        fingerprint=file_fingerprint(target),
    )

