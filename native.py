"""Win32 相关封装：物理像素坐标、截屏排除、单实例、开机自启。

程序进程由 Qt6 设置为 Per-Monitor V2 DPI 感知，因此这里的 Win32 坐标
与 mss 的抓屏坐标一致，都是「物理像素」。
"""
from __future__ import annotations

import ctypes
import os
import sys
import winreg
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WDA_MONITOR = 0x01
WDA_EXCLUDEFROMCAPTURE = 0x11

ERROR_ALREADY_EXISTS = 183

_mutex_handle = None


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """返回窗口在物理像素下的 (x, y, w, h)。"""
    if not hwnd:
        return None
    r = RECT()
    if not user32.GetWindowRect(wintypes.HWND(int(hwnd)), ctypes.byref(r)):
        return None
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def cursor_pos() -> tuple[int, int]:
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def exclude_from_capture(hwnd: int) -> bool:
    """让窗口不出现在截屏结果里（Win10 2004+）。"""
    if not hwnd:
        return False
    try:
        return bool(user32.SetWindowDisplayAffinity(wintypes.HWND(int(hwnd)), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def focus_window(hwnd: int) -> None:
    if hwnd:
        try:
            user32.SetForegroundWindow(wintypes.HWND(int(hwnd)))
        except Exception:
            pass


def acquire_single_instance(name: str = "LongShot_SingleInstance") -> bool:
    """返回 True 表示本次是第一个实例；False 表示已有实例在运行。"""
    global _mutex_handle
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    _mutex_handle = kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return f'"{sys.executable}" "{script}"'


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(enable: bool, value_name: str = "LongShot") -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, value_name)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False
