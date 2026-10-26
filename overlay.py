"""全屏遮罩、框选、选区调整、采集阶段的外框。

坐标约定：
- 选区(self.sel) 与所有鼠标坐标、mss 抓屏坐标统一使用「全局物理像素」；
- 只在绘制/摆放窗口时换算成 Qt 的「逻辑坐标」。
"""
from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

import native

MASK_COLOR = QColor(0, 0, 0, 150)
ACCENT = QColor(47, 124, 246)
HANDLE_SIZE = 8  # 逻辑像素
HANDLE_TOL = 10  # 逻辑像素命中范围
MIN_SELECTION = 50  # 逻辑像素


class HintBar(QWidget):
    """选区旁的小提示条，始终不接收鼠标。"""

    def __init__(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._main = ""
        self._sub = ""
        self._font = QFont("Microsoft YaHei UI", 10)
        self._small = QFont("Microsoft YaHei UI", 9)
        self._resize_to_text()

    def set_text(self, main: str, sub: str = "") -> None:
        if main == self._main and sub == self._sub:
            return
        self._main = main
        self._sub = sub
        self._resize_to_text()
        self.update()

    def _resize_to_text(self) -> None:
        fm = QFontMetrics(self._font)
        fm_small = QFontMetrics(self._small)
        width = max(fm.horizontalAdvance(self._main), fm_small.horizontalAdvance(self._sub)) + 32
        height = 12 + fm.height() + (fm_small.height() + 4 if self._sub else 0) + 10
        self.resize(max(120, width), height)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(QColor(20, 21, 24, 238))
        p.drawRoundedRect(rect, 8, 8)

        fm = QFontMetrics(self._font)
        fm_small = QFontMetrics(self._small)
        y = 12
        p.setFont(self._font)
        p.setPen(QColor(240, 242, 245))
        p.drawText(QRect(16, y, self.width() - 32, fm.height()), int(Qt.AlignmentFlag.AlignLeft), self._main)
        if self._sub:
            y += fm.height()
            p.setFont(self._small)
            p.setPen(QColor(150, 200, 255))
            p.drawText(
                QRect(16, y, self.width() - 32, fm_small.height()),
                int(Qt.AlignmentFlag.AlignLeft),
                self._sub,
            )


class MaskOverlay(QWidget):
    """一整块屏幕的暗色遮罩，负责框选与调整交互。"""

    def __init__(self, ctrl: "SelectionController", screen) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)
        self.ctrl = ctrl
        self.screen = screen
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(screen.geometry())

        self.ox = 0
        self.oy = 0
        self.pw = 0
        self.ph = 0
        self.scale = float(screen.devicePixelRatio() or 1.0)
        self.is_primary = screen is QGuiApplication.primaryScreen()
        self.gear_rect = QRect()

    def sync_geometry(self) -> None:
        self.winId()
        rect = native.window_rect(int(self.winId()))
        if rect and rect[2] > 1 and rect[3] > 1:
            self.ox, self.oy, self.pw, self.ph = rect
            self.scale = self.pw / max(1, self.width())
        if self.is_primary:
            self.gear_rect = QRect(self.width() - 104, 16, 88, 34)
        native.exclude_from_capture(int(self.winId()))

    # ---------- 坐标换算 ----------
    def to_local(self, x: int, y: int) -> QPointF:
        return QPointF((x - self.ox) / self.scale, (y - self.oy) / self.scale)

    def to_local_rect(self, rect: QRect) -> QRectF:
        return QRectF(
            (rect.x() - self.ox) / self.scale,
            (rect.y() - self.oy) / self.scale,
            rect.width() / self.scale,
            rect.height() / self.scale,
        )

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:  # noqa: N802
        ctrl = self.ctrl
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), MASK_COLOR)

        sel = QRectF(ctrl.sel) if not ctrl.sel.isNull() and ctrl.sel.width() > 0 else QRectF()
        hole = QRectF()
        if not sel.isEmpty():
            hole = self.to_local_rect(ctrl.sel).intersected(QRectF(self.rect()))
            if hole.width() > 0 and hole.height() > 0:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                p.fillRect(hole, Qt.GlobalColor.transparent)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                # alpha=2 让选区内部仍能接收鼠标（Windows 会跳过完全透明的像素）
                p.fillRect(hole, QColor(0, 0, 0, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(ACCENT, 2))
                p.drawRect(hole.adjusted(-1, -1, 1, 1))

        if self.is_primary:
            self._paint_gear(p)

        if not hole.isEmpty():
            self._paint_handles(p, hole)
            self._paint_size(p, hole)

    def _paint_gear(self, p: QPainter) -> None:
        r = self.gear_rect
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(28, 30, 34, 220))
        p.drawRoundedRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        center = QPointF(r.x() + 20.0, r.center().y())
        p.setPen(QPen(QColor(210, 214, 220), 1.6))
        for i in range(8):
            angle = math.radians(i * 45)
            inner = QPointF(center.x() + 5 * math.cos(angle), center.y() + 5 * math.sin(angle))
            outer = QPointF(center.x() + 8 * math.cos(angle), center.y() + 8 * math.sin(angle))
            p.drawLine(inner, outer)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center, 4.2, 4.2)
        p.setPen(QColor(235, 238, 242))
        p.setFont(QFont("Microsoft YaHei UI", 9))
        p.drawText(
            QRectF(r.x() + 34, r.y(), r.width() - 38, r.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "设置",
        )

    def _paint_handles(self, p: QPainter, hole: QRectF) -> None:
        if self.ctrl.mode == "new":
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.setBrush(QColor(47, 124, 246))
        half = HANDLE_SIZE / 2
        for px, py in self.ctrl.handle_points(hole):
            p.drawRect(QRectF(px - half, py - half, HANDLE_SIZE, HANDLE_SIZE))

    def _paint_size(self, p: QPainter, hole: QRectF) -> None:
        sel = self.ctrl.sel
        scale = self.ctrl.scale_at(sel.center())
        text = f"{round(sel.width() / scale)} × {round(sel.height() / scale)}"
        font = QFont("Microsoft YaHei UI", 9)
        fm = QFontMetrics(font)
        w = fm.horizontalAdvance(text) + 16
        h = fm.height() + 8
        x = hole.left()
        y = hole.top() - h - 6
        if y < 0:
            y = hole.top() + 6
        rect = QRectF(x, y, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 21, 24, 210))
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(QColor(235, 238, 242))
        p.setFont(font)
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    # ---------- 交互 ----------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.is_primary and self.gear_rect.contains(event.position().toPoint()):
            self.ctrl.settings_requested.emit()
            return
        x, y = native.cursor_pos()
        self.ctrl.press(x, y)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x, y = native.cursor_pos()
        if self.ctrl.mode:
            self.ctrl.move(x, y)
            return
        handle = self.ctrl.handle_at(QPoint(x, y))
        if handle:
            self.setCursor(self.ctrl.handle_cursor(handle))
        elif not self.ctrl.sel.isNull() and self.ctrl.sel.contains(QPoint(x, y)):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = native.cursor_pos()
        self.ctrl.release(x, y)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = native.cursor_pos()
        self.ctrl.double_click(QPoint(x, y))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.ctrl.confirm()
        elif key == Qt.Key.Key_Escape:
            self.ctrl.request_cancel()
        else:
            super().keyPressEvent(event)


