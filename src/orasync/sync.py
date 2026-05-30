from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .errors import GitError, LockError, OrasyncError
from .gitrepo import GitRepo
from .lock import ProjectLock
from .ora import export_ora_archive, file_fingerprint, import_ora_archive
from .paths import ensure_metadata_dir, ensure_project_dir, resolve_project
from .state import (
    ProjectConfig,
    SyncState,
    load_config,
    load_state,
    save_config,
    save_state,
    update_config,
)


@dataclass
class Event:
    event: str
    message: str
    project: str
    ora_path: str | None = None
    data: dict | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        payload["data"] = payload["data"] or {}
        return json.dumps(payload, sort_keys=True)


Emit = Callable[[Event], None]


def _event(project: Path, name: str, message: str, *, ora_path: Path | None = None, **data) -> Event:
    return Event(name, message, str(project), str(ora_path) if ora_path else None, data or None)


def _configure_git(repo: GitRepo, *, remote_url: str | None, remote: str, branch: str) -> None:
    repo.ensure_repo(branch=branch)
    if remote_url:
        repo.set_remote(remote_url, remote=remote)


def _write_gitignore(project: Path) -> None:
    gitignore = project / ".gitignore"
    entry = ".orasync/"
    if gitignore.exists():
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        if entry in lines:
            return
        text = gitignore.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"{entry}\n"
    else:
        text = f"{entry}\n"
    gitignore.write_text(text, encoding="utf-8")


def init_project(
    project: str | Path,
    *,
    ora_path: str | Path | None = None,
    remote_url: str | None = None,
    remote: str = "origin",
    branch: str = "main",
) -> Event:
    root = ensure_project_dir(project)
    ensure_metadata_dir(root)
    repo = GitRepo(root)
    _configure_git(repo, remote_url=remote_url, remote=remote, branch=branch)
    _write_gitignore(root)

    config = update_config(
        root,
        ora_path=str(Path(ora_path).expanduser().resolve()) if ora_path else None,
        remote=remote,
        branch=branch,
    )
    return _event(
        root,
        "initialized",
        "Project initialized",
        ora_path=Path(config.ora_path) if config.ora_path else None,
        remote=remote,
        branch=branch,
        remote_url=repo.remote_url(remote),
    )


def import_ora(
    ora_path: str | Path,
    project: str | Path,
    *,
    force: bool = False,
    remote_url: str | None = None,
    remote: str = "origin",
    branch: str = "main",
) -> Event:
    root = ensure_project_dir(project)
    source = Path(ora_path).expanduser().resolve()
    with ProjectLock(root):
        init_project(root, ora_path=source, remote_url=remote_url, remote=remote, branch=branch)
        result = import_ora_archive(source, root, force=force)
        state = load_state(root)
        if result.fingerprint:
            state.ora_hash = result.fingerprint.sha256
            state.ora_mtime_ns = result.fingerprint.mtime_ns
        state.last_event = "imported"
        save_state(root, state)
    return _event(root, "imported", "ORA imported", ora_path=source, entries=len(result.entries))


def export_ora(project: str | Path, ora_path: str | Path) -> Event:
    root = ensure_project_dir(project)
    target = Path(ora_path).expanduser().resolve()
    with ProjectLock(root):
        result = export_ora_archive(root, target)
        update_config(root, ora_path=str(target))
        state = load_state(root)
        if result.fingerprint:
            state.ora_hash = result.fingerprint.sha256
            state.ora_mtime_ns = result.fingerprint.mtime_ns
        state.last_event = "exported"
        save_state(root, state)
    return _event(root, "exported", "ORA exported", ora_path=target, entries=len(result.entries))


def commit_push(
    project: str | Path,
    *,
    message: str,
    remote: str | None = None,
    branch: str | None = None,
) -> Event:
    root = ensure_project_dir(project)
    config = load_config(root)
    remote = remote or config.remote
    branch = branch or config.branch
    with ProjectLock(root):
        repo = GitRepo(root)
        repo.ensure_repo(branch=branch)
        committed = repo.commit_if_needed(message)
        repo.push(remote=remote, branch=branch)
        state = load_state(root)
        state.last_commit = repo.head()
        state.last_event = "pushed" if committed else "no-change"
        save_state(root, state)
    name = "pushed" if committed else "no-change"
    message_text = "Changes committed and pushed" if committed else "No Git changes to commit"
    return _event(root, name, message_text, remote=remote, branch=branch)


def apply_remote(project: Path, *, ora_path: Path, remote: str, branch: str) -> Event | None:
    repo = GitRepo(project)
    if not repo.fetch(remote):
        return _event(project, "remote-missing", "No Git remote is configured", ora_path=ora_path, remote=remote)
    if not repo.remote_changed(remote=remote, branch=branch):
        return None
    repo.checkout_remote(remote=remote, branch=branch)
    result = export_ora_archive(project, ora_path)
    state = load_state(project)
    if result.fingerprint:
        state.ora_hash = result.fingerprint.sha256
        state.ora_mtime_ns = result.fingerprint.mtime_ns
    state.last_commit = repo.head()
    state.last_event = "remote-applied"
    save_state(project, state)
    return _event(
        project,
        "remote-applied",
        "Remote changes exported to ORA",
        ora_path=ora_path,
        remote=remote,
        branch=branch,
        entries=len(result.entries),
    )


