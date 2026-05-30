#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gimp, GimpUi, Gio, GLib, GObject, Gtk


LOCAL_INTERVAL_SECONDS = 2
REMOTE_INTERVAL_SECONDS = 5.0


def _config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "orasync" / "gimp-poc.json"


def _load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _command(config: dict) -> list[str]:
    return shlex.split(config.get("command") or os.environ.get("ORASYNC_COMMAND") or "orasync")


def _looks_like_remote(value: str) -> bool:
    return "://" in value or (value.startswith("git@") and ":" in value)


def _show_message(message: str) -> None:
    dialog = Gtk.MessageDialog(
        transient_for=None,
        flags=0,
        message_type=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text=message,
    )
    dialog.run()
    dialog.destroy()


def _configure_dialog(config: dict) -> dict | None:
    dialog = Gtk.Dialog(title="Orasync POC", flags=0)
    dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
    box.add(grid)

    project_entry = Gtk.Entry(text=config.get("project", ""))
    ora_entry = Gtk.Entry(text=config.get("ora", ""))
    grid.attach(Gtk.Label(label="Project repo"), 0, 0, 1, 1)
    grid.attach(project_entry, 1, 0, 1, 1)
    grid.attach(Gtk.Label(label="ORA file"), 0, 1, 1, 1)
    grid.attach(ora_entry, 1, 1, 1, 1)

    dialog.show_all()
    response = dialog.run()
    new_config = None
    if response == Gtk.ResponseType.OK:
        new_config = {**config, "project": project_entry.get_text(), "ora": ora_entry.get_text()}
    dialog.destroy()
    return new_config


def _pid_file() -> Path:
    return _config_path().with_suffix(".watch.pid")