class FrameOverlay(QWidget):
    """采集阶段：只画选区外侧的边框，不遮暗、不接收鼠标、不进截图。"""

    def __init__(self, ctrl: "SelectionController", screen) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)
        self.ctrl = ctrl
        self.screen = screen
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setGeometry(screen.geometry())
        self.ox = 0
        self.oy = 0
        self.scale = float(screen.devicePixelRatio() or 1.0)

    def sync_geometry(self) -> None:
        self.winId()
        rect = native.window_rect(int(self.winId()))
        if rect and rect[2] > 1 and rect[3] > 1:
            self.ox, self.oy = rect[0], rect[1]
            self.scale = rect[2] / max(1, self.width())
        native.exclude_from_capture(int(self.winId()))

    def to_local_rect(self, rect: QRect) -> QRectF:
        return QRectF(
            (rect.x() - self.ox) / self.scale,
            (rect.y() - self.oy) / self.scale,
            rect.width() / self.scale,
            rect.height() / self.scale,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        sel = self.ctrl.sel
        if sel.isNull() or sel.width() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        hole = self.to_local_rect(sel)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT)
        t = 2.0
        # 四条边全部画在选区之外，保证抓屏时不会截到边框
        p.drawRect(QRectF(hole.left() - t, hole.top() - t, hole.width() + 2 * t, t))
        p.drawRect(QRectF(hole.left() - t, hole.top() + hole.height(), hole.width() + 2 * t, t))
        p.drawRect(QRectF(hole.left() - t, hole.top(), t, hole.height()))
        p.drawRect(QRectF(hole.left() + hole.width(), hole.top(), t, hole.height()))
        # 四角加粗的 L 形括号，同样完全位于选区外侧
        p.setBrush(QColor(255, 255, 255, 235))
        c = 14.0
        l, tp = hole.left(), hole.top()
        rt, bt = hole.left() + hole.width(), hole.top() + hole.height()
        for cx, cy, sx, sy in (
            (l, tp, -1, -1),
            (rt, tp, 1, -1),
            (l, bt, -1, 1),
            (rt, bt, 1, 1),
        ):
            hx = cx - c - t if sx < 0 else cx
            hy = cy - t if sy < 0 else cy
            p.drawRect(QRectF(hx, hy, c + t, t))
            vx = cx - t if sx < 0 else cx
            vy = cy - c - t if sy < 0 else cy
            p.drawRect(QRectF(vx, vy, t, c + t))


