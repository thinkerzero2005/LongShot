"""保存对话框与设置面板。"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import config as config_mod
import native
from hotkey import hotkey_text, pretty_hotkey


def qimage_from_array(canvas: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(canvas)
    return QImage(
        arr.data,
        arr.shape[1],
        arr.shape[0],
        int(arr.strides[0]),
        QImage.Format.Format_RGB888,
    ).copy()


def unique_path(directory: str, stem: str, ext: str) -> str:
    path = Path(directory) / f"{stem}{ext}"
    index = 1
    while path.exists():
        path = Path(directory) / f"{stem}({index}){ext}"
        index += 1
    return str(path)


class SaveDialog(QDialog):
    """保存长图：格式、JPG 画质、剪贴板、目录。"""

    def __init__(self, cfg, canvas: np.ndarray, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.canvas = canvas
        self.saved_path = ""
        self.copied = False
        self._directory = str(cfg.get("save_dir"))

        self.setWindowTitle("保存长截图")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(620)

        h, w = canvas.shape[:2]
        prefix = str(cfg.get("filename_prefix") or "longshot")
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._default_name = f"{prefix}_{stamp}"

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(14)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body)

        thumb = QLabel()
        thumb.setFixedSize(200, 300)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet("background:#26292d;border:1px solid #34383d;border-radius:8px;")
        pixmap = QPixmap.fromImage(qimage_from_array(canvas))
        thumb.setPixmap(
            pixmap.scaled(
                196,
                296,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        body.addWidget(thumb)

        right = QVBoxLayout()
        right.setSpacing(10)
        body.addLayout(right, 1)

        info = QLabel(f"尺寸　{w} × {h} px")
        info.setStyleSheet("color:#a9adb2;")
        right.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addLayout(form)

        self.name_edit = QLineEdit(self._default_name)
        form.addRow("文件名", self.name_edit)

        dir_row = QHBoxLayout()
        self.dir_label = QLabel()
        self.dir_label.setStyleSheet("color:#c6c9cd;")
        dir_row.addWidget(self.dir_label, 1)
        browse = QPushButton("更改…")
        browse.clicked.connect(self._choose_dir)
        dir_row.addWidget(browse)
        form.addRow("目录", dir_row)

        self.format_box = QComboBox()
        self.format_box.addItem("PNG（无损）", "png")
        self.format_box.addItem("JPG", "jpg")
        self.format_box.currentIndexChanged.connect(self._on_format_changed)
        form.addRow("格式", self.format_box)

        quality_row = QHBoxLayout()
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(70, 100)
        self.quality_spin.setValue(int(cfg.get("jpg_quality")))
        self.quality_spin.setSuffix(" %")
        quality_row.addWidget(self.quality_spin)
        hint = QLabel("仅 JPG 生效")
        hint.setStyleSheet("color:#7f858c;")
        quality_row.addWidget(hint)
        quality_row.addStretch(1)
        form.addRow("画质", quality_row)

        self.copy_box = QCheckBox("保存同时复制到系统剪贴板")
        self.copy_box.setChecked(bool(cfg.get("copy_to_clipboard")))
        right.addWidget(self.copy_box)
        right.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._do_save)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self._refresh_dir_label()
        self._on_format_changed()

    # ---------- 交互 ----------
    def _refresh_dir_label(self) -> None:
        text = self._directory
        metrics = self.dir_label.fontMetrics()
        available = max(120, self.width() - 330)
        self.dir_label.setText(metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, available))
        self.dir_label.setToolTip(text)

    def _choose_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择保存目录", self._directory)
        if chosen:
            self._directory = chosen
            self._refresh_dir_label()

    def _on_format_changed(self) -> None:
        is_jpg = self.format_box.currentData() == "jpg"
        self.quality_spin.setEnabled(is_jpg)

    def _do_save(self) -> None:
        fmt = self.format_box.currentData()
        ext = ".png" if fmt == "png" else ".jpg"
        stem = (self.name_edit.text().strip() or self._default_name)
        stem = os.path.splitext(stem)[0] or self._default_name
        try:
            directory = Path(self._directory)
            directory.mkdir(parents=True, exist_ok=True)
            path = unique_path(str(directory), stem, ext)
            image = Image.fromarray(np.ascontiguousarray(self.canvas))
            if fmt == "png":
                image.save(path, "PNG", compress_level=4)
            else:
                image.convert("RGB").save(
                    path,
                    "JPEG",
                    quality=int(self.quality_spin.value()),
                    subsampling=1,
                    optimize=True,
                )
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"无法保存文件：\n{exc}")
            return

        self.saved_path = path
        if self.copy_box.isChecked():
            try:
                from PyQt6.QtWidgets import QApplication

                QApplication.clipboard().setImage(qimage_from_array(self.canvas))
                self.copied = True
            except Exception:
                self.copied = False

        self.cfg.set("jpg_quality", int(self.quality_spin.value()))
        self.cfg.set("save_dir", str(self._directory))
        self.cfg.set("copy_to_clipboard", self.copy_box.isChecked())
        try:
            self.cfg.save()
        except Exception:
            pass
        self.accept()


class HotkeyEdit(QPushButton):
    """点击后录制新的全局快捷键。"""

    captured = pyqtSignal(str)

    def __init__(self, value: str) -> None:
        super().__init__(pretty_hotkey(value))
        self._value = value
        self._recording = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self._begin)

    def value(self) -> str:
        return self._value

    def _begin(self) -> None:
        self._recording = True
        self.setText("请按下新的快捷键…")
        self.setFocus()
        self.grabKeyboard()

    def _end(self, commit: bool) -> None:
        self._recording = False
        self.releaseKeyboard()
        self.setText(pretty_hotkey(self._value))
        if commit:
            self.captured.emit(self._value)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not self._recording:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._end(False)
            return
        if key in (
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
            Qt.Key.Key_unknown,
        ):
            return
        vk = _qt_key_to_vk(key)
        if vk is None:
            self.setText("请使用字母 / 数字 / F1-F12")
            return
        mods = 0
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            mods |= 0x0002
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            mods |= 0x0004
        if modifiers & Qt.KeyboardModifier.AltModifier:
            mods |= 0x0001
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            mods |= 0x0008
        if mods == 0:
            self.setText("必须包含 Ctrl / Shift / Alt / Win")
            return
        self._value = hotkey_text(mods, vk)
        self._end(True)


def _qt_key_to_vk(key: int) -> int | None:
    if 0x41 <= key <= 0x5A or 0x30 <= key <= 0x39:
        return key
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        return 0x70 + (int(key) - int(Qt.Key.Key_F1))
    return None


class SettingsDialog(QDialog):
    def __init__(self, cfg, apply_hotkey, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._apply_hotkey = apply_hotkey
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(12)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # ---- 快捷键 ----
        hotkey_tab = QWidget()
        hotkey_layout = QFormLayout(hotkey_tab)
        hotkey_layout.setContentsMargins(16, 18, 16, 16)
        hotkey_layout.setSpacing(12)
        self.hotkey_edit = HotkeyEdit(str(cfg.get("hotkey")))
        hotkey_layout.addRow("开始截图", self.hotkey_edit)
        tip = QLabel("点击按钮后按下新的组合键；若已被其他程序占用会提示更换。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b9096;")
        hotkey_layout.addRow("", tip)
        tabs.addTab(hotkey_tab, "快捷键")

        # ---- 采集 ----
        capture_tab = QWidget()
        capture_layout = QFormLayout(capture_tab)
        capture_layout.setContentsMargins(16, 18, 16, 16)
        capture_layout.setSpacing(12)

        self.search_spin = QSpinBox()
        self.search_spin.setRange(60, 1200)
        self.search_spin.setSingleStep(20)
        self.search_spin.setSuffix(" px")
        self.search_spin.setValue(int(cfg.get("match_search_height")))
        capture_layout.addRow("重叠匹配搜索高度", self.search_spin)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.50, 0.99)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(float(cfg.get("match_threshold")))
        capture_layout.addRow("匹配相似度阈值", self.threshold_spin)

        self.debounce_spin = QSpinBox()
        self.debounce_spin.setRange(40, 600)
        self.debounce_spin.setSingleStep(10)
        self.debounce_spin.setSuffix(" ms")
        self.debounce_spin.setValue(int(cfg.get("debounce_ms")))
        capture_layout.addRow("滚轮防抖间隔", self.debounce_spin)

        self.reverse_box = QCheckBox("反转滚轮方向（向下滚=撤销，向上滚=采集）")
        self.reverse_box.setChecked(bool(cfg.get("reverse_scroll")))
        capture_layout.addRow("", self.reverse_box)

        self.scrollbar_box = QCheckBox("匹配时忽略选区右侧滚动条区域")
        self.scrollbar_box.setChecked(bool(cfg.get("exclude_scrollbar")))
        capture_layout.addRow("", self.scrollbar_box)

        self.max_height_spin = QSpinBox()
        self.max_height_spin.setRange(2000, 50000)
        self.max_height_spin.setSingleStep(1000)
        self.max_height_spin.setSuffix(" px")
        self.max_height_spin.setValue(int(cfg.get("max_height")))
        capture_layout.addRow("长图高度上限", self.max_height_spin)
        tabs.addTab(capture_tab, "采集")

        # ---- 保存 ----
        save_tab = QWidget()
        save_layout = QFormLayout(save_tab)
        save_layout.setContentsMargins(16, 18, 16, 16)
        save_layout.setSpacing(12)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(70, 100)
        self.quality_spin.setSuffix(" %")
        self.quality_spin.setValue(int(cfg.get("jpg_quality")))
        save_layout.addRow("JPG 默认画质", self.quality_spin)

        self.copy_box = QCheckBox("保存后默认复制到剪贴板")
        self.copy_box.setChecked(bool(cfg.get("copy_to_clipboard")))
        save_layout.addRow("", self.copy_box)

        self.prefix_edit = QLineEdit(str(cfg.get("filename_prefix")))
        save_layout.addRow("文件名前缀", self.prefix_edit)

        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(str(cfg.get("save_dir")))
        self.dir_edit.setReadOnly(True)
        dir_row.addWidget(self.dir_edit, 1)
        choose = QPushButton("更改…")
        choose.clicked.connect(self._choose_dir)
        dir_row.addWidget(choose)
        save_layout.addRow("保存目录", dir_row)
        tabs.addTab(save_tab, "保存")

        # ---- 其他 ----
        other_tab = QWidget()
        other_layout = QFormLayout(other_tab)
        other_layout.setContentsMargins(16, 18, 16, 16)
        other_layout.setSpacing(12)
        self.autostart_box = QCheckBox("开机自动启动")
        self.autostart_box.setChecked(bool(cfg.get("autostart")))
        other_layout.addRow("", self.autostart_box)
        version = QLabel("滚动长截图工具　v1.0")
        version.setStyleSheet("color:#8b9096;")
        other_layout.addRow("", version)
        tabs.addTab(other_tab, "其他")

        buttons = QHBoxLayout()
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self._restore_defaults)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("保存")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        buttons.addWidget(ok)
        root.addLayout(buttons)

    # ---------- 交互 ----------
    def _choose_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择保存目录", self.dir_edit.text())
        if chosen:
            self.dir_edit.setText(chosen)

    def _restore_defaults(self) -> None:
        defaults = config_mod.DEFAULTS
        self.hotkey_edit._value = defaults["hotkey"]
        self.hotkey_edit.setText(pretty_hotkey(defaults["hotkey"]))
        self.search_spin.setValue(int(defaults["match_search_height"]))
        self.threshold_spin.setValue(float(defaults["match_threshold"]))
        self.debounce_spin.setValue(int(defaults["debounce_ms"]))
        self.reverse_box.setChecked(bool(defaults["reverse_scroll"]))
        self.scrollbar_box.setChecked(bool(defaults["exclude_scrollbar"]))
        self.max_height_spin.setValue(int(defaults["max_height"]))
        self.quality_spin.setValue(int(defaults["jpg_quality"]))
        self.copy_box.setChecked(bool(defaults["copy_to_clipboard"]))
        self.prefix_edit.setText(str(defaults["filename_prefix"]))
        self.dir_edit.setText(str(defaults["save_dir"]))
        self.autostart_box.setChecked(bool(defaults["autostart"]))

    def _save(self) -> None:
        hotkey = self.hotkey_edit.value()
        ok, message = self._apply_hotkey(hotkey)
        if not ok:
            QMessageBox.warning(self, "快捷键不可用", message)
            return
        self.cfg.update(
            {
                "hotkey": hotkey,
                "match_search_height": int(self.search_spin.value()),
                "match_threshold": round(float(self.threshold_spin.value()), 2),
                "debounce_ms": int(self.debounce_spin.value()),
                "reverse_scroll": self.reverse_box.isChecked(),
                "exclude_scrollbar": self.scrollbar_box.isChecked(),
                "max_height": int(self.max_height_spin.value()),
                "jpg_quality": int(self.quality_spin.value()),
                "copy_to_clipboard": self.copy_box.isChecked(),
                "filename_prefix": self.prefix_edit.text().strip() or "longshot",
                "save_dir": self.dir_edit.text().strip() or str(config_mod.DEFAULTS["save_dir"]),
                "autostart": self.autostart_box.isChecked(),
            }
        )
        try:
            self.cfg.save()
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", f"配置写入失败：{exc}")
        native.set_autostart(bool(self.autostart_box.isChecked()))
        self.accept()
