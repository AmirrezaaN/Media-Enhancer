"""Windows of the desktop app (PySide6 / Qt)."""

import math
import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from mecore import MediaError, Options, media_type_for, probe_image, probe_video
from mecore.media import IMAGE_EXTENSIONS, NO_WINDOW, VIDEO_EXTENSIONS
from mecore.pipeline import preview_pair

from . import APP_VERSION, paths
from .api import ApiClient, ApiError
from .i18n import format_duration, is_rtl, ltr, num, tr
from .runner import JobRunner

STYLE = """
* { font-family: "Segoe UI", "Tahoma"; font-size: 10pt; color: #eceefb; }
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget { background: #0e1020; }
QFrame#card { background: #171a2e; border: 1px solid #2a2f52; border-radius: 14px; }
QFrame#drop { background: #1f2340; border: 2px dashed #3a4170; border-radius: 14px; }
QFrame#drop[hover="true"] { border-color: #8b74ff; }
QLabel#title { font-size: 18pt; font-weight: 700; }
QLabel#h2 { font-size: 12pt; font-weight: 700; }
QLabel#muted { color: #9aa1c2; }
QLabel#error { color: #ff7a7a; }
QLabel#ok { color: #4fd18b; }
QLabel#pill { background: #1f2340; border: 1px solid #2a2f52; border-radius: 12px; padding: 4px 12px; }
QLabel#cost { font-size: 13pt; font-weight: 700; }
QLineEdit { background: #1f2340; border: 1px solid #2a2f52; border-radius: 9px; padding: 8px 10px; }
QLineEdit:focus { border-color: #8b74ff; }
QPushButton { background: #1f2340; border: 1px solid #2a2f52; border-radius: 9px; padding: 7px 14px; }
QPushButton:hover { border-color: #8b74ff; }
QPushButton:disabled { color: #5c6285; }
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6a4dff, stop:1 #13b8bb);
    border: none; font-weight: 700; font-size: 11pt; padding: 11px 26px; color: white;
}
QPushButton#primary:disabled { background: #2a2f52; color: #7a80a3; }
QPushButton#danger { color: #ff8a8a; }
QPushButton#link { background: transparent; border: none; color: #8b74ff; padding: 2px; }
QRadioButton, QCheckBox { spacing: 8px; padding: 4px 0; }
QRadioButton:disabled, QCheckBox:disabled { color: #5c6285; }
QProgressBar { background: #1f2340; border: none; border-radius: 7px; height: 14px; text-align: center; }
QProgressBar::chunk { border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6a4dff, stop:1 #13b8bb); }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #2a2f52; border-radius: 5px; min-height: 30px; }
"""


def card():
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def label(text="", name=None, wrap=False):
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


class ElidedLabel(QLabel):
    """One-line label that shortens long text (paths, file names) with an ellipsis instead of growing."""

    def __init__(self, text="", name=None):
        super().__init__()
        if name:
            self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)
        self._full = ""
        self.setText(text)

    def setText(self, text):
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(60, self.width())))


def ask(parent, text) -> bool:
    """Yes/no question with buttons in the app's language (Qt's own buttons are always English)."""
    box = QMessageBox(parent)
    box.setWindowTitle(tr("app_title"))
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Question)
    yes = box.addButton(tr("yes"), QMessageBox.ButtonRole.YesRole)
    box.addButton(tr("no"), QMessageBox.ButtonRole.NoRole)
    box.exec()
    return box.clickedButton() is yes


def app_icon():
    path = paths.asset("icon.png")
    return QIcon(str(path)) if path.exists() else QIcon()


def numpy_to_pixmap(arr):
    h, w = arr.shape[:2]
    image = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


# ---------------------------------------------------------------------------- login


