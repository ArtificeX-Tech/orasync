from __future__ import annotations

import argparse
import sys
from typing import Iterable

from . import __version__
from .errors import GitError, OrasyncError
from .sync import (
    Event,
    commit_push,
    export_ora,
    import_ora,
    init_project,
    pull_export,
    status,
    sync_once,
    watch,
)


def _print_events(events: Iterable[Event], *, json_output: bool) -> None:
    for event in events:
        if json_output:
            print(event.to_json(), flush=True)
        else:
            suffix = f" ({event.ora_path})" if event.ora_path else ""
            print(f"{event.event}: {event.message}{suffix}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orasync")
    parser.add_argument("--version", action="version", version=f"orasync {__version__}")
    parser.add_argument("--json", action="store_true", help="print JSON lines")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="initialize or bind a project repo")
    init.add_argument("project")
    init.add_argument("--ora")
    init.add_argument("--remote-url", "--remote", dest="remote_url")
    init.add_argument("--remote-name", default="origin")
    init.add_argument("--branch", default="main")

    import_cmd = subparsers.add_parser("import", aliases=["import-ora"], help="import an ORA into a project repo")
    import_cmd.add_argument("ora")
    import_cmd.add_argument("project")
    import_cmd.add_argument("--force", action="store_true")
    import_cmd.add_argument("--remote-url", "--remote", dest="remote_url")
    import_cmd.add_argument("--remote-name", default="origin")
    import_cmd.add_argument("--branch", default="main")

    export = subparsers.add_parser("export", aliases=["export-ora"], help="export a project repo to ORA")
    export.add_argument("project")
    export.add_argument("ora")

    commit = subparsers.add_parser("commit-push", help="commit and push project changes")
    commit.add_argument("project")
    commit.add_argument("-m", "--message", required=True)
    commit.add_argument("--remote-name")
    commit.add_argument("--branch")

    pull = subparsers.add_parser("pull-export", help="apply remote changes and export ORA")
    pull.add_argument("project")
    pull.add_argument("--output")
    pull.add_argument("--remote-name")
    pull.add_argument("--branch")

    sync = subparsers.add_parser("sync", help="run one local/remote sync pass")
    sync.add_argument("project")
    sync.add_argument("--ora")
    sync.add_argument("-m", "--message")
    sync.add_argument("--remote-name")
    sync.add_argument("--branch")
    sync.add_argument("--force-import", action="store_true")

    watch_cmd = subparsers.add_parser("watch", help="watch local ORA and remote Git changes")
    watch_cmd.add_argument("project")
    watch_cmd.add_argument("--ora")
    watch_cmd.add_argument("-m", "--message")
    watch_cmd.add_argument("--remote-name")
    watch_cmd.add_argument("--branch")
    watch_cmd.add_argument("--local-interval", type=float)
    watch_cmd.add_argument("--remote-interval", type=float)

    status_cmd = subparsers.add_parser("status", help="show project status")
    status_cmd.add_argument("project")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            event = init_project(
                args.project,
                ora_path=args.ora,
                remote_url=args.remote_url,
                remote=args.remote_name,
                branch=args.branch,
            )
            _print_events([event], json_output=args.json)
        elif args.command in ("import", "import-ora"):
            event = import_ora(
                args.ora,
                args.project,
                force=args.force,
                remote_url=args.remote_url,
                remote=args.remote_name,
                branch=args.branch,
            )
            _print_events([event], json_output=args.json)
        elif args.command in ("export", "export-ora"):
            _print_events([export_ora(args.project, args.ora)], json_output=args.json)
        elif args.command == "commit-push":
            _print_events(
                [
                    commit_push(
                        args.project,
                        message=args.message,
                        remote=args.remote_name,
                        branch=args.branch,
                    )
                ],
                json_output=args.json,
            )
        elif args.command == "pull-export":
            _print_events(
                [pull_export(args.project, output=args.output, remote=args.remote_name, branch=args.branch)],
                json_output=args.json,
            )
        elif args.command == "sync":
            _print_events(
                sync_once(
                    args.project,
                    ora_path=args.ora,
                    message=args.message,
                    remote=args.remote_name,
                    branch=args.branch,
                    force_import=args.force_import,
                ),
                json_output=args.json,
            )
        elif args.command == "watch":
            for _event in watch(
                args.project,
                ora_path=args.ora,
                message=args.message,
                remote=args.remote_name,
                branch=args.branch,
                local_interval=args.local_interval,
                remote_interval=args.remote_interval,
                emit=lambda event: _print_events([event], json_output=args.json),
            ):
                pass
        elif args.command == "status":
            _print_events([status(args.project)], json_output=args.json)
        return 0
    except KeyboardInterrupt:
        return 130
    except GitError as exc:
        if args.json:
            event = Event("error", str(exc), project="", data={"error_type": type(exc).__name__, "stderr": exc.stderr})
            print(event.to_json(), file=sys.stderr)
        else:
            print(f"orasync: git error: {exc}", file=sys.stderr)
        return 2
    except OrasyncError as exc:
        if args.json:
            event = Event("error", str(exc), project="", data={"error_type": type(exc).__name__})
            print(event.to_json(), file=sys.stderr)
        else:
            print(f"orasync: {exc}", file=sys.stderr)
        return 2

