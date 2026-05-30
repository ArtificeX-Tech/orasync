from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

from krita import Extension, InfoObject, Krita

try:
    from PyQt6.QtCore import QProcess
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
except ImportError:  # Krita commonly embeds PyQt5.
    from PyQt5.QtCore import QProcess
    from PyQt5.QtWidgets import QFileDialog, QMessageBox


def _config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "orasync" / "krita-poc.json"


class OrasyncPocExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self.process = None
        self.config = self._load_config()

    def setup(self):
        pass

    def createActions(self, window):
        configure = window.createAction("orasync_poc_configure", "Orasync POC: Configure", "tools/scripts")
        configure.triggered.connect(self.configure)

        start = window.createAction("orasync_poc_start", "Orasync POC: Start Watch", "tools/scripts")
        start.triggered.connect(self.start_watch)

        stop = window.createAction("orasync_poc_stop", "Orasync POC: Stop Watch", "tools/scripts")
        stop.triggered.connect(self.stop_watch)

        save = window.createAction("orasync_poc_save", "Orasync POC: Save ORA Now", "tools/scripts")
        save.triggered.connect(self.save_active_document)

    def _load_config(self):
        path = _config_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_config(self):
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _command(self):
        raw = self.config.get("command") or os.environ.get("ORASYNC_COMMAND") or "orasync"
        return shlex.split(raw)

    def _active_document_path(self):
        document = Krita.instance().activeDocument()
        if document is None:
            return ""
        try:
            return document.fileName() or ""
        except Exception:
            return ""

    def configure(self):
        current = self._active_document_path()
        project = QFileDialog.getExistingDirectory(None, "Choose orasync project repo", self.config.get("project", ""))
        if not project:
            return
        ora, _ = QFileDialog.getSaveFileName(
            None,
            "Choose ORA file",
            self.config.get("ora") or current,
            "OpenRaster (*.ora)",
        )
        if not ora:
            return
        self.config.update({"project": project, "ora": ora})
        self._save_config()
        self._run_once(["init", project, "--ora", ora])

    def _run_once(self, args):
        command = self._command()
        process = QProcess()
        process.start(command[0], command[1:] + args)
        if not process.waitForFinished(30000):
            process.kill()
            QMessageBox.warning(None, "Orasync POC", "orasync command timed out.")
            return False
        stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        stdout = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        if process.exitCode() != 0:
            QMessageBox.warning(None, "Orasync POC", stderr or stdout or "orasync command failed.")
            return False
        if stdout:
            QMessageBox.information(None, "Orasync POC", stdout)
        return True

    def start_watch(self):
        if self.process is not None:
            QMessageBox.information(None, "Orasync POC", "Watcher is already running.")
            return
        project = self.config.get("project")
        ora = self.config.get("ora")
        if not project or not ora:
            self.configure()
            project = self.config.get("project")
            ora = self.config.get("ora")
        if not project or not ora:
            return

        command = self._command()
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self._read_watch_stdout)
        self.process.readyReadStandardError.connect(self._read_watch_stderr)
        self.process.finished.connect(self._watch_finished)
        self.process.start(command[0], command[1:] + ["--json", "watch", project, "--ora", ora])
        QMessageBox.information(None, "Orasync POC", "Watcher started.")

    def stop_watch(self):
        if self.process is None:
            return
        self.process.terminate()
        if not self.process.waitForFinished(3000):
            self.process.kill()
        self.process = None
        QMessageBox.information(None, "Orasync POC", "Watcher stopped.")

    def save_active_document(self):
        ora = self.config.get("ora")
        if not ora:
            self.configure()
            ora = self.config.get("ora")
        if not ora:
            return
        document = Krita.instance().activeDocument()
        if document is None:
            QMessageBox.warning(None, "Orasync POC", "No active Krita document.")
            return
        try:
            if hasattr(document, "exportImage"):
                document.exportImage(ora, InfoObject())
            else:
                document.saveAs(ora)
        except Exception as exc:
            QMessageBox.warning(None, "Orasync POC", f"Could not save ORA: {exc}")

    def _read_watch_stdout(self):
        if self.process is None:
            return
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = event.get("event")
            if name == "remote-applied":
                QMessageBox.information(
                    None,
                    "Orasync POC",
                    "Remote update was written to the ORA file. Reopen or reload the document if Krita does not refresh it automatically.",
                )
            elif name == "error":
                QMessageBox.warning(None, "Orasync POC", event.get("message", "orasync watcher error"))

    def _read_watch_stderr(self):
        if self.process is None:
            return
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            QMessageBox.warning(None, "Orasync POC", data)

    def _watch_finished(self):
        self.process = None

