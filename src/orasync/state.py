from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import config_path, ensure_metadata_dir, manifest_path, state_path


@dataclass
class ProjectConfig:
    ora_path: str | None = None
    remote: str = "origin"
    branch: str = "main"
    local_interval: float = 2.0
    remote_interval: float = 5.0


@dataclass
class SyncState:
    ora_hash: str | None = None
    ora_mtime_ns: int | None = None
    last_commit: str | None = None
    last_event: str | None = None
    updated_at: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def load_config(project: Path) -> ProjectConfig:
    data = _read_json(config_path(project))
    return ProjectConfig(**{**asdict(ProjectConfig()), **data})


def save_config(project: Path, config: ProjectConfig) -> None:
    ensure_metadata_dir(project)
    _write_json(config_path(project), asdict(config))


def update_config(project: Path, **updates: Any) -> ProjectConfig:
    config = load_config(project)
    for key, value in updates.items():
        if value is not None and hasattr(config, key):
            setattr(config, key, value)
    save_config(project, config)
    return config


def load_state(project: Path) -> SyncState:
    data = _read_json(state_path(project))
    return SyncState(**{**asdict(SyncState()), **data})


def save_state(project: Path, state: SyncState) -> None:
    ensure_metadata_dir(project)
    state.updated_at = utc_now()
    _write_json(state_path(project), asdict(state))


def load_manifest(project: Path) -> list[str]:
    data = _read_json(manifest_path(project))
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return []
    return [str(entry) for entry in entries]


def save_manifest(project: Path, entries: list[str]) -> None:
    ensure_metadata_dir(project)
    _write_json(manifest_path(project), {"entries": sorted(set(entries))})

