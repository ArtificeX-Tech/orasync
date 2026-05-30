from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .sync import Event
from .sync import commit_push as _commit_push
from .sync import export_ora as _export_ora
from .sync import import_ora as _import_ora
from .sync import init_project as _init_project
from .sync import pull_export as _pull_export
from .sync import status as _status
from .sync import sync_once as _sync_once
from .sync import watch as _watch


def init_project(
    project: str | Path,
    *,
    ora_path: str | Path | None = None,
    remote_url: str | None = None,
    remote: str = "origin",
    branch: str = "main",
) -> Event:
    return _init_project(project, ora_path=ora_path, remote_url=remote_url, remote=remote, branch=branch)


def import_ora(
    ora_path: str | Path,
    project: str | Path,
    *,
    force: bool = False,
    remote_url: str | None = None,
    remote: str = "origin",
    branch: str = "main",
) -> Event:
    return _import_ora(
        ora_path,
        project,
        force=force,
        remote_url=remote_url,
        remote=remote,
        branch=branch,
    )


def export_ora(project: str | Path, ora_path: str | Path) -> Event:
    return _export_ora(project, ora_path)


def commit_push(
    project: str | Path,
    *,
    message: str,
    remote: str | None = None,
    branch: str | None = None,
) -> Event:
    return _commit_push(project, message=message, remote=remote, branch=branch)


def pull_export(
    project: str | Path,
    *,
    output: str | Path | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> Event:
    return _pull_export(project, output=output, remote=remote, branch=branch)


def sync_once(
    project: str | Path,
    *,
    ora_path: str | Path | None = None,
    message: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    force_import: bool = False,
) -> list[Event]:
    return _sync_once(
        project,
        ora_path=ora_path,
        message=message,
        remote=remote,
        branch=branch,
        force_import=force_import,
    )


def watch(
    project: str | Path,
    *,
    ora_path: str | Path | None = None,
    message: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    local_interval: float | None = None,
    remote_interval: float | None = None,
) -> Iterable[Event]:
    return _watch(
        project,
        ora_path=ora_path,
        message=message,
        remote=remote,
        branch=branch,
        local_interval=local_interval,
        remote_interval=remote_interval,
    )


def status(project: str | Path) -> Event:
    return _status(project)