def _start_watch(config: dict) -> str:
    project = config.get("project")
    ora = config.get("ora")
    if not project or not ora:
        raise RuntimeError("Project and ORA paths must be configured first.")
    if _looks_like_remote(project):
        raise RuntimeError("Project repo must be a local folder, not a Git remote URL.")
    command = _command(config) + ["--json", "watch", project, "--ora", ora]
    log_path = _config_path().with_suffix(".watch.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=log)
    _pid_file().write_text(str(proc.pid), encoding="utf-8")
    return f"orasync watcher started with PID {proc.pid}.\nLog: {log_path}"


def _stop_watch() -> str:
    path = _pid_file()
    if not path.exists():
        return "No watcher PID file was found."
    pid = int(path.read_text(encoding="utf-8").strip())
    try:
        os.kill(pid, 15)
    except OSError as exc:
        path.unlink(missing_ok=True)
        return f"Could not stop watcher PID {pid}: {exc}"
    path.unlink(missing_ok=True)
    return f"Stopped watcher PID {pid}."


def _ora_signature(ora_path: str | None):
    if not ora_path:
        return None
    try:
        stat = Path(ora_path).expanduser().stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _config_property_names(config) -> set[str]:
    return {prop.name for prop in config.list_properties()}


def _set_config_property(config, name: str, value) -> None:
    if name in _config_property_names(config):
        config.set_property(name, value)


def _pdb_procedure(name: str):
    pdb = Gimp.get_pdb()
    if pdb is None:
        raise RuntimeError("GIMP PDB is not available.")
    procedure = pdb.lookup_procedure(name)
    if procedure is None:
        raise RuntimeError(f"GIMP procedure {name} is not available.")
    return procedure


def _check_pdb_result(result, action: str):
    status = result.index(0)
    if status != Gimp.PDBStatusType.SUCCESS:
        raise RuntimeError(f"{action} failed with status {status}.")
    return result


def _export_image_to_ora(image, ora_path: str) -> None:
    target = Path(ora_path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    procedure = _pdb_procedure("file-openraster-export")
    proc_config = procedure.create_config()
    _set_config_property(proc_config, "run-mode", Gimp.RunMode.NONINTERACTIVE)
    _set_config_property(proc_config, "image", image)
    _set_config_property(proc_config, "file", Gio.File.new_for_path(str(target)))
    result = procedure.run(proc_config)
    _check_pdb_result(result, "OpenRaster export")
    image.clean_all()


def _load_ora_image(ora_path: str):
    procedure = _pdb_procedure("file-openraster-load")
    proc_config = procedure.create_config()
    _set_config_property(proc_config, "run-mode", Gimp.RunMode.NONINTERACTIVE)
    _set_config_property(proc_config, "file", Gio.File.new_for_path(str(Path(ora_path).expanduser())))
    result = _check_pdb_result(procedure.run(proc_config), "OpenRaster load")
    return result.index(1)


def _parse_events(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _run_sync_once(config: dict, *, force_import: bool) -> list[dict]:
    project = config.get("project")
    ora = config.get("ora")
    if not project or not ora:
        raise RuntimeError("Project and ORA paths must be configured first.")
    if _looks_like_remote(project):
        raise RuntimeError("Project repo must be a local folder, not a Git remote URL.")

    command = _command(config) + [
        "--json",
        "sync",
        project,
        "--ora",
        ora,
        "-m",
        "GIMP live sync",
    ]
    if force_import:
        command.append("--force-import")
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    events = _parse_events(proc.stdout) + _parse_events(proc.stderr)
    if proc.returncode != 0:
        locked = any(event.get("data", {}).get("error_type") == "LockError" for event in events)
        locked = locked or "locked" in (proc.stderr + proc.stdout).lower()
        if locked:
            return events
        message = proc.stderr.strip() or proc.stdout.strip() or "orasync sync failed."
        raise RuntimeError(message)
    return events


class LiveSyncWindow(Gtk.Window):
    def __init__(self, config: dict, image):
        super().__init__(title="Orasync Live Sync")
        self.config = config
        self.image = image
        self.source_id = 0
        self.next_remote_check = 0.0
        self.ora_signature = _ora_signature(config.get("ora"))
        self.last_error = None

        self.set_border_width(12)
        self.set_default_size(440, 100)
        self.connect("destroy", self._stop)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(box)
        self.status = Gtk.Label(label="Starting live sync...")
        self.status.set_xalign(0.0)
        self.status.set_line_wrap(True)
        box.pack_start(self.status, True, True, 0)

        stop = Gtk.Button(label="Stop")
        stop.connect("clicked", self._stop)
        box.pack_start(stop, False, False, 0)

    def start(self) -> None:
        self.source_id = GLib.timeout_add_seconds(LOCAL_INTERVAL_SECONDS, self._tick)
        self.show_all()
        self._tick()
        Gtk.main()

    def _stop(self, *_args):
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = 0
        if Gtk.main_level() > 0:
            Gtk.main_quit()
        return False

    def _set_status(self, message: str) -> None:
        self.status.set_text(message)

    def _image_is_valid(self) -> bool:
        try:
            return bool(self.image and self.image.is_valid())
        except Exception:
            return False

    def _tick(self):
        if not self._image_is_valid():
            self._set_status("The synced image is no longer open.")
            return True

        now = time.monotonic()
        remote_due = now >= self.next_remote_check
        if remote_due:
            self.next_remote_check = now + REMOTE_INTERVAL_SECONDS

        try:
            local_dirty = bool(self.image.is_dirty())
            current_ora_signature = _ora_signature(self.config.get("ora"))
            ora_changed = (
                current_ora_signature is not None
                and self.ora_signature is not None
                and current_ora_signature != self.ora_signature
            )
            if not local_dirty and not remote_due:
                if ora_changed:
                    self.ora_signature = current_ora_signature
                    self._replace_image_from_ora(self.config["ora"])
                return True
            if local_dirty:
                _export_image_to_ora(self.image, self.config["ora"])
                self.ora_signature = _ora_signature(self.config.get("ora"))
                self._set_status("Exported local edit; syncing...")
            elif ora_changed:
                self.ora_signature = current_ora_signature
                self._replace_image_from_ora(self.config["ora"])
                return True

            events = _run_sync_once(self.config, force_import=local_dirty)
            self._handle_events(events)
        except Exception as exc:
            message = str(exc)
            if message != self.last_error:
                self.last_error = message
            self._set_status(f"Orasync error: {message}")
        return True

    def _handle_events(self, events: list[dict]) -> None:
        if not events:
            self._set_status("No sync events.")
            return
        for event in events:
            name = event.get("event")
            if name == "remote-applied":
                ora = event.get("ora_path") or self.config.get("ora")
                self._replace_image_from_ora(ora)
                return
            if event.get("data", {}).get("error_type") == "LockError":
                self._set_status("Project is busy; retrying...")
                return

        name = events[-1].get("event", "synced")
        if name == "idle":
            self._set_status("Live sync idle.")
        elif name in {"local-pushed", "local-committed"}:
            self._set_status("Local edit synced.")
        elif name == "remote-missing":
            self._set_status("No Git remote is configured.")
        else:
            self._set_status(events[-1].get("message", name))

    def _replace_image_from_ora(self, ora_path: str) -> None:
        old_image = self.image
        new_image = _load_ora_image(ora_path)
        Gimp.Display.new(new_image)
        try:
            old_image.clean_all()
            old_image.delete()
        except Exception:
            pass
        self.image = new_image
        self.image.clean_all()
        self.ora_signature = _ora_signature(ora_path)
        self._set_status("Remote edit loaded into GIMP.")


class OrasyncPocPlugin(Gimp.PlugIn):
    __gtype_name__ = "OrasyncPocPlugin"

    def do_query_procedures(self):
        return [
            "python-fu-orasync-poc-configure",
            "python-fu-orasync-poc-start-watch",
            "python-fu-orasync-poc-stop-watch",
        ]

    def do_create_procedure(self, name):
        if name.endswith("start-watch"):
            procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
            procedure.set_image_types("*")
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        else:
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
            procedure.add_enum_argument(
                "run-mode",
                "Run mode",
                "The run mode",
                Gimp.RunMode,
                Gimp.RunMode.INTERACTIVE,
                GObject.ParamFlags.READWRITE,
            )
        procedure.set_documentation(
            "Orasync POC",
            "Live-sync the current GIMP image through an orasync project.",
            name,
        )
        procedure.set_attribution("ArtificeX", "ArtificeX", "2026")
        if name.endswith("configure"):
            procedure.set_menu_label("Configure Orasync POC")
        elif name.endswith("start-watch"):
            procedure.set_menu_label("Start Orasync Live Sync")
        else:
            procedure.set_menu_label("Stop Orasync Background Watcher")
        procedure.add_menu_path("<Image>/Filters/Development/Orasync")
        return procedure

    def run(self, procedure, *args):
        GimpUi.init("orasync-poc")
        try:
            stored = _load_config()
            name = procedure.get_name()
            if name.endswith("configure"):
                _config, _run_data = args
                updated = _configure_dialog(stored)
                if updated is not None:
                    _save_config(updated)
                    _show_message("Orasync POC configuration saved.")
            elif name.endswith("start-watch"):
                _run_mode, image, _drawables, _config, _run_data = args
                if not stored.get("project") or not stored.get("ora"):
                    updated = _configure_dialog(stored)
                    if updated is None:
                        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
                    _save_config(updated)
                    stored = updated
                LiveSyncWindow(stored, image).start()
            elif name.endswith("stop-watch"):
                _config, _run_data = args
                _show_message(_stop_watch())
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            _show_message(f"Orasync POC error: {exc}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())


Gimp.main(OrasyncPocPlugin.__gtype__, sys.argv)
