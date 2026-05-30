from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import DirtyRepoError, GitError


@dataclass
class GitResult:
    args: list[str]
    stdout: str
    stderr: str
    returncode: int


class GitRepo:
    def __init__(self, project: Path):
        self.project = project

    def run(self, *args: str, check: bool = True) -> GitResult:
        command = ["git", *args]
        proc = subprocess.run(
            command,
            cwd=self.project,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result = GitResult(command, proc.stdout, proc.stderr, proc.returncode)
        if check and proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or "Git command failed"
            raise GitError(
                message,
                command=command,
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        return result

    def ensure_repo(self, *, branch: str = "main") -> None:
        if not (self.project / ".git").exists():
            self.run("init", "-b", branch)
        elif not self.current_branch(check=False):
            self.run("checkout", "-B", branch)

    def current_branch(self, *, check: bool = True) -> str | None:
        result = self.run("branch", "--show-current", check=False)
        branch = result.stdout.strip()
        if branch:
            return branch
        if check:
            raise GitError("Could not determine current Git branch")
        return None

    def remote_url(self, remote: str = "origin") -> str | None:
        result = self.run("remote", "get-url", remote, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def set_remote(self, url: str, *, remote: str = "origin") -> None:
        if self.remote_url(remote):
            self.run("remote", "set-url", remote, url)
        else:
            self.run("remote", "add", remote, url)

    def has_remote(self, remote: str = "origin") -> bool:
        return self.remote_url(remote) is not None

    def status_porcelain(self) -> str:
        return self.run("status", "--porcelain").stdout

    def is_dirty(self) -> bool:
        return bool(self.status_porcelain().strip())

    def require_clean(self) -> None:
        status = self.status_porcelain()
        if status.strip():
            raise DirtyRepoError("Git working tree is dirty", stdout=status)

    def add_all(self) -> None:
        self.run("add", "-A")

    def commit_if_needed(self, message: str) -> bool:
        self.add_all()
        if not self.is_dirty():
            return False
        self.run("commit", "-m", message)
        return True

    def head(self) -> str | None:
        result = self.run("rev-parse", "--verify", "HEAD", check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def fetch(self, remote: str = "origin") -> bool:
        if not self.has_remote(remote):
            return False
        self.run("fetch", remote)
        return True

    def remote_head(self, *, remote: str = "origin", branch: str = "main") -> str | None:
        result = self.run("rev-parse", "--verify", f"{remote}/{branch}", check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def remote_changed(self, *, remote: str = "origin", branch: str = "main") -> bool:
        remote_sha = self.remote_head(remote=remote, branch=branch)
        if remote_sha is None:
            return False
        return self.head() != remote_sha

    def checkout_remote(self, *, remote: str = "origin", branch: str = "main") -> None:
        self.run("checkout", "-B", branch)
        self.run("reset", "--hard", f"{remote}/{branch}")

    def push(self, *, remote: str = "origin", branch: str = "main") -> None:
        if not self.has_remote(remote):
            return
        self.run("push", "-u", remote, branch)

