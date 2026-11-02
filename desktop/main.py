"""Media Enhancer desktop app: log in with the website account, then enhance files on this PC's GPU."""

import logging
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler

import typing

# On Python 3.10 PySide6 adds a placeholder `typing.Self`. typing_extensions would then re-export that
# placeholder instead of its own Self, and torch fails to import ("Plain typing.Self is not valid as
# type argument"). In the packaged app Qt is loaded before this file runs (PyInstaller runtime hook),
# so: hide Qt's placeholder, let typing_extensions create a proper Self, then put Qt's back.
if sys.version_info < (3, 11) and "typing_extensions" not in sys.modules:
    _qt_self = typing.__dict__.pop("Self", None)
    import typing_extensions  # noqa: F401, isort: skip
    if _qt_self is not None:
        typing.Self = _qt_self

import mecore.core  # noqa: F401, E402, isort: skip  (torch must load before the Qt widgets below)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop import paths
from desktop.api import ApiClient, ApiError
from mecore.media import NO_WINDOW
from desktop.i18n import is_rtl, set_language, tr
from desktop.runner import EngineHolder, EngineLoader
from desktop.store import Settings
from desktop.ui import STYLE, LoginWindow, MainWindow, ask

logger = logging.getLogger("desktop")


def setup_logging():
    log_file = paths.ensure_data_dir() / "app.log"
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


class Controller:
    def __init__(self, app):
        self.app = app
        self.settings = Settings()
        set_language(self.settings.get("language"))
        self.holder = EngineHolder()
        self.loader = None
        self.window = None
        self.api = None

    def apply_language(self):
        set_language(self.settings.get("language"))
        self.app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

    def start(self):
        self.apply_language()
        token = self.settings.token
        if token:
            api = ApiClient(self.settings.get("server_url"), token, self.settings.get("language"))
            try:
                account = api.me()
                return self.show_main(api, account)
            except ApiError as exc:
                if exc.code != "network":
                    self.settings.token = ""
                logger.info("Saved login not usable: %s", exc)
        self.show_login()

    def _swap(self, window):
        old = self.window
        self.window = window
        window.show()
        if old is not None:
            old.close()
            old.deleteLater()

    def show_login(self):
        login = LoginWindow(self.settings)
        login.logged_in.connect(self.show_main)
        login.language_toggled.connect(lambda: self.toggle_language(login_screen=True))
        self._swap(login)

    def show_main(self, api, account):
        self.api = api
        main = MainWindow(self.settings, api, account, self.holder)
        main.logout_requested.connect(self.logout)
        main.language_toggled.connect(self.toggle_language)
        self._swap(main)
        self.flush_pending_reports()
        self.loader = EngineLoader(self.holder)
        self.loader.ready.connect(main.engine_ready_cb)
        self.loader.error.connect(main.engine_error_cb)
        self.loader.start()

    def toggle_language(self, login_screen=False):
        self.settings.set("language", "en" if self.settings.get("language") == "fa" else "fa")
        self.apply_language()
        if login_screen or self.api is None:
            self.show_login()
        else:
            self.api.language = self.settings.get("language")
            self.show_main(self.api, self.window.account)

    def logout(self):
        api = self.api
        self.api = None
        self.settings.token = ""
        if api is not None:
            threading.Thread(target=lambda: _quiet(api.logout), daemon=True).start()
        self.show_login()

    def flush_pending_reports(self):
        """Results that could not be sent earlier (no internet) are sent now so refunds still happen."""
        pending = list(self.settings.get("pending_reports") or [])
        if not pending or self.api is None:
            return

        def send():
            left = []
            for item in pending:
                try:
                    self.api.finish_job(item["job_id"], item["status"], item.get("seconds", 0), item.get("error", ""))
                except ApiError as exc:
                    if exc.code == "network":
                        left.append(item)
            self.settings.set("pending_reports", left)

        threading.Thread(target=send, daemon=True).start()


def offer_shortcut(settings):
    """First start of the installed app: offer a desktop shortcut (the installer only extracts files)."""
    if not paths.FROZEN or settings.get("shortcut_asked"):
        return
    settings.set("shortcut_asked", True)
    if not ask(None, tr("shortcut_q")):
        return
    exe = sys.executable.replace("'", "''")
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        "[Environment]::GetFolderPath('Desktop') + '\\Media Enhancer.lnk');"
        f"$s.TargetPath = '{exe}'; $s.WorkingDirectory = (Split-Path '{exe}'); $s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], creationflags=NO_WINDOW, check=False)


def _quiet(fn):
    try:
        fn()
    except Exception:  # noqa: BLE001
        pass


def main():
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Media Enhancer")
    app.setStyleSheet(STYLE)
    controller = Controller(app)
    try:
        controller.apply_language()
        offer_shortcut(controller.settings)
        controller.start()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Startup failed")
        QMessageBox.critical(None, "Media Enhancer", str(exc))
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
