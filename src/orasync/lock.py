from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .errors import LockError
from .paths import ensure_metadata_dir, lock_path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class ProjectLock:
    def __init__(self, project: Path, *, stale_after: float = 12 * 60 * 60):
        self.project = project
        self.path = lock_path(project)
        self.stale_after = stale_after
        self._owned = False

    def acquire(self) -> "ProjectLock":
        ensure_metadata_dir(self.project)
        data = {
            "pid": os.getpid(),
            "created_at": time.time(),
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self.path, flags)
        except FileExistsError:
            self._break_stale_lock()
            try:
                fd = os.open(self.path, flags)
            except FileExistsError as exc:
                raise LockError(f"Project is already locked: {self.project}") from exc

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self._owned = True
        return self

    def _break_stale_lock(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return
        pid = int(data.get("pid") or 0)
        created_at = float(data.get("created_at") or 0)
        is_stale = created_at and time.time() - created_at > self.stale_after
        if not _pid_alive(pid) or is_stale:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def release(self) -> None:
        if not self._owned:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._owned = False

    def __enter__(self) -> "ProjectLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

