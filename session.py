"""一次完整的长截图会话：框选 → 采集 → 保存。"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QPoint, QRect, pyqtSignal

from collector import FrameCollector
from dialogs import SaveDialog
from overlay import SelectionController
from preview import PreviewWindow


class CaptureSession(QObject):
    closed = pyqtSignal()
    key_signal = pyqtSignal(str)

    def __init__(self, cfg, notify, open_settings) -> None:
        super().__init__()
        self.cfg = cfg
        self._notify = notify
        self._open_settings = open_settings
        self.active = False
        self.controller: SelectionController | None = None
        self.collector: FrameCollector | None = None
        self.preview: PreviewWindow | None = None
        self._keys = None
        self._suspended = False
        self.key_signal.connect(self._on_key)

    # ---------- 启动 ----------
    def start(self) -> None:
        if self.active:
            return
        self.active = True
        self.controller = SelectionController(self.cfg)
        self.controller.confirmed.connect(self._begin_collect)
        self.controller.cancelled.connect(self.close)
        self.controller.settings_requested.connect(self._show_settings)
        self.controller.open()
        self._start_keys()

    # ---------- 框选阶段的键盘 ----------
    # 遮罩是 Tool 窗口，未必能拿到系统焦点，所以 Enter / Esc 走全局监听
    def _start_keys(self) -> None:
        try:
            from pynput import keyboard

            self._keys = keyboard.Listener(on_press=self._on_press)
            self._keys.daemon = True
            self._keys.start()
        except Exception:
            self._keys = None

    def _stop_keys(self) -> None:
        if self._keys is not None:
            try:
                self._keys.stop()
            except Exception:
                pass
            self._keys = None

    def _on_press(self, key) -> None:
        try:
            from pynput import keyboard

            if key == keyboard.Key.enter:
                self.key_signal.emit("enter")
            elif key == keyboard.Key.esc:
                self.key_signal.emit("esc")
        except Exception:
            pass

    def _on_key(self, name: str) -> None:
        if not self.active or self._suspended:
            return
        if self.controller is None or self.controller.phase != "select":
            return
        if name == "enter":
            self.controller.confirm()
        elif name == "esc":
            self.controller.request_cancel()

    # ---------- 采集 ----------
    def _begin_collect(self, rect: QRect) -> None:
        self._stop_keys()
        scale = self.controller.scale_at(rect.center())
        self.collector = FrameCollector(self.cfg, rect, scale)
        self.collector.canvas_changed.connect(self._on_canvas)
        self.collector.stats_changed.connect(self._on_stats)
        self.collector.finished.connect(self._on_finished)
        self.collector.cancelled.connect(self.close)
        self.collector.notice.connect(self._notify)

        self.preview = PreviewWindow()
        self._place_preview(rect)
        self.preview.show()
        self.preview.sync_capture()
        self.preview.raise_()

        self.collector.start()

    def _on_canvas(self, canvas) -> None:
        if self.preview is not None:
            self.preview.update_canvas(canvas)

    def _on_stats(self, frames: int, height: int) -> None:
        if self.controller is not None:
            self.controller.set_stats(frames, height)
        if self.preview is not None:
            self.preview.set_stats(frames, height)
            self.preview.update()

    def _place_preview(self, rect: QRect) -> None:
        preview = self.preview
        controller = self.controller
        if preview is None or controller is None:
            return
        info = None
        center = rect.center()
        for item in controller.screen_info:
            if (
                item["x"] <= center.x() < item["x"] + item["w"]
                and item["y"] <= center.y() < item["y"] + item["h"]
            ):
                info = item
                break
        if info is None:
            preview.hide()
            return

        available = info["screen"].availableGeometry()
        height = max(240, min(600, int(available.height() * 0.72)))
        preview.resize(240, height)

        scale = info["scale"] or 1.0
        width_phys = int(240 * scale)
        margin = int(12 * scale)
        virtual = controller.virtual_rect()
        x = None
        if rect.x() + rect.width() + margin + width_phys <= virtual.x() + virtual.width():
            x = rect.x() + rect.width() + margin
        elif rect.x() - margin - width_phys >= virtual.x():
            x = rect.x() - margin - width_phys
        if x is None:
            preview.hide()
            return

        point = controller.to_logical(QPoint(x, rect.y()))
        max_y = available.y() + available.height() - preview.height() - 8
        point.setY(min(max(available.y() + 8, point.y()), max_y))
        preview.move(point)

    # ---------- 结束 ----------
    def _on_finished(self) -> None:
        collector = self.collector
        canvas = collector.canvas if collector is not None else None
        if canvas is None or canvas.size == 0:
            self.close()
            return

        if self.preview is not None:
            self.preview.hide()
        if self.controller is not None:
            self.controller.close_all()

        dialog = SaveDialog(self.cfg, canvas)
        accepted = dialog.exec()

        if accepted and dialog.saved_path:
            text = f"已保存到：{dialog.saved_path}"
            if dialog.copied:
                text += "\n已复制到剪贴板"
            self._notify("长截图已保存", text)
        self.close()

    def _show_settings(self) -> None:
        if self.controller is None:
            return
        self._suspended = True
        self.controller.set_visible_for_settings(False)
        try:
            self._open_settings()
        finally:
            self._suspended = False
            if self.controller is not None and self.active:
                self.controller.set_visible_for_settings(True)

    def close(self) -> None:
        if not self.active:
            return
        self.active = False
        self._stop_keys()
        if self.collector is not None:
            self.collector.stop()
            self.collector.deleteLater()
            self.collector = None
        if self.preview is not None:
            self.preview.hide()
            self.preview.deleteLater()
            self.preview = None
        if self.controller is not None:
            self.controller.close_all()
            self.controller.deleteLater()
            self.controller = None
        self.closed.emit()
