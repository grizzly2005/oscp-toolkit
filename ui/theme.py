"""Thème dark cohérent — v1.1 (fix boutons + layout)."""
from __future__ import annotations
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

_BG          = QColor("#1e1e1e")
_BG_ALT      = QColor("#252526")
_BG_DARKER   = QColor("#181818")
_FG          = QColor("#d4d4d4")
_FG_DIM      = QColor("#9e9e9e")
_BORDER      = QColor("#333333")
_ACCENT      = QColor("#4fc3f7")
_ACCENT_DARK = QColor("#0288d1")
_WARN        = QColor("#ffb74d")
_ERROR       = QColor("#ef5350")
_OK          = QColor("#81c784")


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window,           _BG)
    palette.setColor(QPalette.WindowText,       _FG)
    palette.setColor(QPalette.Base,             _BG_DARKER)
    palette.setColor(QPalette.AlternateBase,    _BG_ALT)
    palette.setColor(QPalette.ToolTipBase,      _BG_ALT)
    palette.setColor(QPalette.ToolTipText,      _FG)
    palette.setColor(QPalette.Text,             _FG)
    palette.setColor(QPalette.Button,           _BG_ALT)
    palette.setColor(QPalette.ButtonText,       _FG)
    palette.setColor(QPalette.BrightText,       _ERROR)
    palette.setColor(QPalette.Link,             _ACCENT)
    palette.setColor(QPalette.Highlight,        _ACCENT_DARK)
    palette.setColor(QPalette.HighlightedText,  QColor("#ffffff"))
    palette.setColor(QPalette.Disabled, QPalette.Text,       _FG_DIM)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, _FG_DIM)
    palette.setColor(QPalette.Disabled, QPalette.WindowText, _FG_DIM)
    app.setPalette(palette)

    app.setStyleSheet("""
        /* ── Typographie globale ─────────────────────────────── */
        QWidget {
            font-family: "Segoe UI", "Noto Sans", "Cantarell", sans-serif;
            font-size: 10pt;
        }
        QMainWindow, QDialog { background: #1e1e1e; }

        /* ── Boutons ─────────────────────────────────────────── */
        /*
         * FIX v1.1 :
         *   - min-width + min-height explicites → hitbox == zone visible
         *   - max-height pour que le bouton ne grandisse pas en mode stretch
         *   - outline: none → retire le focus-rect qui décale le layout
         *   - qproperty-autoDefault: false → empêche l'activation accidentelle
         *     par Entrée dans un QDialog
         *   - border ne change PAS entre :hover et :pressed → pas de reflow
         */
        QPushButton {
            background: #2d2d30;
            border: 1px solid #3e3e42;
            border-radius: 4px;
            padding: 4px 12px;
            min-height: 24px;
            max-height: 28px;
            min-width: 36px;
            color: #d4d4d4;
            qproperty-autoDefault: false;
        }
        QPushButton:hover {
            background: #3e3e42;
            border-color: #4fc3f7;
            color: #ffffff;
        }
        QPushButton:pressed {
            background: #1a6898;
            border-color: #4fc3f7;
            color: #ffffff;
            /* padding identique → pas de décalage visuel */
            padding: 4px 12px;
        }
        QPushButton:disabled {
            color: #555;
            border-color: #2a2a2a;
            background: #252526;
        }
        QPushButton:focus {
            outline: none;
            border-color: #4fc3f7;
        }
        QPushButton:flat {
            background: transparent;
            border: none;
            min-width: 20px;
            padding: 2px 4px;
        }
        QPushButton:flat:hover {
            background: #3e3e42;
            border-radius: 3px;
        }
        QPushButton:flat:pressed {
            background: #0288d1;
        }

        /* ── Champs de saisie ────────────────────────────────── */
        QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser {
            background: #181818;
            color: #d4d4d4;
            border: 1px solid #333;
            border-radius: 3px;
            padding: 3px;
            selection-background-color: #0288d1;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
            border-color: #4fc3f7;
            outline: none;
        }

        /* ── Listes / Arbres / Tables ────────────────────────── */
        QListWidget, QTreeWidget, QTableWidget {
            background: #181818;
            border: 1px solid #333;
            alternate-background-color: #222;
            outline: none;
        }
        QListWidget::item:selected, QTreeWidget::item:selected,
        QTableWidget::item:selected {
            background: #0288d1;
            color: white;
        }
        QListWidget::item:hover, QTreeWidget::item:hover {
            background: #2a2a2d;
        }
        QTreeWidget::item, QListWidget::item { padding: 2px 0; }

        QHeaderView::section {
            background: #252526;
            color: #d4d4d4;
            padding: 4px;
            border: 0;
            border-right: 1px solid #333;
            border-bottom: 1px solid #333;
        }

        /* ── Onglets ─────────────────────────────────────────── */
        QTabWidget::pane { border: 1px solid #333; background: #1e1e1e; }
        QTabBar::tab {
            background: #252526;
            color: #9e9e9e;
            padding: 6px 14px;
            border: 1px solid #333;
            border-bottom: 0;
            min-width: 80px;
        }
        QTabBar::tab:selected {
            background: #1e1e1e;
            color: #4fc3f7;
            border-bottom: 2px solid #4fc3f7;
        }
        QTabBar::tab:hover:!selected { background: #2d2d30; color: #d4d4d4; }
        QTabBar::close-button {
            image: url(ui/icons/close_red.svg);
            subcontrol-position: right;
            padding: 2px;
            margin-right: 2px;
            width: 14px;
            height: 14px;
        }
        QTabBar::close-button:hover {
            image: url(ui/icons/close_red_hover.svg);
        }

        /* ── Toolbar / Menu ──────────────────────────────────── */
        QToolBar { background: #252526; border: 0; spacing: 4px; padding: 3px; }
        QToolBar::separator { width: 1px; background: #3e3e42; margin: 3px 2px; }
        QMenuBar { background: #252526; color: #d4d4d4; }
        QMenuBar::item:selected { background: #0288d1; color: white; }
        QMenu { background: #252526; border: 1px solid #333; color: #d4d4d4; }
        QMenu::item { padding: 5px 20px 5px 12px; }
        QMenu::item:selected { background: #0288d1; color: white; }
        QMenu::separator { height: 1px; background: #333; margin: 4px 8px; }

        /* ── Toolbar : 3 nuances pour distinguer les groupes ─── */
        /* (1) Boutons "primary" : actions de creation principales        *
         *     -> bleu nuance, fond legerement plus clair                 */
        QToolBar QToolButton#toolbar_primary {
            background: #2c4a5e;
            color: #eceff1;
            border: 1px solid #3a5e75;
            border-radius: 3px;
            padding: 4px 10px;
            margin: 1px 2px;
            min-height: 22px;
        }
        QToolBar QToolButton#toolbar_primary:hover {
            background: #365d77;
            border-color: #4fc3f7;
        }
        QToolBar QToolButton#toolbar_primary:pressed {
            background: #4fc3f7;
            color: #1e1e1e;
        }

        /* (2) Boutons "util" : actions secondaires (Encoder, Hash, etc.) *
         *     -> gris fonce, simple, neutre                              */
        QToolBar QToolButton#toolbar_util {
            background: #3a3a3d;
            color: #d4d4d4;
            border: 1px solid #4a4a4d;
            border-radius: 3px;
            padding: 4px 10px;
            margin: 1px 2px;
            min-height: 22px;
        }
        QToolBar QToolButton#toolbar_util:hover {
            background: #45454a;
            border-color: #5a5a5e;
        }
        QToolBar QToolButton#toolbar_util:pressed {
            background: #5a5a5e;
        }
        QToolBar QToolButton#toolbar_util:checked {
            background: #4fc3f7;
            color: #1e1e1e;
            border-color: #4fc3f7;
        }

        /* ── Barre de statut ─────────────────────────────────── */
        QStatusBar { background: #263238; color: #eceff1; }

        /* ── Scrollbars ──────────────────────────────────────── */
        QScrollBar:vertical {
            background: #1e1e1e; width: 10px; margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #3e3e42; min-height: 20px; border-radius: 5px;
            margin: 1px;
        }
        QScrollBar::handle:vertical:hover { background: #4fc3f7; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal {
            background: #1e1e1e; height: 10px; margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: #3e3e42; min-width: 20px; border-radius: 5px;
            margin: 1px;
        }
        QScrollBar::handle:horizontal:hover { background: #4fc3f7; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

        /* ── Dock ────────────────────────────────────────────── */
        QDockWidget { color: #d4d4d4; }
        QDockWidget::title {
            text-align: left; background: #252526;
            padding: 5px 8px; border-bottom: 1px solid #333;
        }
        QDockWidget::close-button, QDockWidget::float-button {
            border: none; background: transparent; padding: 2px;
            icon-size: 14px;
        }
        QDockWidget::close-button {
            image: url(ui/icons/close_red.svg);
        }
        QDockWidget::close-button:hover {
            image: url(ui/icons/close_red_hover.svg);
            background: transparent; border-radius: 2px;
        }
        QDockWidget::float-button:hover {
            background: #3e3e42; border-radius: 2px;
        }

        /* ── Boutons "service" toolbar (Listener / HTTP / Ligolo) ─── */
        /* Bordure orange permanente pour identifier les services
           reseau qui demarrent un process en arriere-plan. */
        QToolBar QToolButton#service_listener,
        QToolBar QToolButton#service_http,
        QToolBar QToolButton#service_ligolo {
            background: #2d2d30;
            color: #ffb74d;
            border: 2px solid #ff9800;
            border-radius: 4px;
            padding: 3px 10px;
            margin: 1px 2px;
            min-height: 22px;
            font-weight: bold;
        }
        QToolBar QToolButton#service_listener:hover,
        QToolBar QToolButton#service_http:hover,
        QToolBar QToolButton#service_ligolo:hover {
            background: #3a2a18;
            border-color: #ffa726;
            color: #ffe0b2;
        }
        QToolBar QToolButton#service_listener:pressed,
        QToolBar QToolButton#service_http:pressed,
        QToolBar QToolButton#service_ligolo:pressed {
            background: #ff9800;
            color: #1e1e1e;
        }
        /* Etat "ON" (checked) : fond orange plein -> visuel switch ON */
        QToolBar QToolButton#service_ligolo:checked {
            background: #ff9800;
            color: #1e1e1e;
            border: 2px solid #ffa726;
        }
        QToolBar QToolButton#service_ligolo:checked:hover {
            background: #ffa726;
            border-color: #ffb74d;
            color: #1e1e1e;
        }

        /* ── Splitter ────────────────────────────────────────── */
        QSplitter::handle { background: #2a2a2a; }
        QSplitter::handle:horizontal { width: 3px; }
        QSplitter::handle:vertical  { height: 3px; }
        QSplitter::handle:hover { background: #4fc3f7; }

        /* ── ComboBox ────────────────────────────────────────── */
        QComboBox {
            background: #2d2d30; border: 1px solid #3e3e42;
            border-radius: 3px; padding: 4px 8px;
            min-height: 24px;
        }
        QComboBox:hover { border-color: #4fc3f7; }
        QComboBox:focus { outline: none; border-color: #4fc3f7; }
        QComboBox QAbstractItemView {
            background: #252526; border: 1px solid #333;
            selection-background-color: #0288d1;
            outline: none;
        }
        QComboBox::drop-down { border: none; }

        /* ── Checkbox / Radio ────────────────────────────────── */
        QCheckBox::indicator, QRadioButton::indicator {
            width: 14px; height: 14px; border-radius: 2px;
        }
        QCheckBox::indicator:unchecked {
            background: #181818; border: 1px solid #555;
        }
        QCheckBox::indicator:checked {
            background: #4fc3f7; border: 1px solid #4fc3f7;
        }
        QRadioButton::indicator:unchecked {
            background: #181818; border: 1px solid #555; border-radius: 7px;
        }
        QRadioButton::indicator:checked {
            background: #4fc3f7; border: 1px solid #4fc3f7; border-radius: 7px;
        }

        /* ── GroupBox ────────────────────────────────────────── */
        QGroupBox {
            border: 1px solid #333; border-radius: 3px;
            margin-top: 12px; padding-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 10px; padding: 0 4px;
            color: #4fc3f7;
        }

        /* ── ProgressBar ─────────────────────────────────────── */
        QProgressBar {
            background: #181818; border: 1px solid #333;
            border-radius: 3px; text-align: center; color: #d4d4d4;
        }
        QProgressBar::chunk { background: #4fc3f7; border-radius: 2px; }

        /* ── Tooltip ─────────────────────────────────────────── */
        QToolTip {
            background: #252526; color: #d4d4d4;
            border: 1px solid #4fc3f7; padding: 4px;
            border-radius: 3px;
        }

        /* ── Dialogs ─────────────────────────────────────────── */
        QDialogButtonBox QPushButton { min-width: 80px; }
    """)
