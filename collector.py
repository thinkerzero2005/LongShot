"""采集会话：监听滚轮、防抖抓帧、拼接、撤销、失败兜底。"""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

import mss
import numpy as np
from PyQt6.QtCore import QObject, QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

import stitcher

MAX_MEMORY_BYTES = 300 * 1024 * 1024


class CaptureWorker(QObject):
    """独立线程里抓屏 + 匹配，避免阻塞界面。"""

    frame_ready = pyqtSignal(int, object, int, float)
    grab_failed = pyqtSignal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._alive = True
        self._thread = threading.Thread(target=self._loop, name="capture-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, job_id: int, rect: dict, prev, search_h: int, threshold: float, exclude_right: int) -> None:
        if self._alive:
            self._queue.put((job_id, rect, prev, search_h, threshold, exclude_right))

    def stop(self) -> None:
        self._alive = False
        self._queue.put(None)

    def _loop(self) -> None:
        try:
            with mss.mss() as sct:
                while self._alive:
                    job = self._queue.get()
                    if job is None:
                        break
                    job_id, rect, prev, search_h, threshold, exclude_right = job
                    try:
                        raw = sct.grab(rect)
                        arr = np.asarray(raw, dtype=np.uint8)
                        rgb = np.ascontiguousarray(arr[:, :, [2, 1, 0]])
                        if stitcher.is_broken_frame(rgb):
                            self.grab_failed.emit(job_id, "当前画面无法截取（可能处于锁屏、UAC 或独占全屏）")
                            continue
                        if prev is None:
                            self.frame_ready.emit(job_id, rgb, 0, 1.0)
                        else:
                            skip, score = stitcher.match_offset(
                                prev, rgb, search_h, threshold, exclude_right
                            )
                            self.frame_ready.emit(job_id, rgb, skip, score)
                    except Exception as exc:
                        self.grab_failed.emit(job_id, f"抓取失败：{exc}")
        except Exception as exc:
            self.grab_failed.emit(-1, f"截屏服务初始化失败：{exc}")


class FrameCollector(QObject):
    canvas_changed = pyqtSignal(object)  # np.ndarray 视图
    stats_changed = pyqtSignal(int, int)  # 帧数, 高度
    finished = pyqtSignal()
    cancelled = pyqtSignal()
    notice = pyqtSignal(str, str)

    wheel_signal = pyqtSignal(int)
    key_signal = pyqtSignal(str)

    def __init__(self, cfg, rect: QRect, scale: float = 1.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._rect = rect
        self._scale = max(1.0, float(scale))
        self._max_h = int(cfg.get("max_height"))
        self._width = rect.width()

        self._frames: list[np.ndarray] = []
        self._skips: list[int] = []
        self._piece_hs: list[int] = []
        self._prev: Optional[np.ndarray] = None

        self._buf: Optional[np.ndarray] = None
        self._used = 0

        self._job = 0
        self._busy = False
        self._paused = False
        self._done = False
        self._fail_count = 0
        self._pending_dir = 0
        self._burst_start = 0.0
        self._last_key_at = 0.0
        self._memory_limit = MAX_MEMORY_BYTES

        self._worker = CaptureWorker()
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.grab_failed.connect(self._on_grab_failed)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(max(40, int(cfg.get("debounce_ms"))))
        self._debounce.timeout.connect(self._fire)

        self.wheel_signal.connect(self._on_wheel)
        self.key_signal.connect(self._on_key)

        self._mouse_listener = None
        self._key_listener = None

    # ---------- 生命周期 ----------
    @property
    def canvas(self) -> Optional[np.ndarray]:
        if self._buf is None or self._used <= 0:
            return None
        return self._buf[: self._used]

    def start(self) -> None:
        self._worker.start()
        self._start_listeners()
        QTimer.singleShot(140, self._capture_first)

    def stop(self) -> None:
        self._done = True
        self._debounce.stop()
        self._stop_listeners()
        self._worker.stop()

    def _start_listeners(self) -> None:
        try:
            from pynput import keyboard, mouse

            self._mouse_listener = mouse.Listener(on_scroll=self._pynput_scroll)
            self._mouse_listener.daemon = True
            self._mouse_listener.start()

            self._key_listener = keyboard.Listener(on_press=self._pynput_key)
            self._key_listener.daemon = True
            self._key_listener.start()
        except Exception as exc:
            self.notice.emit("无法监听鼠标滚轮", str(exc))

    def _stop_listeners(self) -> None:
        for listener in (self._mouse_listener, self._key_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._mouse_listener = None
        self._key_listener = None

    # ---------- 输入 ----------
    def _pynput_scroll(self, x, y, dx, dy) -> None:
        if dy == 0:
            return
        self.wheel_signal.emit(1 if dy > 0 else -1)

    def _pynput_key(self, key) -> None:
        try:
            from pynput import keyboard

            now = time.monotonic()
            if now - self._last_key_at < 0.25:
                return
            if key == keyboard.Key.esc:
                self._last_key_at = now
                self.key_signal.emit("esc")
            elif key == keyboard.Key.space:
                self._last_key_at = now
                self.key_signal.emit("space")
        except Exception:
            pass

    def _on_key(self, name: str) -> None:
        if self._done:
            return
        if name == "esc":
            self._cancel()
        elif name == "space":
            self._finish()

    def _on_wheel(self, direction: int) -> None:
        if self._done or self._paused:
            return
        if bool(self._cfg.get("reverse_scroll")):
            direction = -direction
        now = time.monotonic()
        if self._burst_start == 0.0:
            self._burst_start = now
        self._pending_dir = direction
        # 连续滚动时也不能一直等下去：超过 350ms 的持续滚动就立即抓一帧
        if now - self._burst_start >= 0.35 and not self._busy:
            self._debounce.stop()
            self._fire()
        else:
            self._debounce.start()

    def _fire(self) -> None:
        self._burst_start = 0.0
        if self._done or self._paused or self._pending_dir == 0:
            return
        direction, self._pending_dir = self._pending_dir, 0
        if direction < 0:
            self._capture()
        else:
            self._undo()

    # ---------- 抓帧 ----------
    def _mss_rect(self) -> dict:
        return {
            "left": int(self._rect.x()),
            "top": int(self._rect.y()),
            "width": int(self._rect.width()),
            "height": int(self._rect.height()),
        }

    def _capture_first(self) -> None:
        if self._done:
            return
        self._capture()

    def _capture(self) -> None:
        if self._done or self._paused or self._busy:
            return
        if self._memory_bytes() > self._memory_limit:
            self._pause_for_memory()
            return
        self._job += 1
        self._busy = True
        self._worker.submit(
            self._job,
            self._mss_rect(),
            self._prev,
            int(self._cfg.get("match_search_height")),
            float(self._cfg.get("match_threshold")),
            int(16 * self._scale) if self._cfg.get("exclude_scrollbar") else 0,
        )

    def _on_frame(self, job_id: int, frame: np.ndarray, skip: int, score: float) -> None:
        self._busy = False
        if self._done or job_id != self._job:
            return
        first = self._prev is None
        if not first:
            if score < 0:
                self._on_match_failure(frame, score)
                return
            if score < float(self._cfg.get("match_threshold")):
                self._on_match_failure(frame, score)
                return
        self._fail_count = 0
        self._prev = frame
        if skip >= frame.shape[0]:
            # 画面没有变化（没滚动或已到页面底部）
            return
        self._commit(frame, skip)

    def _commit(self, frame: np.ndarray, skip: int) -> None:
        piece = frame[skip:]
        if piece.shape[0] <= 0:
            return
        if self._used + piece.shape[0] > self._max_h:
            room = self._max_h - self._used
            if room <= 0:
                self._finish_by_cap()
                return
            piece = piece[:room]
        self._frames.append(frame)
        self._skips.append(int(skip))
        self._append_piece(piece)
        self._fail_count = 0
        self.canvas_changed.emit(self.canvas)
        self.stats_changed.emit(len(self._frames), self._used)
        if self._used >= self._max_h:
            self._finish_by_cap()

    def _append_piece(self, piece: np.ndarray) -> None:
        h = int(piece.shape[0])
        need = self._used + h
        if self._buf is None:
            capacity = min(max(2048, need), self._max_h)
            self._buf = np.empty((capacity, self._width, 3), dtype=np.uint8)
        elif need > self._buf.shape[0]:
            capacity = min(max(self._buf.shape[0] * 2, need), self._max_h)
            new_buf = np.empty((capacity, self._width, 3), dtype=np.uint8)
            new_buf[: self._used] = self._buf[: self._used]
            self._buf = new_buf
        self._buf[self._used : need] = piece
        self._used = need
        self._piece_hs.append(h)

    def _undo(self) -> None:
        if len(self._frames) <= 1 or self._busy:
            return
        self._frames.pop()
        self._skips.pop()
        removed = self._piece_hs.pop()
        self._used = max(0, self._used - removed)
        self._prev = self._frames[-1]
        self.canvas_changed.emit(self.canvas)
        self.stats_changed.emit(len(self._frames), self._used)

    def _memory_bytes(self) -> int:
        total = 0
        for frame in self._frames:
            total += int(frame.nbytes)
        if self._buf is not None:
            total += int(self._buf.nbytes)
        return total

    # ---------- 异常与兜底 ----------
    def _on_match_failure(self, frame: np.ndarray, score: float) -> None:
        self._fail_count += 1
        if self._fail_count >= 3:
            self._pause_ask(
                "连续多次匹配失败",
                "已连续 3 次未识别到重叠区域，采集已暂停。\n请放慢滚动速度，避开固定悬浮栏 / 动画区域。",
                retry_text="继续采集",
            )
            return
        self._paused = True
        box = QMessageBox()
        box.setWindowTitle("未识别重叠区域")
        box.setText("未识别重叠区域，请放慢滚动，避开固定悬浮栏 / 动画")
        score_text = f"相似度 {score:.2f}" if score >= 0 else "无法计算相似度"
        box.setInformativeText(f"{score_text} / 阈值 {float(self._cfg.get('match_threshold')):.2f}")
        force_btn = box.addButton("强制拼接", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("撤销本次采集", QMessageBox.ButtonRole.RejectRole)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()
        self._paused = False
        if box.clickedButton() is force_btn:
            self._prev = frame
            self._commit(frame, 0)
        self._fail_count = 0

    def _on_grab_failed(self, job_id: int, message: str) -> None:
        self._busy = False
        if self._done:
            return
        self.notice.emit("截图失败", message)
        self._abort()

    def _pause_for_memory(self) -> None:
        self._paused = True
        box = QMessageBox()
        box.setWindowTitle("内存占用过高")
        box.setText("截图数据占用内存过高，采集已暂停。")
        box.setInformativeText("建议结束本次采集并保存当前内容。")
        stop_btn = box.addButton("结束并保存", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("继续采集", QMessageBox.ButtonRole.RejectRole)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()
        self._paused = False
        if box.clickedButton() is stop_btn:
            self._finish()
        else:
            # 用户选择继续：抬高本轮阈值，避免刚关掉弹窗又被立刻拦下
            self._memory_limit = int(self._memory_limit * 1.5)
            self._capture()

    def _pause_ask(self, title: str, text: str, retry_text: str) -> None:
        self._paused = True
        box = QMessageBox()
        box.setWindowTitle(title)
        box.setText(text)
        retry_btn = box.addButton(retry_text, QMessageBox.ButtonRole.AcceptRole)
        box.addButton("结束并保存", QMessageBox.ButtonRole.RejectRole)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()
        self._paused = False
        if box.clickedButton() is retry_btn:
            self._fail_count = 0
        else:
            self._finish()

    def _finish_by_cap(self) -> None:
        if self._done:
            return
        self.notice.emit("已达到高度上限", f"长图高度上限 {self._max_h}px，已自动停止采集")
        self._finish()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._debounce.stop()
        self._stop_listeners()
        self._worker.stop()
        self.finished.emit()

    def _cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._debounce.stop()
        self._stop_listeners()
        self._worker.stop()
        self.cancelled.emit()

    def _abort(self) -> None:
        self._cancel()
