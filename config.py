"""配置读写：JSON 存放在 %APPDATA%\\LongShot\\config.json。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "LongShot"
APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"

DEFAULTS: dict[str, Any] = {
    "hotkey": "ctrl+shift+s",
    "jpg_quality": 90,
    "match_search_height": 200,
    "match_threshold": 0.80,
    "debounce_ms": 120,
    "reverse_scroll": False,
    "exclude_scrollbar": True,
    "max_height": 20000,
    "copy_to_clipboard": True,
    "save_dir": str(Path.home() / "Pictures" / APP_NAME),
    "filename_prefix": "longshot",
    "autostart": False,
}


class Config:
    def __init__(self) -> None:
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            if CONFIG_PATH.exists():
                # utf-8-sig 兼容记事本另存为带 BOM 的文件，否则会解析失败
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    for key, value in raw.items():
                        if key in DEFAULTS:
                            self._data[key] = value
        except Exception:
            # 配置损坏时回落到默认值，不影响启动
            self._data = dict(DEFAULTS)

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, values: dict[str, Any]) -> None:
        self._data.update(values)
