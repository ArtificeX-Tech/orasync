from __future__ import annotations

import json
import os
import shlex
import sys
import time
from pathlib import Path

from krita import Extension, InfoObject, Krita

try:
    from PyQt6.QtCore import QProcess, QTimer
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
except ImportError:  # Krita commonly embeds PyQt5.
    from PyQt5.QtCore import QProcess, QTimer
    from PyQt5.QtWidgets import QFileDialog, QMessageBox


def _config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "orasync" / "krita-poc.json"


def _log(message):
    path = _config_path().with_name("krita-poc-loader.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _ora_signature(ora):
    try:
        stat = Path(ora).expanduser().stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


class OrasyncPocExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self.timer = None
        self.sync_process = None
        self.sync_stdout = ""
        self.sync_stderr = ""
        self.document = None
        self.next_remote_check = 0.0
        self.ora_signature = None
        self.last_error = None
        self.applying_remote = False
        self.config = self._load_config()

    def setup(self):
        _log("orasync_poc: setup called")

    def createActions(self, window):
        _log("orasync_poc: createActions called")
        configure = window.createAction("orasync_poc_configure", "Orasync POC: Configure", "tools/scripts")
        configure.triggered.connect(self.configure)

        start = window.createAction("orasync_poc_start", "Orasync POC: Start Live Sync", "tools/scripts")
        start.triggered.connect(self.start_watch)

        stop = window.createAction("orasync_poc_stop", "Orasync POC: Stop Live Sync", "tools/scripts")
        stop.triggered.connect(self.stop_watch)

        save = window.createAction("orasync_poc_save", "Orasync POC: Sync ORA Now", "tools/scripts")
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

    def _ensure_config(self):
        project = self.config.get("project")
        ora = self.config.get("ora")
        if not project or not ora:
            self.configure()
            project = self.config.get("project")
            ora = self.config.get("ora")
        return project, ora

    def start_watch(self):
        if self.timer is not None:
            QMessageBox.information(None, "Orasync POC", "Live sync is already running.")
            return
        project, ora = self._ensure_config()
        if not project or not ora:
            return
        document = Krita.instance().activeDocument()
        if document is None:
            QMessageBox.warning(None, "Orasync POC", "Open an image before starting live sync.")
            return

        self.document = document
        self.next_remote_check = 0.0
        self.ora_signature = _ora_signature(ora)
        self.last_error = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._live_sync_tick)
        self.timer.start(2000)
        self._live_sync_tick()
        QMessageBox.information(None, "Orasync POC", "Live sync started.")

    def stop_watch(self):
        if self.timer is None:
            return
        self.timer.stop()
        self.timer = None
        if self.sync_process is not None:
            self.sync_process.terminate()
            if not self.sync_process.waitForFinished(3000):
                self.sync_process.kill()
            self.sync_process = None
        QMessageBox.information(None, "Orasync POC", "Live sync stopped.")

    def save_active_document(self):
        project, ora = self._ensure_config()
        if not project or not ora:
            return
        document = Krita.instance().activeDocument()
        if document is None:
            QMessageBox.warning(None, "Orasync POC", "No active Krita document.")
            return
        if not self._export_document(document, ora):
            return
        self.ora_signature = _ora_signature(ora)
        self._run_once(["--json", "sync", project, "--ora", ora, "--force-import", "-m", "Krita manual sync"])

    def _export_document(self, document, ora):
        try:
            Path(ora).expanduser().parent.mkdir(parents=True, exist_ok=True)
            if hasattr(document, "waitForDone"):
                document.waitForDone()
            if hasattr(document, "exportImage"):
                ok = document.exportImage(ora, InfoObject())
                if ok is False:
                    raise RuntimeError("Krita returned false while exporting the ORA file.")
            else:
                document.saveAs(ora)
            if hasattr(document, "setModified"):
                document.setModified(False)
            return True
        except Exception as exc:
            QMessageBox.warning(None, "Orasync POC", f"Could not save ORA: {exc}")
            return False

    def _live_sync_tick(self):
        if self.sync_process is not None or self.applying_remote:
            return
        project = self.config.get("project")
        ora = self.config.get("ora")
        if not project or not ora:
            return
        document = self.document or Krita.instance().activeDocument()
        if document is None:
            return

        now = time.monotonic()
        remote_due = now >= self.next_remote_check
        if remote_due:
            self.next_remote_check = now + 5.0
        try:
            local_dirty = bool(document.modified()) if hasattr(document, "modified") else False
        except Exception:
            local_dirty = False
        current_ora_signature = _ora_signature(ora)
        ora_changed = (
            current_ora_signature is not None
            and self.ora_signature is not None
            and current_ora_signature != self.ora_signature
        )

        if local_dirty:
            if not self._export_document(document, ora):
                return
            self.ora_signature = _ora_signature(ora)
        elif ora_changed:
            self.ora_signature = current_ora_signature
            self._replace_document_from_ora(ora)
            return
        elif not remote_due:
            return

        self._start_sync_process(force_import=local_dirty)

    def _start_sync_process(self, *, force_import):
        project = self.config.get("project")
        ora = self.config.get("ora")
        if not project or not ora:
            return
        command = self._command()
        args = [
            "--json",
            "sync",
            project,
            "--ora",
            ora,
            "-m",
            "Krita live sync",
        ]
        if force_import:
            args.append("--force-import")
        self.sync_stdout = ""
        self.sync_stderr = ""
        self.sync_process = QProcess()
        self.sync_process.readyReadStandardOutput.connect(self._read_sync_stdout)
        self.sync_process.readyReadStandardError.connect(self._read_sync_stderr)
        self.sync_process.finished.connect(self._sync_finished)
        self.sync_process.start(command[0], command[1:] + args)

    def _read_sync_stdout(self):
        if self.sync_process is None:
            return
        data = bytes(self.sync_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_sync_event(event)

    def _read_sync_stderr(self):
        if self.sync_process is None:
            return
        data = bytes(self.sync_process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            unparsed = []
            for line in data.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    unparsed.append(line)
                    continue
                self._handle_sync_event(event)
            if unparsed:
                self.sync_stderr += "\n".join(unparsed) + "\n"

    def _sync_finished(self):
        process = self.sync_process
        self.sync_process = None
        if process is None:
            return
        if process.exitCode() != 0 and self.sync_stderr:
            self._show_error_once(self.sync_stderr.strip())

    def _handle_sync_event(self, event):
        name = event.get("event")
        if name == "remote-applied":
            ora = event.get("ora_path") or self.config.get("ora")
            if ora:
                self._replace_document_from_ora(ora)
        elif name == "error":
            if event.get("data", {}).get("error_type") == "LockError":
                _log("orasync_poc: project busy; retrying")
                return
            self._show_error_once(event.get("message", "orasync sync error"))

    def _replace_document_from_ora(self, ora):
        app = Krita.instance()
        self.applying_remote = True
        try:
            old_document = self.document or app.activeDocument()
            if old_document is not None:
                try:
                    old_document.setModified(False)
                except Exception:
                    pass
                try:
                    old_document.close()
                except Exception as exc:
                    _log(f"orasync_poc: could not close old document: {exc}")

            new_document = app.openDocument(ora)
            if new_document is None:
                raise RuntimeError("Krita could not open the synced ORA file.")
            self.document = new_document
            try:
                new_document.setModified(False)
            except Exception:
                pass
            window = app.activeWindow()
            if window is not None:
                view = window.addView(new_document)
                if hasattr(window, "showView") and view is not None:
                    window.showView(view)
            try:
                app.setActiveDocument(new_document)
            except Exception:
                pass
            self.ora_signature = _ora_signature(ora)
        except Exception as exc:
            self._show_error_once(f"Could not reload synced ORA: {exc}")
        finally:
            self.applying_remote = False

    def _show_error_once(self, message):
        _log(f"orasync_poc: {message}")
        if message != self.last_error:
            self.last_error = message
            QMessageBox.warning(None, "Orasync POC", message)