class LoginWindow(QWidget):
    logged_in = Signal(object, dict)  # ApiClient, account
    language_toggled = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setObjectName("root")
        self.setWindowTitle(tr("app_title"))
        self.setWindowIcon(app_icon())
        self.setFixedSize(460, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        top = QHBoxLayout()
        top.addStretch()
        lang = QPushButton(tr("language"))
        lang.clicked.connect(self.language_toggled.emit)
        top.addWidget(lang)
        outer.addLayout(top)

        logo = QLabel()
        icon = paths.asset("icon.png")
        if icon.exists():
            logo.setPixmap(QPixmap(str(icon)).scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(logo)
        title = label(tr("app_title"), "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)
        tag = label(tr("tagline"), "muted", wrap=True)
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(tag)
        outer.addSpacing(14)

        box = card()
        form = QVBoxLayout(box)
        form.setContentsMargins(20, 18, 20, 18)
        form.addWidget(label(tr("login_title"), "h2"))
        self.username = QLineEdit(settings.get("username") or "")
        self.username.setPlaceholderText(tr("username"))
        self.password = QLineEdit()
        self.password.setPlaceholderText(tr("password"))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self.submit)
        self.username.returnPressed.connect(self.password.setFocus)
        form.addWidget(self.username)
        form.addWidget(self.password)

        self.server = QLineEdit(settings.get("server_url"))
        self.server.setPlaceholderText(tr("server"))
        self.server.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.server.setVisible(False)
        adv = QPushButton(tr("advanced"))
        adv.setObjectName("link")
        adv.clicked.connect(lambda: self.server.setVisible(not self.server.isVisible()))
        form.addWidget(adv, alignment=Qt.AlignmentFlag.AlignLeading)
        form.addWidget(self.server)

        self.error = label("", "error", wrap=True)
        form.addWidget(self.error)
        self.button = QPushButton(tr("login"))
        self.button.setObjectName("primary")
        self.button.clicked.connect(self.submit)
        form.addWidget(self.button)
        outer.addWidget(box)

        signup = QPushButton(tr("no_account"))
        signup.setObjectName("link")
        signup.clicked.connect(self.open_signup)
        outer.addWidget(signup, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch()
        version = label(f"v{APP_VERSION}", "muted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(version)
        (self.password if self.username.text() else self.username).setFocus()

    def open_signup(self):
        QDesktopServices.openUrl(QUrl(self.server.text().rstrip("/") + "/accounts/register/"))

    def submit(self):
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self.error.setText(tr("fill_login"))
            return
        server = self.server.text().strip() or self.settings.get("server_url")
        self.button.setEnabled(False)
        self.button.setText(tr("logging_in"))
        self.error.setText("")

        api = ApiClient(server, language=self.settings.get("language"))
        device = f"{platform.node()} ({platform.system()} {platform.release()})"
        self._thread = _Call(lambda: api.login(username, password, device))
        self._thread.done.connect(lambda account: self._ok(api, server, username, account))
        self._thread.error.connect(self._fail)
        self._thread.start()

    def _ok(self, api, server, username, account):
        self.settings.set("server_url", server)
        self.settings.set("username", username)
        self.settings.token = api.token
        self.password.clear()
        self.logged_in.emit(api, account)

    def _fail(self, message):
        self.button.setEnabled(True)
        self.button.setText(tr("login"))
        self.error.setText(message)


class _Call(QThread):
    """Run one blocking API call off the UI thread."""

    done = Signal(object)
    error = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except ApiError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------- widgets


class DropArea(QFrame):
    file_chosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(150)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.thumb = QLabel("⇪")
        self.thumb.setFixedSize(150, 110)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("font-size: 34pt; background: #171a2e; border-radius: 10px;")
        layout.addWidget(self.thumb)
        text = QVBoxLayout()
        self.title = ElidedLabel(tr("drop_here"), "h2")
        self.info = label(tr("drop_hint"), "muted", wrap=True)
        text.addStretch()
        text.addWidget(self.title)
        text.addWidget(self.info)
        text.addStretch()
        layout.addLayout(text, 1)

    def mousePressEvent(self, event):
        exts = " ".join(f"*.{e}" for e in sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(self, tr("choose_file"), "", f"{tr('file_filter')} ({exts})")
        if path:
            self.file_chosen.emit(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("hover", True)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self.setProperty("hover", False)
        self.style().polish(self)

    def dropEvent(self, event):
        self.dragLeaveEvent(event)
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.file_chosen.emit(urls[0].toLocalFile())

    def show_file(self, name, details, pixmap=None):
        self.title.setText(name)
        self.info.setText(details)
        if pixmap is not None and not pixmap.isNull():
            self.thumb.setPixmap(pixmap.scaled(150, 110, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        else:
            self.thumb.setText("🎬")


class CompareView(QWidget):
    """Before/after slider: drag to move the split line."""

    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.before = self.after = None
        self.split = 0.5

    def set_images(self, before: QPixmap, after: QPixmap):
        self.before, self.after = before, after
        self.split = 0.5
        self.update()

    def _target(self):
        if self.before is None:
            return QRect()
        size = self.before.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect(QPoint((self.width() - size.width()) // 2, (self.height() - size.height()) // 2), size)

    def _move(self, x):
        rect = self._target()
        if rect.width() > 0:
            self.split = min(1.0, max(0.0, (x - rect.left()) / rect.width()))
            self.update()

    def mousePressEvent(self, event):
        self._move(event.position().x())

    def mouseMoveEvent(self, event):
        self._move(event.position().x())

    def paintEvent(self, event):
        if self.before is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self._target()
        p.drawPixmap(rect, self.before)
        cut = rect.left() + int(rect.width() * self.split)
        p.save()
        p.setClipRect(QRect(cut, rect.top(), rect.right() - cut + 1, rect.height()))
        p.drawPixmap(rect, self.after)
        p.restore()
        p.fillRect(QRect(cut - 1, rect.top(), 3, rect.height()), Qt.GlobalColor.white)
        p.setPen(Qt.GlobalColor.white)
        p.fillRect(QRect(rect.left() + 8, rect.top() + 8, 60, 22), Qt.GlobalColor.black)
        p.drawText(QRect(rect.left() + 8, rect.top() + 8, 60, 22), Qt.AlignmentFlag.AlignCenter, tr("before"))
        p.fillRect(QRect(rect.right() - 68, rect.top() + 8, 60, 22), Qt.GlobalColor.black)
        p.drawText(QRect(rect.right() - 68, rect.top() + 8, 60, 22), Qt.AlignmentFlag.AlignCenter, tr("after"))
        p.end()


# ---------------------------------------------------------------------------- main window


class MainWindow(QMainWindow):
    logout_requested = Signal()
    language_toggled = Signal()

    def __init__(self, settings, api, account, holder):
        super().__init__()
        self.settings = settings
        self.api = api
        self.account = account
        self.holder = holder
        self.source = None
        self.media_type = None
        self.info = None
        self.runner = None
        self.result_path = None
        self.engine_ready = False
        self.job_started_at = 0.0

        self.setWindowTitle(tr("app_title"))
        self.setWindowIcon(app_icon())
        self.resize(980, 820)
        self.setMinimumSize(760, 600)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root = QWidget()
        root.setObjectName("root")
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 16, 22, 22)
        layout.setSpacing(14)

        # header
        header = QHBoxLayout()
        logo = QLabel()
        icon = paths.asset("icon.png")
        if icon.exists():
            logo.setPixmap(QPixmap(str(icon)).scaled(34, 34, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        header.addWidget(logo)
        header.addWidget(label(tr("app_title"), "title"))
        header.addStretch()
        self.balance = label("", "pill")
        header.addWidget(self.balance)
        refresh = QPushButton(tr("refresh"))
        refresh.clicked.connect(self.refresh_account)
        header.addWidget(refresh)
        lang = QPushButton(tr("language"))
        lang.clicked.connect(self._toggle_language)
        header.addWidget(lang)
        self.logout_btn = QPushButton(f"{tr('logout')} ({ltr(account['username'])})")
        self.logout_btn.clicked.connect(self._logout)
        header.addWidget(self.logout_btn)
        layout.addLayout(header)

        self.gpu = label(tr("engine_loading"), "muted", wrap=True)
        layout.addWidget(self.gpu)

        # file
        self.drop = DropArea()
        self.drop.file_chosen.connect(self.choose_file)
        layout.addWidget(self.drop)
        self.file_error = label("", "error", wrap=True)
        self.file_error.setVisible(False)
        layout.addWidget(self.file_error)

        # options
        options = card()
        grid = QGridLayout(options)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(30)
        grid.addWidget(label(tr("mode"), "h2"), 0, 0)
        grid.addWidget(label(tr("upscale"), "h2"), 0, 1)
        grid.addWidget(label(tr("extras"), "h2"), 0, 2)
        self.quality = QButtonGroup(self)
        self.fast = QRadioButton(f"{tr('fast')} — {tr('fast_hint')}")
        self.high = QRadioButton(f"{tr('high')} — {tr('high_hint')}")
        self.high.setChecked(True)
        self.quality.addButton(self.fast)
        self.quality.addButton(self.high)
        grid.addWidget(self.fast, 1, 0)
        grid.addWidget(self.high, 2, 0)
        self.scale = QButtonGroup(self)
        self.x2 = QRadioButton(f"{tr('x2')} — {tr('x2_hint')}")
        self.x4 = QRadioButton(f"{tr('x4')} — {tr('x4_hint')}")
        self.x4.setChecked(True)
        self.scale.addButton(self.x2)
        self.scale.addButton(self.x4)
        grid.addWidget(self.x2, 1, 1)
        grid.addWidget(self.x4, 2, 1)
        self.faces = QCheckBox(tr("faces"))
        self.smooth = QCheckBox(tr("smooth"))
        grid.addWidget(self.faces, 1, 2)
        grid.addWidget(self.smooth, 2, 2)
        for widget in (self.fast, self.high, self.x2, self.x4, self.faces, self.smooth):
            widget.toggled.connect(self.update_cost)
        layout.addWidget(options)

        # output folder
        out_row = QHBoxLayout()
        out_row.addWidget(label(tr("output_folder") + ":", "muted"))
        self.out_label = ElidedLabel()
        out_row.addWidget(self.out_label, 1)
        change = QPushButton(tr("change"))
        change.clicked.connect(self.choose_output)
        out_row.addWidget(change)
        reset = QPushButton(tr("same_folder"))
        reset.clicked.connect(lambda: self._set_output(""))
        out_row.addWidget(reset)
        layout.addLayout(out_row)
        self._set_output(settings.get("output_dir") or "")

        # cost + start
        action = QHBoxLayout()
        cost_col = QVBoxLayout()
        self.cost = label("—", "cost")
        self.cost_note = label("", "muted")
        cost_col.addWidget(self.cost)
        cost_col.addWidget(self.cost_note)
        action.addLayout(cost_col)
        action.addStretch()
        self.start_btn = QPushButton(tr("start"))
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        action.addWidget(self.start_btn)
        layout.addLayout(action)

        # progress
        self.progress_box = card()
        pl = QVBoxLayout(self.progress_box)
        pl.setContentsMargins(18, 14, 18, 14)
        self.stage = label("", "h2")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        row = QHBoxLayout()
        self.percent = label("0%", None)
        self.eta = label("", "muted")
        row.addWidget(self.percent)
        row.addWidget(self.eta)
        row.addStretch()
        self.cancel_btn = QPushButton(tr("cancel"))
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self.cancel)
        row.addWidget(self.cancel_btn)
        pl.addWidget(self.stage)
        pl.addWidget(self.bar)
        pl.addLayout(row)
        self.progress_box.setVisible(False)
        layout.addWidget(self.progress_box)

        # result
        self.result_box = card()
        rl = QVBoxLayout(self.result_box)
        rl.setContentsMargins(18, 14, 18, 14)
        self.result_text = label("", "ok", wrap=True)
        rl.addWidget(self.result_text)
        self.result_file = ElidedLabel("", "muted")
        rl.addWidget(self.result_file)
        self.compare = CompareView()
        rl.addWidget(self.compare, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        open_file = QPushButton(tr("open_file"))
        open_file.setObjectName("primary")
        open_file.clicked.connect(lambda: self.result_path and os.startfile(self.result_path))
        show = QPushButton(tr("open_folder"))
        show.clicked.connect(self.show_in_folder)
        buttons.addWidget(open_file)
        buttons.addWidget(show)
        buttons.addStretch()
        rl.addLayout(buttons)
        self.result_box.setVisible(False)
        self.result_box.setMinimumHeight(460)
        layout.addWidget(self.result_box)

        self.status = label("", "error", wrap=True)
        layout.addWidget(self.status)
        layout.addStretch()

        self.set_account(account)
        self.update_cost()

    # ----- account
    def set_account(self, account):
        self.account = account
        self.balance.setText("● " + tr("balance", n=account["coins"]))
        self.update_cost()

    def set_coins(self, coins):
        if coins is not None and coins >= 0:
            self.account["coins"] = coins
            self.set_account(self.account)

    def refresh_account(self):
        self._call = _Call(self.api.me)
        self._call.done.connect(self.set_account)
        self._call.error.connect(self._api_error)
        self._call.start()

    def _api_error(self, message):
        self.status.setText(message)

    def _logout(self):
        if self.runner is not None:
            return
        self.logout_requested.emit()

    def _toggle_language(self):
        if self.runner is None:
            self.language_toggled.emit()

    # ----- engine
    def engine_ready_cb(self, device_name, cuda):
        self.engine_ready = True
        self.gpu.setObjectName("muted" if cuda else "error")
        self.gpu.setText(tr("gpu_ok", name=ltr(device_name)) if cuda else tr("gpu_missing"))
        self.gpu.style().polish(self.gpu)
        self.update_cost()

    def engine_error_cb(self, message):
        self.gpu.setObjectName("error")
        self.gpu.setText(tr("engine_error", err=message))
        self.gpu.style().polish(self.gpu)

    # ----- file and options
    def choose_file(self, path):
        if self.runner is not None:
            return
        path = Path(path)
        self.file_error.setVisible(False)
        media_type = media_type_for(path.name)
        if media_type is None:
            return self._file_problem(tr("unsupported"))
        try:
            if media_type == "image":
                info = probe_image(path)
                parts = [tr("image"), ltr(f"{num(info.width)}×{num(info.height)}")]
                pixmap = QPixmap(str(path))
            else:
                info = probe_video(path, paths.ffmpeg_tool("ffprobe"))
                parts = [tr("video"), ltr(f"{num(info.width)}×{num(info.height)}"),
                         tr("fps_value", n=num(round(info.fps))), tr("seconds_value", n=num(info.duration, "{:.1f}"))]
                pixmap = self._video_thumb(path)
        except MediaError:
            return self._file_problem(tr("unreadable"))
        size_mb = path.stat().st_size / 1e6
        self.source, self.media_type, self.info = path, media_type, info
        parts.append(tr("mb_value", n=num(size_mb, "{:.1f}")))
        self.drop.show_file(path.name, " · ".join(parts), pixmap)
        self.smooth.setEnabled(media_type == "video")
        if media_type == "image":
            self.smooth.setChecked(False)
        self.result_box.setVisible(False)
        self._set_output(self.settings.get("output_dir") or "")
        self.update_cost()

    def _file_problem(self, message):
        self.file_error.setText(message)
        self.file_error.setVisible(True)

    @staticmethod
    def _video_thumb(path):
        tmp = Path(tempfile.gettempdir()) / "media_enhancer_thumb.jpg"
        try:
            subprocess.run([paths.ffmpeg_tool("ffmpeg"), "-v", "error", "-y", "-ss", "0.5", "-i", str(path),
                            "-frames:v", "1", "-vf", "scale=320:-2", str(tmp)],
                           capture_output=True, timeout=20, creationflags=NO_WINDOW)
            return QPixmap(str(tmp))
        except (OSError, subprocess.TimeoutExpired):
            return None

    def options(self) -> Options:
        limits = self.account.get("limits", {})
        return Options(
            quality="fast" if self.fast.isChecked() else "high",
            scale=2 if self.x2.isChecked() else 4,
            face=self.faces.isChecked(),
            fps_boost=self.smooth.isChecked() and self.media_type == "video",
            max_side=limits.get("max_image_side", 8192) if self.media_type == "image"
            else limits.get("max_video_side", 3840),
            denoise=self.account.get("video_denoise", 1),
        )

    def price(self, opts):
        """Same formula as the server; the server's number is the one that is charged."""
        prices = self.account["prices"][self.media_type]
        high = opts.quality == "high"
        if self.media_type == "image":
            base = (prices["high"] if high else prices["fast"]) + (prices["x4"] if opts.scale == 4 else 0) \
                + (prices["face"] if opts.face else 0)
        else:
            units = max(1, math.ceil(self.info.duration / 10))
            base = ((prices["high"] if high else prices["fast"]) + (prices["x4"] if opts.scale == 4 else 0)
                    + (prices["face"] if opts.face else 0) + (prices["fps"] if opts.fps_boost else 0)) * units
        return math.ceil(base * self.account["app_price_percent"] / 100)

    def update_cost(self):
        if self.source is None:
            self.cost.setText("—")
            self.cost_note.setText("")
            self.start_btn.setEnabled(False)
            return
        cost = self.price(self.options())
        self.cost.setText(tr("cost", n=cost) if cost else tr("free"))
        enough = cost <= self.account["coins"]
        note = tr("cost_note", p=self.account["app_price_percent"])
        self.cost_note.setText(note if enough else f"{note} — {tr('not_enough')}")
        self.cost_note.setObjectName("muted" if enough else "error")
        self.cost_note.style().polish(self.cost_note)
        self.start_btn.setEnabled(enough and self.engine_ready and self.runner is None)

    def _set_output(self, folder):
        self.settings.set("output_dir", folder)
        if folder:
            self.out_label.setText(folder)
        elif self.source is not None:
            self.out_label.setText(str(self.source.parent))
        else:
            self.out_label.setText(tr("same_folder"))

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, tr("output_folder"), self.settings.get("output_dir") or "")
        if folder:
            self._set_output(folder)

    def output_dir(self) -> Path:
        folder = self.settings.get("output_dir")
        return Path(folder) if folder else self.source.parent

    # ----- running
    def _set_busy(self, busy):
        for widget in (self.drop, self.fast, self.high, self.x2, self.x4, self.faces, self.logout_btn):
            widget.setEnabled(not busy)
        self.smooth.setEnabled(not busy and self.media_type == "video")
        self.progress_box.setVisible(busy)
        self.cancel_btn.setEnabled(True)
        self.update_cost()

    def start(self):
        if self.source is None:
            self.status.setText(tr("choose_first"))
            return
        self.status.setText("")
        self.result_box.setVisible(False)
        opts = self.options()
        self.runner = JobRunner(self.holder, self.api, self.settings, self.source, self.media_type, self.info,
                                opts, self.output_dir())
        self.runner.progress.connect(self.on_progress)
        self.runner.charged.connect(lambda cost, coins: self.set_coins(coins))
        self.runner.succeeded.connect(self.on_success)
        self.runner.failed.connect(self.on_failed)
        self.runner.cancelled.connect(self.on_cancelled)
        self.runner.finished.connect(self._runner_done)
        self.job_started_at = time.monotonic()
        self.on_progress(0, "charging")
        self._set_busy(True)
        self.runner.start()

    def cancel(self):
        if self.runner is not None:
            if ask(self, tr("cancel_confirm")):
                self.cancel_btn.setEnabled(False)
                self.runner.cancel()

    def on_progress(self, percent, stage):
        if stage:
            self.stage.setText(tr(f"stage_{stage}"))
        self.bar.setValue(int(percent * 10))
        self.percent.setText(tr("percent", n=num(percent, "{:.1f}")))
        elapsed = time.monotonic() - self.job_started_at
        if percent >= 3 and elapsed > 5:
            self.eta.setText(tr("time_left", t=format_duration(elapsed / percent * (100 - percent))))

    def on_success(self, result, seconds, coins):
        self.set_coins(coins)
        self.result_path = str(result.output_path)
        before, after = preview_pair(result.before, result.after, 1400)
        import numpy as np

        self.compare.set_images(numpy_to_pixmap(np.asarray(before)), numpy_to_pixmap(np.asarray(after)))
        self.result_text.setText(f"{tr('done')}  {tr('done_time', t=format_duration(seconds))}")
        self.result_file.setText(self.result_path)
        self.result_box.setVisible(True)

    def on_failed(self, message, coins, charged):
        self.set_coins(coins)
        self.status.setText(tr("failed", err=message) if charged else message)

    def on_cancelled(self, coins):
        self.set_coins(coins)
        self.status.setText(tr("cancelled"))

    def _runner_done(self):
        self.runner = None
        self.eta.setText("")
        self._set_busy(False)
        self.refresh_account()

    def show_in_folder(self):
        if self.result_path:
            subprocess.run(["explorer", "/select,", os.path.normpath(self.result_path)], creationflags=NO_WINDOW)

    def closeEvent(self, event):
        if self.runner is not None:
            if not ask(self, tr("busy_close")):
                event.ignore()
                return
            self.runner.cancel()
            self.runner.wait(20000)
        event.accept()
