"""滚动长截图工具：入口。"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

import config as config_mod
import native
from dialogs import SettingsDialog
from hotkey import HotkeyManager, pretty_hotkey
from session import CaptureSession
from theme import apply_dark_theme

VERSION = "1.0"


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)


def make_fallback_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(47, 124, 246))
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawRoundedRect(20, 12, 24, 30, 4, 4)
    painter.setBrush(QColor(47, 124, 246))
    painter.drawRoundedRect(24, 30, 16, 8, 2, 2)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawRect(28, 46, 8, 6)
    painter.end()
    return QIcon(pixmap)


class LongShotApp(QObject):
    def __init__(self, app: QApplication, cfg: config_mod.Config) -> None:
        super().__init__()
        self.app = app
        self.cfg = cfg
        self.session: CaptureSession | None = None

        icon_path = resource_path(os.path.join("resources", "icon.png"))
        self.icon = QIcon(icon_path) if os.path.exists(icon_path) else make_fallback_icon()

        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("滚动长截图工具")
        self.menu = QMenu()
        action_start = self.menu.addAction("开始长截图")
        action_start.triggered.connect(self.start_capture)
        action_settings = self.menu.addAction("设置…")
        action_settings.triggered.connect(self.open_settings)
        action_dir = self.menu.addAction("打开截图保存目录")
        action_dir.triggered.connect(self.open_save_dir)
        self.menu.addSeparator()
        action_quit = self.menu.addAction("退出")
        action_quit.triggered.connect(self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.hotkey = HotkeyManager(self)
        self.hotkey.start()
        self.hotkey.activated.connect(self.start_capture)
        ok, message = self.hotkey.bind(str(self.cfg.get("hotkey")))
        if not ok:
            # 快捷键被别的程序占用时，引导用户立刻更换（否则快捷键等于失效）
            QTimer.singleShot(800, lambda: self._guide_hotkey(message))

        QTimer.singleShot(700, self._welcome)

    def _guide_hotkey(self, message: str) -> None:
        self.notify("快捷键不可用，请更换", message)
        dialog = SettingsDialog(self.cfg, self.apply_hotkey)
        dialog.exec()

    # ---------- 托盘 ----------
    def _welcome(self) -> None:
        self.notify(
            "长截图已就绪",
            f"按 {pretty_hotkey(str(self.cfg.get('hotkey')))} 开始；右键托盘图标可打开设置。",
        )

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.start_capture()

    def notify(self, title: str, message: str) -> None:
        try:
            self.tray.showMessage(title, message, self.icon, 4000)
        except Exception:
            pass

    # ---------- 功能 ----------
    def start_capture(self) -> None:
        if self.session is not None and self.session.active:
            return
        self.notify("开始截图", "拖动框选区域，Enter 或双击开始采集")
        self.session = CaptureSession(self.cfg, self.notify, self.open_settings)
        self.session.closed.connect(self._on_session_closed)
        self.session.start()

    def _on_session_closed(self) -> None:
        if self.session is not None:
            self.session.deleteLater()
            self.session = None

    def apply_hotkey(self, text: str) -> tuple[bool, str]:
        # 注册失败时旧快捷键依然有效，不需要回滚
        ok, message = self.hotkey.bind(text)
        if not ok:
            return False, message
        self.cfg.set("hotkey", text)
        return True, ""

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.cfg, self.apply_hotkey)
        dialog.exec()

    def open_save_dir(self) -> None:
        directory = Path(str(self.cfg.get("save_dir")))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            os.startfile(str(directory))  # noqa: S606
        except Exception as exc:
            QMessageBox.warning(None, "无法打开目录", str(exc))

    def quit(self) -> None:
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
        try:
            self.hotkey.shutdown()
        except Exception:
            pass
        self.tray.hide()
        self.app.quit()


def install_exception_hook(app_ref: dict) -> None:
    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            config_mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(config_mod.LOG_DIR / "error.log", "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except Exception:
            pass
        app = app_ref.get("app")
        if app is not None:
            try:
                app.notify("程序出现异常", str(exc_value)[:200])
            except Exception:
                pass
        sys.stderr.write(text)

    sys.excepthook = hook


def main() -> int:
    if not native.acquire_single_instance():
        temp_app = QApplication(sys.argv)
        QMessageBox.information(None, "长截图", "程序已经在运行中，请查看系统托盘。")
        return 0

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("长截图")
    apply_dark_theme(app)

    cfg = config_mod.Config()
    controller = LongShotApp(app, cfg)
    ref: dict = {"app": controller}
    install_exception_hook(ref)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
