#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gimp, GimpUi, GLib, Gtk


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


class OrasyncPocPlugin(Gimp.PlugIn):
    __gtype_name__ = "OrasyncPocPlugin"

    def do_query_procedures(self):
        return [
            "python-fu-orasync-poc-configure",
            "python-fu-orasync-poc-start-watch",
            "python-fu-orasync-poc-stop-watch",
        ]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("*")
        procedure.set_documentation(
            "Orasync POC",
            "Start or stop the orasync OpenRaster Git sync watcher.",
            name,
        )
        procedure.set_attribution("ArtificeX", "ArtificeX", "2026")
        procedure.add_menu_path("<Image>/File/Orasync")
        if name.endswith("configure"):
            procedure.set_menu_label("Configure Orasync POC")
        elif name.endswith("start-watch"):
            procedure.set_menu_label("Start Orasync Watch")
        else:
            procedure.set_menu_label("Stop Orasync Watch")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        GimpUi.init("orasync-poc")
        try:
            stored = _load_config()
            name = procedure.get_name()
            if name.endswith("configure"):
                updated = _configure_dialog(stored)
                if updated is not None:
                    _save_config(updated)
                    _show_message("Orasync POC configuration saved.")
            elif name.endswith("start-watch"):
                if not stored.get("project") or not stored.get("ora"):
                    updated = _configure_dialog(stored)
                    if updated is None:
                        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
                    _save_config(updated)
                    stored = updated
                _show_message(_start_watch(stored))
            elif name.endswith("stop-watch"):
                _show_message(_stop_watch())
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            _show_message(f"Orasync POC error: {exc}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())


Gimp.main(OrasyncPocPlugin.__gtype__, sys.argv)
