from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

from orasync.sync import import_ora, init_project, pull_export, sync_once


def run_git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def configure_identity(path: Path) -> None:
    run_git(path, "config", "user.email", "orasync@example.invalid")
    run_git(path, "config", "user.name", "Orasync Test")


def make_ora(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), "image/openraster", compress_type=zipfile.ZIP_STORED)
        archive.writestr("stack.xml", f"<image><stack><layer src=\"data/{text}.txt\"/></stack></image>")
        archive.writestr(f"data/{text}.txt", text)


def test_init_import_commit_push_and_pull_export(tmp_path: Path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", remote], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    ora_a = tmp_path / "a.ora"
    ora_b = tmp_path / "b.ora"
    make_ora(ora_a, "first")

    init_project(repo_a, ora_path=ora_a, remote_url=str(remote), branch="main")
    configure_identity(repo_a)
    import_ora(ora_a, repo_a, force=True)
    events = sync_once(repo_a, ora_path=ora_a, message="first", force_import=True)
    assert events[-1].event in {"local-pushed", "local-imported", "idle"}

    subprocess.run(["git", "clone", str(remote), str(repo_b)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    configure_identity(repo_b)
    init_project(repo_b, ora_path=ora_b, remote_url=str(remote), branch="main")
    event = pull_export(repo_b, output=ora_b)
    assert event.event in {"remote-applied", "exported"}
    with zipfile.ZipFile(ora_b, "r") as archive:
        assert archive.read("data/first.txt") == b"first"

    make_ora(ora_a, "second")
    events = sync_once(repo_a, ora_path=ora_a, message="second", force_import=True)
    assert any(event.event == "local-pushed" for event in events)

    event = pull_export(repo_b, output=ora_b)
    assert event.event == "remote-applied"
    with zipfile.ZipFile(ora_b, "r") as archive:
        assert archive.read("data/second.txt") == b"second"

