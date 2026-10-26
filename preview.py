"""采集过程中的实时长图预览窗（不抢焦点，可拖动查看）。"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import native

PADDING = 8
HEADER_H = 30
FOOTER_H = 28


class PreviewWindow(QWidget):
    def __init__(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self._canvas: Optional[np.ndarray] = None
        self._frames = 0
        self._height = 0
        self._follow = True
        self._last_top = 0
        self._press_y = 0
        self._press_top = 0
        self._dragging = False

    def sync_capture(self) -> None:
        native.exclude_from_capture(int(self.winId()))

    def update_canvas(self, canvas) -> None:
        self._canvas = canvas
        self.update()

    def set_stats(self, frames: int, height: int) -> None:
        self._frames = frames
        self._height = height

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(QColor(20, 21, 24, 242))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        p.setFont(QFont("Microsoft YaHei UI", 9))
        p.setPen(QColor(230, 233, 238))
        p.drawText(
            QRectF(PADDING, 6, self.width() - 2 * PADDING, HEADER_H - 10),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "长图预览",
        )

        area = QRectF(
            PADDING,
            HEADER_H,
            self.width() - 2 * PADDING,
            max(10, self.height() - HEADER_H - FOOTER_H),
        )
        canvas = self._canvas
        if canvas is not None and canvas.size > 0:
            src_h, src_w = canvas.shape[:2]
            scale = area.width() / max(1, src_w)
            view_src_h = max(1, min(src_h, int(area.height() / max(scale, 1e-6))))
            max_top = max(0, src_h - view_src_h)
            top = max_top if self._follow else int(max(0, min(max_top, self._last_top)))
            self._last_top = top
            chunk = canvas[top : top + view_src_h]
            if chunk.size > 0:
                chunk = np.ascontiguousarray(chunk)
                image = QImage(
                    chunk.data,
                    chunk.shape[1],
                    chunk.shape[0],
                    int(chunk.strides[0]),
                    QImage.Format.Format_RGB888,
                )
                target = QRectF(
                    area.x(),
                    area.y(),
                    area.width(),
                    min(area.height(), view_src_h * scale),
                )
                p.drawImage(target, image)
                p.setPen(QPen(QColor(255, 255, 255, 26), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(area)
        else:
            p.setPen(QColor(140, 145, 152))
            p.drawText(area, int(Qt.AlignmentFlag.AlignCenter), "等待采集…")

        p.setFont(QFont("Microsoft YaHei UI", 8))
        p.setPen(QColor(150, 156, 164))
        p.drawText(
            QRectF(PADDING, self.height() - FOOTER_H, self.width() - 2 * PADDING, FOOTER_H - 6),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"{self._frames} 帧 · {self._height} px",
        )

    # ---------- 拖动 ----------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._press_y = event.position().y()
        self._press_top = self._last_top
        self._follow = False
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging or self._canvas is None:
            return
        src_h, src_w = self._canvas.shape[:2]
        area_w = max(1, self.width() - 2 * PADDING)
        area_h = max(1, self.height() - HEADER_H - FOOTER_H)
        scale = area_w / max(1, src_w)
        view_src_h = max(1, min(src_h, int(area_h / max(scale, 1e-6))))
        max_top = max(0, src_h - view_src_h)
        delta = (event.position().y() - self._press_y) / max(scale, 1e-6)
        self._last_top = int(max(0, min(max_top, self._press_top - delta)))
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
