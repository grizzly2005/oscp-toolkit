"""FindBar — barre de recherche Ctrl+F reutilisable.

A encastrer en bas d'un QPlainTextEdit. Highlight les occurrences,
navigation next/prev, indicateur "5/42".

Usage :
  bar = FindBar(text_widget)
  layout.addWidget(bar)
  QShortcut("Ctrl+F", parent, bar.show_and_focus)
  QShortcut("Escape", bar.line_edit, bar.hide)
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QWidget,
)


class FindBar(QWidget):
    """Barre de recherche en bas d'un QPlainTextEdit."""

    closed = pyqtSignal()

    def __init__(self, target: QPlainTextEdit, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._target = target
        self._matches: List[int] = []      # positions de debut de chaque match
        self._current_idx: int = -1
        self._last_query: str = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Find:"))

        self._input = QLineEdit()
        self._input.setPlaceholderText("Rechercher dans le terminal...")
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self.find_next)
        layout.addWidget(self._input, 1)

        self._counter = QLabel("0/0")
        self._counter.setMinimumWidth(50)
        self._counter.setStyleSheet("color:#9e9e9e;")
        layout.addWidget(self._counter)

        self._case_cb = QCheckBox("Aa")
        self._case_cb.setToolTip("Case sensitive")
        self._case_cb.stateChanged.connect(lambda: self._update_matches())
        layout.addWidget(self._case_cb)

        btn_prev = QPushButton("^")
        btn_prev.setFixedSize(24, 22)
        btn_prev.setToolTip("Occurrence precedente (Shift+Entree)")
        btn_prev.clicked.connect(self.find_prev)
        layout.addWidget(btn_prev)

        btn_next = QPushButton("v")
        btn_next.setFixedSize(24, 22)
        btn_next.setToolTip("Occurrence suivante (Entree)")
        btn_next.clicked.connect(self.find_next)
        layout.addWidget(btn_next)

        btn_close = QPushButton("x")
        btn_close.setFixedSize(22, 22)
        btn_close.setToolTip("Fermer (Echap)")
        btn_close.clicked.connect(self.hide_and_clear)
        layout.addWidget(btn_close)

        self.setStyleSheet(
            "FindBar { background:#252526; border-top:1px solid #333; }"
            "QLineEdit { background:#181818; }"
        )
        self.hide()

    # -- API -----------------------------------------------------------------

    def show_and_focus(self) -> None:
        """Affiche la bar, selectionne le texte en cours dans target si court."""
        sel = self._target.textCursor().selectedText()
        if sel and len(sel) < 100 and "\u2029" not in sel:
            self._input.setText(sel)
            self._input.selectAll()
        self.show()
        self._input.setFocus()

    def hide_and_clear(self) -> None:
        """Ferme + retire les highlights."""
        self._clear_highlights()
        self.hide()
        self._target.setFocus()
        self.closed.emit()

    def find_next(self) -> None:
        if not self._matches:
            return
        self._current_idx = (self._current_idx + 1) % len(self._matches)
        self._jump_to_current()

    def find_prev(self) -> None:
        if not self._matches:
            return
        self._current_idx = (self._current_idx - 1) % len(self._matches)
        self._jump_to_current()

    # -- Internal ------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        if text != self._last_query:
            self._last_query = text
            self._update_matches()

    def _update_matches(self) -> None:
        self._clear_highlights()
        self._matches = []
        self._current_idx = -1

        query = self._input.text()
        if not query:
            self._counter.setText("0/0")
            return

        doc = self._target.document()
        text = doc.toPlainText()
        if not self._case_cb.isChecked():
            needle = query.lower()
            haystack = text.lower()
        else:
            needle = query
            haystack = text

        idx = 0
        while True:
            pos = haystack.find(needle, idx)
            if pos < 0:
                break
            self._matches.append(pos)
            idx = pos + max(1, len(needle))

        self._paint_highlights(len(query))

        if self._matches:
            self._current_idx = 0
            self._jump_to_current()
            self._counter.setText(f"1/{len(self._matches)}")
        else:
            self._counter.setText("0/0")

    def _paint_highlights(self, length: int) -> None:
        """Highlight toutes les occurrences via extraSelections."""
        extras = list(self._target.extraSelections() or [])
        # Retire nos anciens highlights si presents (on utilise une propriete)
        extras = [s for s in extras if not getattr(s.format, '_findbar', False)]

        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#3a5c85"))
        fmt.setForeground(QColor("#ffffff"))

        from PyQt5.QtWidgets import QTextEdit
        for pos in self._matches:
            sel = QTextEdit.ExtraSelection()
            cursor = self._target.textCursor()
            cursor.setPosition(pos)
            cursor.setPosition(pos + length, QTextCursor.KeepAnchor)
            sel.cursor = cursor
            sel.format = fmt
            sel.format._findbar = True  # type: ignore[attr-defined]
            extras.append(sel)

        self._target.setExtraSelections(extras)

    def _clear_highlights(self) -> None:
        extras = list(self._target.extraSelections() or [])
        extras = [s for s in extras if not getattr(s.format, '_findbar', False)]
        self._target.setExtraSelections(extras)

    def _jump_to_current(self) -> None:
        if not (0 <= self._current_idx < len(self._matches)):
            return
        pos = self._matches[self._current_idx]
        cursor = self._target.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + len(self._input.text()), QTextCursor.KeepAnchor)
        self._target.setTextCursor(cursor)
        self._target.ensureCursorVisible()
        self._counter.setText(f"{self._current_idx + 1}/{len(self._matches)}")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide_and_clear()
            return
        if event.key() == Qt.Key_Return and event.modifiers() & Qt.ShiftModifier:
            self.find_prev()
            return
        super().keyPressEvent(event)
