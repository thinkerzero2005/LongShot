"""深色主题（Fusion + 暗色调色板 + 少量 QSS）。"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

QSS = """
QDialog, QMessageBox { background-color: #1e1f22; }
QLabel { color: #e3e5e8; }
QPushButton {
    background-color: #2d3136; color: #e8eaed;
    border: 1px solid #3c4148; border-radius: 6px;
    padding: 6px 16px; min-height: 20px;
}
QPushButton:hover { background-color: #383d43; }
QPushButton:pressed { background-color: #232629; }
QPushButton:disabled { color: #6b7075; }
QPushButton#primary {
    background-color: #2f7cf6; border: 1px solid #2f7cf6; color: #ffffff;
}
QPushButton#primary:hover { background-color: #4a8ff8; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #26292d; border: 1px solid #3c4148; border-radius: 6px;
    padding: 5px 8px; color: #e8eaed; selection-background-color: #2f7cf6;
}
QComboBox QAbstractItemView {
    background: #26292d; border: 1px solid #3c4148;
    selection-background-color: #2f7cf6; color: #e8eaed;
}
QTabWidget::pane { border: 1px solid #34383d; border-radius: 8px; top: -1px; }
QTabBar::tab {
    background: transparent; padding: 8px 16px; color: #a9adb2; border: 0;
}
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #2f7cf6; }
QGroupBox {
    border: 1px solid #34383d; border-radius: 8px;
    margin-top: 12px; padding-top: 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #a9adb2; }
QSlider::groove:horizontal { height: 4px; background: #3a3f45; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #2f7cf6; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #2f7cf6; width: 14px; margin: -6px 0; border-radius: 7px;
}
QCheckBox { color: #e8eaed; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #4a5056; background: #26292d;
}
QCheckBox::indicator:checked { background: #2f7cf6; border-color: #2f7cf6; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #454a51; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(30, 31, 34))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(232, 234, 237))
    pal.setColor(QPalette.ColorRole.Base, QColor(37, 39, 43))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(44, 46, 50))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(44, 46, 50))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(232, 234, 237))
    pal.setColor(QPalette.ColorRole.Text, QColor(232, 234, 237))
    pal.setColor(QPalette.ColorRole.Button, QColor(45, 48, 53))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(232, 234, 237))
    pal.setColor(QPalette.ColorRole.BrightText, QColor(255, 90, 90))
    pal.setColor(QPalette.ColorRole.Link, QColor(80, 160, 255))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(47, 124, 246))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 145, 150))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