def pull_export(
    project: str | Path,
    *,
    output: str | Path | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> Event:
    root = ensure_project_dir(project)
    config = load_config(root)
    if output is None and not config.ora_path:
        raise OrasyncError("No output ORA path was provided or configured")
    target = Path(output or config.ora_path).expanduser()
    target = target.resolve()
    remote = remote or config.remote
    branch = branch or config.branch
    with ProjectLock(root):
        event = apply_remote(root, ora_path=target, remote=remote, branch=branch)
        if event is not None:
            return event
        exported = export_ora_archive(root, target)
        state = load_state(root)
        if exported.fingerprint:
            state.ora_hash = exported.fingerprint.sha256
            state.ora_mtime_ns = exported.fingerprint.mtime_ns
        state.last_event = "exported"
        save_state(root, state)
    return _event(root, "exported", "No remote changes; ORA exported", ora_path=target)


def _local_changed(ora_path: Path, state: SyncState) -> bool:
    fingerprint = file_fingerprint(ora_path)
    if fingerprint is None:
        return False
    return fingerprint.sha256 != state.ora_hash


def sync_once(
    project: str | Path,
    *,
    ora_path: str | Path | None = None,
    message: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    force_import: bool = False,
) -> list[Event]:
    root = ensure_project_dir(project)
    config = load_config(root)
    if ora_path:
        config.ora_path = str(Path(ora_path).expanduser().resolve())
    if remote:
        config.remote = remote
    if branch:
        config.branch = branch
    if not config.ora_path:
        raise OrasyncError("No ORA path was provided or configured")
    save_config(root, config)

    target = Path(config.ora_path).expanduser().resolve()
    message = message or f"orasync: sync {target.name}"
    events: list[Event] = []

    with ProjectLock(root):
        repo = GitRepo(root)
        repo.ensure_repo(branch=config.branch)
        state = load_state(root)

        local_changed = _local_changed(target, state)
        repo_dirty = repo.is_dirty()
        if local_changed or repo_dirty:
            result = None
            if local_changed:
                result = import_ora_archive(target, root, force=force_import)
            committed = repo.commit_if_needed(message)
            try:
                repo.push(remote=config.remote, branch=config.branch)
            except GitError:
                remote_event = apply_remote(root, ora_path=target, remote=config.remote, branch=config.branch)
                if remote_event is not None:
                    events.append(remote_event)
                    return events
                raise
            state = load_state(root)
            if result and result.fingerprint:
                state.ora_hash = result.fingerprint.sha256
                state.ora_mtime_ns = result.fingerprint.mtime_ns
            state.last_commit = repo.head()
            has_remote = repo.has_remote(config.remote)
            state.last_event = "local-pushed" if committed and has_remote else "local-committed"
            save_state(root, state)
            events.append(
                _event(
                    root,
                    "local-pushed" if committed and has_remote else "local-committed",
                    "Local changes committed and pushed"
                    if committed and has_remote
                    else "Local changes committed",
                    ora_path=target,
                    remote=config.remote,
                    branch=config.branch,
                )
            )

        remote_event = apply_remote(root, ora_path=target, remote=config.remote, branch=config.branch)
        if remote_event is not None:
            events.append(remote_event)

    if not events:
        events.append(_event(root, "idle", "No changes detected", ora_path=target))
    return events


def watch(
    project: str | Path,
    *,
    ora_path: str | Path | None = None,
    message: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    local_interval: float | None = None,
    remote_interval: float | None = None,
    emit: Emit | None = None,
    stop_after: int | None = None,
) -> Iterable[Event]:
    root = resolve_project(project)
    config = load_config(root)
    if ora_path:
        config.ora_path = str(Path(ora_path).expanduser().resolve())
    if remote:
        config.remote = remote
    if branch:
        config.branch = branch
    if local_interval is not None:
        config.local_interval = local_interval
    if remote_interval is not None:
        config.remote_interval = remote_interval
    if not config.ora_path:
        raise OrasyncError("No ORA path was provided or configured")
    save_config(root, config)

    next_remote = 0.0
    count = 0
    start_event = _event(root, "watch-started", "Watcher started", ora_path=Path(config.ora_path))
    if emit:
        emit(start_event)
    yield start_event

    while True:
        remote_due = time.monotonic() >= next_remote
        try:
            if remote_due:
                next_remote = time.monotonic() + config.remote_interval
            state = load_state(root)
            local_changed = _local_changed(Path(config.ora_path), state)
            if local_changed or remote_due:
                for event in sync_once(
                    root,
                    ora_path=config.ora_path,
                    message=message,
                    remote=config.remote,
                    branch=config.branch,
                    force_import=True,
                ):
                    if event.event == "idle" and not remote_due:
                        continue
                    if emit:
                        emit(event)
                    yield event
        except LockError:
            pass
        except OrasyncError as exc:
            event = _event(root, "error", str(exc), ora_path=Path(config.ora_path), error_type=type(exc).__name__)
            if emit:
                emit(event)
            yield event

        count += 1
        if stop_after is not None and count >= stop_after:
            break
        time.sleep(config.local_interval)


def status(project: str | Path) -> Event:
    root = ensure_project_dir(project)
    config = load_config(root)
    state = load_state(root)
    repo = GitRepo(root)
    remote_url = repo.remote_url(config.remote) if (root / ".git").exists() else None
    return _event(
        root,
        "status",
        "Project status",
        ora_path=Path(config.ora_path) if config.ora_path else None,
        config=asdict(config),
        state=asdict(state),
        remote_url=remote_url,
        dirty=repo.is_dirty() if (root / ".git").exists() else None,
    )
