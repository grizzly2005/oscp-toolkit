"""Clipboard Manager Panel.

Liste des 50 derniers items (pins en haut), catégories auto
(IP / hash / URL / credential / command / text), recherche,
clic = recopie système.
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout,
    QWidget,
)

from core.clipboard_manager import ClipboardManager, ClipboardItem


_CATEGORY_COLOR = {
    "ip":         "#80deea",
    "hash":       "#ffb74d",
    "url":        "#b39ddb",
    "credential": "#f48fb1",
    "command":    "#a5d6a7",
    "multi":      "#bcaaa4",
    "text":       "#d4d4d4",
}

_CATEGORY_EMOJI = {
    "ip": "", "hash": "", "url": "",
    "credential": "", "command": "", "multi": "", "text": "",
}


class ClipboardPanel(QWidget):
    def __init__(self, manager: ClipboardManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._mgr = manager

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(" Filtrer...")
        self._search.textChanged.connect(self._refresh)
        bar.addWidget(self._search, 1)

        btn_capture = QPushButton(" Capture système")
        btn_capture.setToolTip("Capturer le contenu actuel du presse-papier système")
        btn_capture.clicked.connect(self._on_capture_system)
        bar.addWidget(btn_capture)

        btn_clear = QPushButton("")
        btn_clear.setToolTip("Nettoyer les non-pinnés")
        btn_clear.clicked.connect(self._on_clear)
        bar.addWidget(btn_clear)
        root.addLayout(bar)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self._list, 1)

        self._mgr.items_changed.connect(self._refresh)
        self._refresh()

    # ----------------------------------------------------------

    def _refresh(self) -> None:
        query = self._search.text().strip().lower()
        self._list.clear()
        for it in self._mgr.all():
            if query and query not in it.text.lower():
                continue
            display = self._format_item(it)
            row = QListWidgetItem(display)
            row.setData(Qt.UserRole, it.id)
            color = _CATEGORY_COLOR.get(it.category, "#d4d4d4")
            row.setForeground(QColor(color))
            if it.pinned:
                row.setText("[pin] " + row.text())
            row.setToolTip(it.text)
            row.setFont(QFont("Monospace", 9))
            self._list.addItem(row)

    @staticmethod
    def _format_item(it: ClipboardItem) -> str:
        emoji = _CATEGORY_EMOJI.get(it.category, "|")
        short = it.text.replace("\n", " <-| ")
        if len(short) > 80:
            short = short[:78] + "..."
        return f"{emoji} {short}"

    def _selected_item(self) -> Optional[ClipboardItem]:
        item = self._list.currentItem()
        if item is None:
            return None
        iid = item.data(Qt.UserRole)
        for c in self._mgr.all():
            if c.id == iid:
                return c
        return None

    # ----------------------------------------------------------

    def _on_double_click(self, _item) -> None:
        it = self._selected_item()
        if it is None:
            return
        QApplication.clipboard().setText(it.text)

    def _on_context_menu(self, point) -> None:
        it = self._selected_item()
        if it is None:
            return
        m = QMenu(self)
        m.addAction("Copier",
                    lambda: QApplication.clipboard().setText(it.text))
        m.addAction("[pin] Unpin" if it.pinned else "[pin] Pin",
                    lambda: self._mgr.toggle_pin(it.id))
        m.addSeparator()
        m.addAction(" Retirer", lambda: self._mgr.remove(it.id))
        m.exec_(self._list.viewport().mapToGlobal(point))

    def _on_capture_system(self) -> None:
        clip = QApplication.clipboard()
        text = clip.text()
        if text:
            self._mgr.capture(text, also_system=False)

    def _on_clear(self) -> None:
        self._mgr.clear_non_pinned()
