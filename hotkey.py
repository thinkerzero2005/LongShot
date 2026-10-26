"""全局快捷键：Win32 RegisterHotKey + 独立消息线程。

注册失败（错误码 1409）即说明被其它程序占用，天然满足「冲突检测」需求。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_APP_CMD = 0x8000 + 1
HOTKEY_ID = 0xB001
PROBE_ID = 0xB002
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_NAMED = {
    "space": 0x20,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "printscreen": 0x2C,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}
for _i in range(1, 13):
    _NAMED[f"f{_i}"] = 0x6F + _i

_VK_TO_NAME = {v: k for k, v in _NAMED.items()}
for _c in range(ord("A"), ord("Z") + 1):
    _VK_TO_NAME[_c] = chr(_c)
for _c in range(ord("0"), ord("9") + 1):
    _VK_TO_NAME[_c] = chr(_c)


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'ctrl+shift+s' -> (mods, vk)。无法解析返回 None。"""
    if not text:
        return None
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    vk = 0
    for part in parts:
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part == "alt":
            mods |= MOD_ALT
        elif part in ("win", "meta", "super"):
            mods |= MOD_WIN
        elif part in _NAMED:
            vk = _NAMED[part]
        elif len(part) == 1 and (part.isalpha() or part.isdigit()):
            vk = ord(part.upper())
        else:
            return None
    if not mods or not vk:
        return None
    return mods, vk


def hotkey_text(mods: int, vk: int) -> str:
    pieces = []
    if mods & MOD_CONTROL:
        pieces.append("ctrl")
    if mods & MOD_SHIFT:
        pieces.append("shift")
    if mods & MOD_ALT:
        pieces.append("alt")
    if mods & MOD_WIN:
        pieces.append("win")
    name = _VK_TO_NAME.get(vk, f"vk{vk}")
    pieces.append(name)
    return "+".join(pieces)


def pretty_hotkey(text: str) -> str:
    parsed = parse_hotkey(text)
    if not parsed:
        return text
    mods, vk = parsed
    labels = []
    if mods & MOD_CONTROL:
        labels.append("Ctrl")
    if mods & MOD_SHIFT:
        labels.append("Shift")
    if mods & MOD_ALT:
        labels.append("Alt")
    if mods & MOD_WIN:
        labels.append("Win")
    labels.append(_VK_TO_NAME.get(vk, "?").upper())
    return " + ".join(labels)


class HotkeyManager(QObject):
    activated = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()
        self._pending: list = []
        self._lock = threading.Lock()
        self._current: tuple[int, int] | None = None
        self._active_id = 0

    # ---------- 线程 ----------
    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="hotkey-loop", daemon=True)
        self._thread.start()
        self._ready.wait(3)

    def _run(self) -> None:
        self._tid = int(kernel32.GetCurrentThreadId())
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._ready.set()
        while True:
            ret = int(user32.GetMessageW(ctypes.byref(msg), None, 0, 0))
            if ret <= 0:
                break
            if msg.message == WM_HOTKEY:
                self.activated.emit()
            elif msg.message == WM_APP_CMD:
                self._drain()

    def _drain(self) -> None:
        with self._lock:
            jobs, self._pending = self._pending, []
        for job, box, done in jobs:
            try:
                box["result"] = job()
            except Exception as exc:  # pragma: no cover - 防御
                box["result"] = (False, str(exc))
            done.set()

    def _submit(self, job, timeout: float = 3.0):
        box: dict = {}
        done = threading.Event()
        with self._lock:
            self._pending.append((job, box, done))
        user32.PostThreadMessageW(self._tid, WM_APP_CMD, 0, 0)
        done.wait(timeout)
        return box.get("result")

    # ---------- 注册 ----------
    def bind(self, text: str) -> tuple[bool, str]:
        parsed = parse_hotkey(text)
        if not parsed:
            return False, "快捷键格式无效，请用 Ctrl / Shift / Alt / Win 组合一个按键"
        mods, vk = parsed
        if self._current == (mods, vk):
            return True, ""  # 已经在用这个组合键，无需重复注册

        def job():
            # 新组合键先注册到备用 ID 上，成功后才释放旧 ID，
            # 这样即使新键被占用，原来的快捷键依然有效。
            old_id = self._active_id
            new_id = PROBE_ID if old_id == HOTKEY_ID else HOTKEY_ID
            user32.UnregisterHotKey(None, new_id)
            if not user32.RegisterHotKey(None, new_id, mods | MOD_NOREPEAT, vk):
                err = ctypes.get_last_error()
                user32.UnregisterHotKey(None, new_id)
                return (False, err, None)
            if old_id and old_id != new_id:
                user32.UnregisterHotKey(None, old_id)
            return (True, 0, new_id)

        result = self._submit(job)
        if not result:
            return False, "快捷键注册超时，请重试"
        ok, err, new_id = result
        if not ok:
            if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                return False, f"{pretty_hotkey(text)} 已被其他程序占用，请更换"
            return False, f"快捷键注册失败（错误码 {err}），请更换"
        self._active_id = int(new_id)
        self._current = (mods, vk)
        return True, ""

    def shutdown(self) -> None:
        try:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            user32.UnregisterHotKey(None, PROBE_ID)
        except Exception:
            pass
