import sys
import os
import json
import shutil
import tempfile
import subprocess
import urllib.request
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog


def _parse_version(tag: str) -> tuple[int, ...]:
    cleaned = tag.strip().lstrip("vV")
    parts = []
    for p in cleaned.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


class UpdateCheckWorker(QThread):
    update_available = Signal(str, str, str)
    up_to_date = Signal(str)
    check_failed = Signal(str)

    def __init__(self, repo: str, current_version: str, manual: bool = False):
        super().__init__()
        self.repo = repo
        self.current_version = current_version
        self.manual = manual

    def run(self):
        try:
            url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": f"PageSmith/{self.current_version}", "Accept": "application/vnd.github+json"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            latest_tag = data.get("tag_name", "").strip()
            if not latest_tag or _parse_version(latest_tag) <= _parse_version(self.current_version):
                if self.manual:
                    self.up_to_date.emit(self.current_version)
                return

            target_asset = "PageSmith.exe" if sys.platform == "win32" else "PageSmith-Linux-x86_64"
            download_url = ""
            for asset in data.get("assets", []):
                if asset.get("name") == target_asset:
                    download_url = asset.get("browser_download_url", "")
                    break

            if download_url:
                notes = (data.get("body") or "Bug fixes and new features.").strip()
                self.update_available.emit(latest_tag, download_url, notes)
            elif self.manual:
                self.check_failed.emit(f"Release {latest_tag} is still compiling on GitHub Actions. Try again in 2 minutes.")
        except Exception as exc:
            if self.manual:
                self.check_failed.emit(f"Could not check for updates: {exc}")


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, download_url: str, current_version: str):
        super().__init__()
        self.download_url = download_url
        self.current_version = current_version

    def run(self):
        try:
            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": f"PageSmith/{self.current_version}"}
            )
            suffix = ".exe" if sys.platform == "win32" else ""
            fd, temp_path = tempfile.mkstemp(prefix="PageSmith_update_", suffix=suffix)
            os.close(fd)

            with urllib.request.urlopen(req, timeout=60) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(temp_path, "wb") as f:
                    while True:
                        if self.isInterruptionRequested():
                            f.close()
                            os.remove(temp_path)
                            return
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            self.progress.emit(int((downloaded / total_size) * 100))

            self.finished.emit(temp_path)
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdaterPlugin:
    def __init__(self, ctx):
        self.ctx = ctx
        self._checker: UpdateCheckWorker | None = None
        self._downloader: UpdateDownloadWorker | None = None

        ctx.toolbar.addSeparator()
        act_update = QAction("Check Updates", ctx.window)
        act_update.triggered.connect(lambda: self.check_for_updates(manual=True))
        ctx.toolbar.addAction(act_update)

        # Silent check 2 seconds after startup
        QTimer.singleShot(2000, lambda: self.check_for_updates(manual=False))

    def check_for_updates(self, manual: bool = False):
        if self._checker and self._checker.isRunning():
            return
        if manual:
            self.ctx.status_bar.showMessage("Checking GitHub for updates...")
        self._checker = UpdateCheckWorker(self.ctx.github_repo, self.ctx.app_version, manual=manual)
        self._checker.update_available.connect(self._prompt_update)
        self._checker.up_to_date.connect(
            lambda ver: QMessageBox.information(self.ctx.window, "PageSmith Up to Date", f"You are running the latest version ({ver}).")
        )
        self._checker.check_failed.connect(
            lambda msg: QMessageBox.warning(self.ctx.window, "Update Check", msg)
        )
        self._checker.start()

    def _prompt_update(self, latest_tag: str, download_url: str, notes: str):
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self.ctx.window,
                f"Update Available ({latest_tag})",
                f"PageSmith {latest_tag} is available on GitHub!\nRun 'git pull' to update your local source checkout."
            )
            return

        reply = QMessageBox.question(
            self.ctx.window,
            f"Update Available — PageSmith {latest_tag}",
            f"A new version of PageSmith ({latest_tag}) is available! (Current: {self.ctx.app_version})\n\n"
            f"Release Notes:\n{notes[:400]}\n\n"
            f"Download and replace PageSmith automatically now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self._start_self_update(latest_tag, download_url)

    def _start_self_update(self, latest_tag: str, download_url: str):
        prog = QProgressDialog(f"Downloading PageSmith {latest_tag}...", "Cancel", 0, 100, self.ctx.window)
        prog.setWindowTitle("Updating PageSmith")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        self._downloader = UpdateDownloadWorker(download_url, self.ctx.app_version)
        self._downloader.progress.connect(prog.setValue)
        prog.canceled.connect(self._downloader.requestInterruption)

        def on_downloaded(temp_bin_path: str):
            prog.close()
            self._apply_binary_replacement(temp_bin_path)

        def on_failed(err: str):
            prog.close()
            QMessageBox.critical(self.ctx.window, "Update Failed", f"Failed to download update:\n{err}")

        self._downloader.finished.connect(on_downloaded)
        self._downloader.failed.connect(on_failed)
        self._downloader.start()

    def _apply_binary_replacement(self, new_bin_path: str):
        current_exe = os.path.abspath(sys.executable)
        reopen_args = []
        for i in range(self.ctx.tabs.count()):
            tab = self.ctx.tabs.widget(i)
            if hasattr(tab, "file_path") and hasattr(tab, "doc"):
                reopen_args.append(tab.file_path)
                tab.doc.close()

        if sys.platform == "win32":
            bat_fd, bat_path = tempfile.mkstemp(prefix="pagesmith_swap_", suffix=".bat")
            os.close(bat_fd)
            quoted_args = " ".join(f'"{p}"' for p in reopen_args)
            bat_script = (
                "@echo off\r\n"
                "timeout /t 2 /nobreak > nul\r\n"
                ":retry\r\n"
                f'move /y "{new_bin_path}" "{current_exe}" > nul 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                "  timeout /t 1 /nobreak > nul\r\n"
                "  goto retry\r\n"
                ")\r\n"
                f'start "" "{current_exe}" {quoted_args}\r\n'
                'del "%~f0"\r\n'
            )
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_script)

            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            )
            QApplication.quit()
        else:
            os.chmod(new_bin_path, 0o755)
            shutil.move(new_bin_path, current_exe)
            os.execv(current_exe, [current_exe] + reopen_args)


def register(ctx):
    return UpdaterPlugin(ctx)