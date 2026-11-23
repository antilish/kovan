"""KOVAN koyu teması (bal rengi vurgu)."""

BG = "#0e1116"
SIDEBAR = "#12161d"
SURFACE = "#151a22"
FIELD = "#0f141b"
BORDER = "#232c39"
TEXT = "#e6e9ef"
MUTED = "#8b95a5"
ACCENT = "#f6b73c"
GOOD = "#3ecf8e"
BAD = "#ef5b5b"
INFO = "#4aa3ff"

STYLE = f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog, QMessageBox, QWidget#root, QWidget#page {{ background: {BG}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid #1c2430; }}
QLabel#logo {{ font-size: 22px; font-weight: 800; color: {ACCENT}; letter-spacing: 1px; }}
QLabel#tagline {{ color: {MUTED}; font-size: 11px; }}
QPushButton#nav {{ text-align: left; padding: 11px 14px; border: none; border-radius: 9px;
                   color: #9aa5b5; background: transparent; font-size: 14px; }}
QPushButton#nav:hover {{ background: #1a212b; color: {TEXT}; }}
QPushButton#nav:checked {{ background: #2a2414; color: {ACCENT}; font-weight: 600; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#card[state="offline"] {{ border-color: #2a3038; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 24px; font-weight: 700; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#stat {{ font-size: 30px; font-weight: 700; }}
QLabel#icon {{ font-size: 26px; }}
QLabel#code {{ font-family: "Consolas", "Cascadia Mono", monospace; font-size: 34px; font-weight: 700;
               letter-spacing: 4px; color: {ACCENT}; }}
QLabel#mono {{ font-family: "Consolas", "Cascadia Mono", monospace; color: {MUTED}; }}
QLabel#good {{ color: {GOOD}; font-weight: 600; }}
QLabel#bad {{ color: {BAD}; font-weight: 600; }}
QLabel#bench {{ font-size: 26px; font-weight: 700; color: {ACCENT}; }}
QLabel#banner {{ background: #1c2430; border-radius: 10px; padding: 12px 14px; }}
QLabel#banner[ok="true"] {{ background: #12261f; color: {GOOD}; }}

QPushButton {{ background: #222b38; border: 1px solid #2d3848; border-radius: 9px; padding: 8px 16px; }}
QPushButton:hover {{ background: #2a3545; }}
QPushButton:pressed {{ background: #1b2330; }}
QPushButton#primary {{ background: {ACCENT}; color: #1a1405; border: none; font-weight: 700; }}
QPushButton#primary:hover {{ background: #ffc857; }}
QPushButton#primary * {{ color: #1a1405; }}
QToolButton {{ background: transparent; border: none; color: {MUTED}; padding: 2px 6px; border-radius: 6px; }}
QToolButton:hover {{ background: #2a3038; color: {BAD}; }}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
  background: {FIELD}; border: 1px solid #2a3340; border-radius: 9px; padding: 7px 10px;
  selection-background-color: {ACCENT}; selection-color: #1a1405; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: #2a2414; }}

QTableWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
                alternate-background-color: #181e27; gridline-color: transparent; outline: none; }}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QTableWidget::item:selected {{ background: #2a2414; color: {TEXT}; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none;
                        border-bottom: 1px solid {BORDER}; padding: 9px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

QProgressBar {{ background: {FIELD}; border: none; border-radius: 4px; min-height: 8px; max-height: 8px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QProgressBar[level="good"]::chunk {{ background: {GOOD}; }}
QProgressBar[level="bad"]::chunk {{ background: {BAD}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a3340; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: #2a3340; border-radius: 4px; }}
QToolTip {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px 8px; }}
"""


def apply_theme(app) -> None:
    app.setStyleSheet(STYLE)
