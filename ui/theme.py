"""Thème dark cohérent — v1.1 (fix boutons + layout)."""
from __future__ import annotations
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

_BG          = QColor("#111318")
_BG_ALT      = QColor("#161a22")
_BG_DARKER   = QColor("#0d1117")
_FG          = QColor("#e6edf3")
_FG_DIM      = QColor("#8b949e")
_BORDER      = QColor("#30363d")
_ACCENT      = QColor("#58a6ff")
_ACCENT_DARK = QColor("#1f6feb")
_WARN        = QColor("#ffb74d")
_ERROR       = QColor("#ef5350")
_OK          = QColor("#81c784")


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    for effect in (
        Qt.UI_AnimateMenu,
        Qt.UI_FadeMenu,
        Qt.UI_AnimateCombo,
        Qt.UI_AnimateTooltip,
        Qt.UI_FadeTooltip,
    ):
        app.setEffectEnabled(effect, False)

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
        QMainWindow, QDialog { background: #111318; }
        QMainWindow#OSCPToolkitMain { background: #111318; }

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
        QListWidget::item:hover, QTreeWidget::item:hover,
        QTableWidget::item:hover {
            background: #2a2a2d;
        }
        QTreeWidget::item, QListWidget::item { padding: 3px 4px; }
        QTableWidget { gridline-color: #2a2a2d; }
        QTableWidget::item { padding: 2px 4px; }

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
        QToolBar {
            background: #0d1117;
            border: 0;
            border-bottom: 1px solid #30363d;
            spacing: 3px;
            padding: 5px 4px;
        }
        QToolBar::separator { width: 1px; background: #30363d; margin: 3px 3px; }
        QMenuBar { background: #0d1117; color: #e6edf3; }
        QMenuBar::item:selected { background: #0288d1; color: white; }
        QMenu { background: #161a22; border: 1px solid #30363d; color: #e6edf3; }
        QMenu::item { padding: 5px 20px 5px 12px; }
        QMenu::item:selected { background: #0288d1; color: white; }
        QMenu::separator { height: 1px; background: #333; margin: 4px 8px; }

        /* ── Toolbar : 3 nuances pour distinguer les groupes ─── */
        /* (1) Boutons "primary" : actions de creation principales        *
         *     -> bleu nuance, fond legerement plus clair                 */
        QToolBar QToolButton#toolbar_primary {
            background: #17324d;
            color: #e6f6ff;
            border: 1px solid #2f81f7;
            border-radius: 3px;
            padding: 3px 8px;
            margin: 1px;
            min-height: 22px;
            min-width: 42px;
        }
        QToolBar QToolButton#toolbar_primary:hover {
            background: #1f4f78;
            border-color: #58a6ff;
        }
        QToolBar QToolButton#toolbar_primary:pressed {
            background: #58a6ff;
            color: #0d1117;
        }

        /* (2) Boutons "util" : actions secondaires (Encoder, Hash, etc.) *
         *     -> gris fonce, simple, neutre                              */
        QToolBar QToolButton#toolbar_util {
            background: #21262d;
            color: #e6edf3;
            border: 1px solid #30363d;
            border-radius: 3px;
            padding: 3px 8px;
            margin: 1px;
            min-height: 22px;
            min-width: 36px;
        }
        QToolBar QToolButton#toolbar_util:hover {
            background: #30363d;
            border-color: #8b949e;
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
        QStatusBar {
            background: #0d1117;
            color: #e6edf3;
            border-top: 1px solid #30363d;
        }

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
        QDockWidget { color: #e6edf3; }
        QDockWidget::title {
            text-align: left;
            background: #161a22;
            padding: 6px 8px;
            border-bottom: 1px solid #30363d;
            color: #e6edf3;
            font-weight: bold;
        }
        QDockWidget#dock_tools::title { border-left: 4px solid #58a6ff; }
        QDockWidget#dock_scope::title { border-left: 4px solid #7ee787; }
        QDockWidget#dock_notes::title { border-left: 4px solid #d2a8ff; }
        QDockWidget#dock_creds::title { border-left: 4px solid #ffa657; }
        QDockWidget#dock_docs::title { border-left: 4px solid #a5d6ff; }
        QDockWidget#dock_clipboard::title { border-left: 4px solid #f2cc60; }
        QDockWidget#dock_history::title { border-left: 4px solid #8b949e; }
        QDockWidget#dock_targets::title { border-left: 4px solid #ff7b72; }
        QDockWidget#dock_wordlists::title { border-left: 4px solid #f2cc60; }
        QDockWidget#dock_file_server::title { border-left: 4px solid #7ee787; }
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
            border: 1px solid #ff9800;
            border-radius: 4px;
            padding: 3px 10px;
            margin: 1px;
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
            border: 1px solid #ffa726;
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

        /* ── Accueil compact OSCP ───────────────────────────── */
        QWidget#welcomePage {
            background: #111318;
        }
        QWidget#welcomePage QLabel#welcomeTitle {
            color: #f3f4f6;
        }
        QWidget#welcomePage QLabel#welcomeSubtitle {
            color: #9e9e9e;
            font-size: 10pt;
        }
        QWidget#welcomePage QLabel#welcomeHint {
            color: #6f7680;
            font-size: 9pt;
        }
        QWidget#welcomePage QLabel#welcomePill {
            background: #161a22;
            color: #e6edf3;
            border: 1px solid #30363d;
            border-radius: 4px;
            padding: 4px 10px;
            font-weight: bold;
        }
        QPushButton#welcome_primary {
            background: #263847;
            border-color: #35566d;
            color: #e6f6ff;
            font-weight: bold;
        }
        QPushButton#welcome_primary:hover {
            background: #2f4a5e;
            border-color: #4fc3f7;
        }
        QPushButton#welcome_service {
            background: #332719;
            border-color: #8a5a16;
            color: #ffd89a;
            font-weight: bold;
        }
        QPushButton#welcome_service:hover {
            background: #47351d;
            border-color: #ffb74d;
        }
        QPushButton#welcome_util {
            background: #263b2c;
            border-color: #3d6b48;
            color: #dff5e3;
            font-weight: bold;
        }

        /* ── Terminal ───────────────────────────────────────── */
        QLabel#terminalFastBadge {
            background: #263b2c;
            color: #81c784;
            border: 1px solid #3d6b48;
            border-radius: 3px;
            padding: 1px 4px;
            font-size: 8pt;
            font-weight: bold;
        }

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
