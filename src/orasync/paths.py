from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from .errors import ProjectLayoutError, UnsafeArchiveError

METADATA_DIR = ".orasync"
CONFIG_FILE = "config.json"
STATE_FILE = "state.json"
MANIFEST_FILE = "manifest.json"
LOCK_FILE = "lock"
ORA_MIME = "image/openraster"

PROJECT_EXCLUDES = {
    ".git",
    METADATA_DIR,
    ".gitignore",
    ".gitattributes",
    ".DS_Store",
    "Thumbs.db",
}


def looks_like_remote_url(value: str | os.PathLike[str]) -> bool:
    text = os.fspath(value)
    if "://" in text:
        return True
    if text.startswith("git@") and ":" in text:
        return True
    return False


def resolve_project(project: str | os.PathLike[str]) -> Path:
    if looks_like_remote_url(project):
        raise ProjectLayoutError(
            "Project must be a local Git working tree path, not a remote URL. "
            "Use --remote-url with `orasync init` to configure the remote."
        )
    return Path(project).expanduser().resolve()


def ensure_project_dir(project: str | os.PathLike[str]) -> Path:
    root = resolve_project(project)
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ProjectLayoutError(f"Project path is not a directory: {root}")
    return root


def metadata_dir(project: Path) -> Path:
    return project / METADATA_DIR


def config_path(project: Path) -> Path:
    return metadata_dir(project) / CONFIG_FILE


def state_path(project: Path) -> Path:
    return metadata_dir(project) / STATE_FILE


def manifest_path(project: Path) -> Path:
    return metadata_dir(project) / MANIFEST_FILE


def lock_path(project: Path) -> Path:
    return metadata_dir(project) / LOCK_FILE


def ensure_metadata_dir(project: Path) -> Path:
    path = metadata_dir(project)
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_archive_name(name: str) -> str:
    if not name:
        raise UnsafeArchiveError("Archive entry has an empty name")
    if "\\" in name:
        raise UnsafeArchiveError(f"Archive entry uses backslashes: {name}")

    pure = PurePosixPath(name)
    if pure.is_absolute():
        raise UnsafeArchiveError(f"Archive entry is absolute: {name}")
    if pure.parts and pure.parts[0].endswith(":"):
        raise UnsafeArchiveError(f"Archive entry looks like a drive path: {name}")
    for part in pure.parts:
        if part in ("", ".", ".."):
            raise UnsafeArchiveError(f"Archive entry is unsafe: {name}")
    return pure.as_posix()


def archive_name_for_path(project: Path, path: Path) -> str:
    rel = path.relative_to(project)
    return rel.as_posix()


def is_project_metadata(project: Path, path: Path, *, ora_path: Path | None = None) -> bool:
    rel = path.relative_to(project)
    if not rel.parts:
        return False
    if rel.parts[0] in PROJECT_EXCLUDES:
        return True
    if ora_path is not None:
        try:
            if path.resolve() == ora_path.resolve():
                return True
        except FileNotFoundError:
            return False
    return False


def project_payload_paths(project: Path, *, ora_path: Path | None = None) -> list[Path]:
    if not project.exists():
        return []
    payload: list[Path] = []
    for child in project.iterdir():
        if is_project_metadata(project, child, ora_path=ora_path):
            continue
        payload.append(child)
    return payload


def remove_payload(project: Path, *, ora_path: Path | None = None) -> None:
    for child in project_payload_paths(project, ora_path=ora_path):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_replace_path(temp_path: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temp_path, target)