class SelectionController(QObject):
    confirmed = pyqtSignal(object)  # QRect（物理像素）
    cancelled = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, cfg, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.sel = QRect()
        self.phase = "select"
        self.mode: Optional[str] = None
        self.handle: Optional[str] = None
        self.anchor = QPoint()
        self.press_pos = QPoint()
        self.start_rect = QRect()
        self.masks: list[MaskOverlay] = []
        self.frames: list[FrameOverlay] = []
        self.hint: Optional[HintBar] = None
        self.screen_info: list[dict] = []
        self.screens = list(QGuiApplication.screens())
        self._stats = ""

    # ---------- 显示 ----------
    def open(self) -> None:
        for screen in self.screens:
            w = MaskOverlay(self, screen)
            w.show()
            self.masks.append(w)
            self.screen_info.append(
                {
                    "screen": screen,
                    "x": 0,
                    "y": 0,
                    "w": 0,
                    "h": 0,
                    "scale": float(screen.devicePixelRatio() or 1.0),
                }
            )
        QApplication.processEvents()
        for idx, w in enumerate(self.masks):
            w.sync_geometry()
            info = self.screen_info[idx]
            info.update({"x": w.ox, "y": w.oy, "w": w.pw, "h": w.ph, "scale": w.scale})
        self.hint = HintBar()
        self.hint.show()
        native.exclude_from_capture(int(self.hint.winId()))
        self._set_hint()
        self.refresh()

        target = self._mask_under_cursor()
        if target is not None:
            target.activateWindow()
            target.setFocus()

    def close_all(self) -> None:
        for w in self.masks + self.frames:
            w.hide()
            w.deleteLater()
        self.masks.clear()
        self.frames.clear()
        if self.hint is not None:
            self.hint.hide()
            self.hint.deleteLater()
            self.hint = None

    # ---------- 坐标 ----------
    def scale_at(self, point: QPoint) -> float:
        for info in self.screen_info:
            if (
                info["x"] <= point.x() < info["x"] + info["w"]
                and info["y"] <= point.y() < info["y"] + info["h"]
            ):
                return info["scale"] or 1.0
        return 1.0

    def virtual_rect(self) -> QRect:
        if not self.screen_info:
            return QRect(0, 0, 1920, 1080)
        xs = [i["x"] for i in self.screen_info]
        ys = [i["y"] for i in self.screen_info]
        x2 = [i["x"] + i["w"] for i in self.screen_info]
        y2 = [i["y"] + i["h"] for i in self.screen_info]
        left, top = min(xs), min(ys)
        return QRect(left, top, max(x2) - left, max(y2) - top)

    def to_logical(self, point: QPoint) -> QPoint:
        for info in self.screen_info:
            if (
                info["x"] <= point.x() < info["x"] + info["w"]
                and info["y"] <= point.y() < info["y"] + info["h"]
            ):
                geo = info["screen"].geometry()
                scale = info["scale"] or 1.0
                return QPoint(
                    int(geo.x() + (point.x() - info["x"]) / scale),
                    int(geo.y() + (point.y() - info["y"]) / scale),
                )
        return point

    def _mask_under_cursor(self) -> Optional[MaskOverlay]:
        x, y = native.cursor_pos()
        for w in self.masks:
            if w.rect().contains(w.to_local(x, y).toPoint()):
                return w
        return self.masks[0] if self.masks else None

    # ---------- 手柄 ----------
    def _min_size(self, point: QPoint) -> int:
        return int(MIN_SELECTION * self.scale_at(point))

    def handle_points(self, hole: QRectF) -> list[tuple[float, float]]:
        """绘制手柄用（选区局部坐标）。"""
        return [
            (hole.left(), hole.top()),
            (hole.left() + hole.width() / 2, hole.top()),
            (hole.left() + hole.width(), hole.top()),
            (hole.left(), hole.top() + hole.height() / 2),
            (hole.left() + hole.width(), hole.top() + hole.height() / 2),
            (hole.left(), hole.top() + hole.height()),
            (hole.left() + hole.width() / 2, hole.top() + hole.height()),
            (hole.left() + hole.width(), hole.top() + hole.height()),
        ]

    def handle_at(self, point: QPoint) -> Optional[str]:
        r = self.sel
        if r.isNull() or r.width() <= 0:
            return None
        tol = int(HANDLE_TOL * self.scale_at(point))
        left, top = r.x(), r.y()
        right, bottom = r.x() + r.width(), r.y() + r.height()
        mid_x, mid_y = (left + right) // 2, (top + bottom) // 2
        points = {
            "tl": (left, top),
            "tr": (right, top),
            "bl": (left, bottom),
            "br": (right, bottom),
            "tm": (mid_x, top),
            "bm": (mid_x, bottom),
            "lm": (left, mid_y),
            "rm": (right, mid_y),
        }
        for name, (px, py) in points.items():
            if abs(point.x() - px) <= tol and abs(point.y() - py) <= tol:
                return name
        return None

    def handle_cursor(self, handle: str) -> Qt.CursorShape:
        if handle in ("tl", "br"):
            return Qt.CursorShape.SizeFDiagCursor
        if handle in ("tr", "bl"):
            return Qt.CursorShape.SizeBDiagCursor
        if handle in ("tm", "bm"):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.SizeHorCursor

    # ---------- 鼠标 ----------
    def press(self, x: int, y: int) -> None:
        if self.phase != "select":
            return
        point = QPoint(x, y)
        if not self.sel.isNull() and self.sel.width() > 0:
            handle = self.handle_at(point)
            if handle:
                self.mode = "resize"
                self.handle = handle
                self.start_rect = QRect(self.sel)
                self.press_pos = point
                return
            if self.sel.contains(point):
                self.mode = "move"
                self.start_rect = QRect(self.sel)
                self.press_pos = point
                return
        self.mode = "new"
        self.anchor = point
        self.sel = QRect(x, y, 0, 0)
        self.refresh()

    def move(self, x: int, y: int) -> None:
        if self.phase != "select" or self.mode is None:
            return
        point = QPoint(x, y)
        if self.mode == "new":
            self.sel = self._rect_between(self.anchor, point)
        elif self.mode == "move":
            self.sel = self._clamp(self.start_rect.translated(point - self.press_pos))
        elif self.mode == "resize":
            self.sel = self._resize(self.start_rect, point)
        self.refresh()

    def release(self, x: int, y: int) -> None:
        if self.phase != "select":
            return
        if self.mode == "new":
            min_size = self._min_size(QPoint(x, y))
            if self.sel.width() < min_size or self.sel.height() < min_size:
                self.sel = QRect()
        self.mode = None
        self.handle = None
        self.refresh()

    def double_click(self, point: QPoint) -> None:
        if self.phase == "select" and not self.sel.isNull() and self.sel.contains(point):
            self.confirm()

    def _rect_between(self, a: QPoint, b: QPoint) -> QRect:
        x = min(a.x(), b.x())
        y = min(a.y(), b.y())
        return QRect(x, y, abs(a.x() - b.x()), abs(a.y() - b.y()))

    def _clamp(self, rect: QRect) -> QRect:
        return rect.intersected(self.virtual_rect())

    def _resize(self, start: QRect, point: QPoint) -> QRect:
        left, top = start.x(), start.y()
        right, bottom = start.x() + start.width(), start.y() + start.height()
        handle = self.handle or ""
        min_size = self._min_size(point)
        if "l" in handle:
            left = min(point.x(), right - min_size)
        if "r" in handle:
            right = max(point.x(), left + min_size)
        if "t" in handle:
            top = min(point.y(), bottom - min_size)
        if "b" in handle:
            bottom = max(point.y(), top + min_size)
        rect = QRect(left, top, right - left, bottom - top)
        return rect.intersected(self.virtual_rect())

    # ---------- 阶段切换 ----------
    def confirm(self) -> None:
        if self.phase != "select":
            return
        if self.sel.isNull() or self.sel.width() <= 0 or self.sel.height() <= 0:
            return
        min_size = self._min_size(self.sel.center())
        if self.sel.width() < min_size or self.sel.height() < min_size:
            return
        self.phase = "collect"
        for w in self.masks:
            w.hide()
        for screen in self.screens:
            layer = FrameOverlay(self, screen)
            layer.show()
            self.frames.append(layer)
        QApplication.processEvents()
        for layer in self.frames:
            layer.sync_geometry()
        self._set_hint()
        self.refresh()
        self.confirmed.emit(QRect(self.sel))

    def request_cancel(self) -> None:
        if self.phase == "collect":
            return  # 采集阶段的 ESC 由采集器处理
        self.cancelled.emit()

    def set_stats(self, frames: int, height: int) -> None:
        self._stats = f"已采集 {frames} 帧 · 高度 {height} px"
        self._set_hint()

    def _set_hint(self) -> None:
        if self.hint is None:
            return
        if self.phase == "select":
            if self.sel.isNull() or self.sel.width() <= 0:
                self.hint.set_text("按住鼠标左键拖动框选区域　·　Esc 取消")
            else:
                self.hint.set_text("拖动边角调整选区　·　Enter 或双击开始采集　·　Esc 取消", self._stats)
        else:
            self.hint.set_text("滚动鼠标滚轮采集画面　·　Esc 取消　·　空格完成保存", self._stats)
        self._place_hint()

    def _place_hint(self) -> None:
        hint = self.hint
        if hint is None:
            return
        if self.sel.isNull() or self.sel.width() <= 0:
            screen = QGuiApplication.primaryScreen()
            geo = screen.geometry()
            hint.move(
                geo.x() + (geo.width() - hint.width()) // 2,
                geo.y() + 60,
            )
            hint.show()
            return

        gap = 10
        hw, hh = hint.width(), hint.height()
        sel = self.sel
        virtual = self.virtual_rect()
        candidates = [
            (sel.x(), sel.y() + sel.height() + gap),
            (sel.x(), sel.y() - hh - gap),
            (sel.x() + sel.width() + gap, sel.y()),
            (sel.x() - hw - gap, sel.y()),
        ]
        for px, py in candidates:
            rect = QRect(px, py, hw, hh)
            if virtual.contains(rect) and not rect.intersects(sel):
                logical = self.to_logical(QPoint(px, py))
                hint.move(logical)
                hint.show()
                return
        # 选区占满屏幕时无处可放，隐藏提示条（预览窗仍显示状态）
        hint.hide()

    def refresh(self) -> None:
        for w in self.masks:
            w.update()
        self._set_hint()

    def set_visible_for_settings(self, visible: bool) -> None:
        for w in self.masks:
            w.setVisible(visible)
        for w in self.frames:
            w.setVisible(visible)
        if self.hint is not None:
            self.hint.setVisible(visible)
        if visible:
            self.refresh()
            for w in self.masks:
                w.raise_()
