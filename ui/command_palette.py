"""Command Palette — recherche globale type VSCode / Blender F3.

Ctrl+P ouvre un dialog modal avec :
  - champ de recherche
  - liste fuzzy-matched des actions (outils, notes, creds, commandes recentes)
  - flèches haut/bas pour naviguer
  - Entree pour executer

Sources :
  - Outils du ToolManager (charge via config/tools.json)
  - Notes existantes
  - Credentials (pour quick-paste dans le terminal actif)
  - Actions systeme (nouveau terminal, nouveau note, env dialog, etc.)
  - Machines du scope

Le fuzzy match utilise un simple sub-sequence scoring : chaque caractere
de la query doit apparaitre dans le label dans l'ordre. Score = proximite
des matchs. Pas de lib externe.

Integration :
  from ui.command_palette import CommandPalette
  palette = CommandPalette(main_window)
  QShortcut("Ctrl+P", main_window, palette.open)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (
    QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)
from .widgets import frozen_updates


_CATEGORY_ORDER = {
    "Action": 0,
    "Outil": 1,
    "Machine": 2,
    "Note": 3,
    "Cred": 4,
}


@dataclass
class PaletteAction:
    """Une action affichable dans la palette."""
    label: str
    category: str        # "Outil", "Note", "Cred", "Action", "Machine"
    callback: Callable[[], None]
    keywords: str = ""   # Mots-cles supplementaires pour le matching
    subtitle: str = ""   # Texte gris a droite

    def searchable_text(self) -> str:
        return f"{self.label} {self.keywords}".lower()


def _fuzzy_score(query: str, text: str) -> Optional[int]:
    """Retourne un score si query est un sous-sequence de text, sinon None.

    Score plus bas = meilleur match (distance entre les caracteres).
    None = pas de match.
    """
    if not query:
        return 0
    q = query.lower()
    t = text.lower()

    # Match exact = prioritaire
    if q in t:
        return 0 if t.startswith(q) else 1

    # Sub-sequence
    i = 0
    last_pos = -1
    total_gap = 0
    for c in q:
        pos = t.find(c, i)
        if pos < 0:
            return None
        if last_pos >= 0:
            total_gap += pos - last_pos - 1
        last_pos = pos
        i = pos + 1
    return 10 + total_gap


class CommandPalette(QDialog):
    """Palette de commandes globale."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setFixedSize(640, 420)
        self.setStyleSheet(
            "QDialog { background: #252526; border: 1px solid #4fc3f7; "
            "border-radius: 6px; }"
        )

        self._actions: List[PaletteAction] = []
        self._filtered: List[Tuple[int, PaletteAction]] = []
        self._query_timer = QTimer(self)
        self._query_timer.setSingleShot(True)
        self._query_timer.setInterval(60)
        self._query_timer.timeout.connect(
            lambda: self._on_query_changed(self._input.text())
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(6)

        # Header
        header = QLabel("Palette - tape pour chercher")
        header.setStyleSheet("color:#4fc3f7; font-weight:bold;")
        root.addWidget(header)

        # Input
        self._input = QLineEdit()
        self._input.setPlaceholderText("nmap, WS26, env, listener...")
        f = QFont()
        f.setPointSize(12)
        self._input.setFont(f)
        self._input.setStyleSheet(
            "QLineEdit { background:#1a1a1a; border:1px solid #333; "
            "padding:6px; border-radius:3px; color:#eee; }"
            "QLineEdit:focus { border-color:#4fc3f7; }"
        )
        self._input.textChanged.connect(lambda _text: self._query_timer.start())
        self._input.returnPressed.connect(self._execute_current)
        root.addWidget(self._input)

        # Liste
        self._list = QListWidget()
        self._list.setIconSize(QSize(16, 16))
        self._list.setStyleSheet(
            "QListWidget { background:#1a1a1a; border:1px solid #333; "
            "outline:none; }"
            "QListWidget::item { padding:6px 8px; }"
            "QListWidget::item:selected { background:#0288d1; color:white; }"
            "QListWidget::item:hover { background:#2a2a2d; }"
        )
        self._list.itemActivated.connect(lambda _: self._execute_current())
        self._list.itemDoubleClicked.connect(lambda _: self._execute_current())
        root.addWidget(self._list, 1)

        # Footer
        footer = QLabel(
            "<span style='color:#777;font-size:9pt;'>"
            "Entree = executer &nbsp;|&nbsp; ^v = naviguer &nbsp;|&nbsp; "
            "Echap = fermer"
            "</span>"
        )
        root.addWidget(footer)

    # -- Public API ----------------------------------------------------------

    def set_actions(self, actions: List[PaletteAction]) -> None:
        """Definit la liste complete des actions. Appele juste avant open()."""
        self._actions = list(actions)

    def open(self) -> None:
        self._input.clear()
        self._on_query_changed("")
        self.show()
        self._input.setFocus()
        # Centre sur le parent
        parent = self.parent()
        if parent and hasattr(parent, 'geometry'):
            pg = parent.geometry()
            x = pg.x() + (pg.width() - self.width()) // 2
            y = pg.y() + max(60, (pg.height() - self.height()) // 3)
            self.move(x, y)

    # -- Query ---------------------------------------------------------------

    def _on_query_changed(self, text: str) -> None:
        text = text.strip()
        scored: List[Tuple[int, PaletteAction]] = []
        for act in self._actions:
            if not text:
                scored.append((0, act))
                continue
            sc = _fuzzy_score(text, act.searchable_text())
            if sc is not None:
                scored.append((sc, act))

        scored.sort(key=lambda x: (
            x[0],
            _CATEGORY_ORDER.get(x[1].category, 99),
            x[1].label.lower(),
        ))
        if not text:
            # Limite a 50 pour la perf
            scored = scored[:50]
        self._filtered = scored

        with frozen_updates(self._list):
            self._list.clear()
            cat_colors = {
                "Outil":   "#4fc3f7",
                "Note":    "#81c784",
                "Cred":    "#ffb74d",
                "Action":  "#ef5350",
                "Machine": "#ba68c8",
            }
            for _score, act in scored:
                item = QListWidgetItem()
                label = act.label
                cat = act.category
                color = cat_colors.get(cat, "#9e9e9e")
                # QListWidget ne gere pas le HTML simple via setText,
                # on met texte brut + colorisation via data.
                item.setText(f"[{cat}]  {label}{('  - ' + act.subtitle) if act.subtitle else ''}")
                item.setForeground(QColor(color))
                item.setData(Qt.UserRole, act)
                self._list.addItem(item)

            if self._list.count() > 0:
                self._list.setCurrentRow(0)

    # -- Keys ---------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.key() == Qt.Key_Down:
            row = self._list.currentRow()
            if row < self._list.count() - 1:
                self._list.setCurrentRow(row + 1)
            return
        if event.key() == Qt.Key_Up:
            row = self._list.currentRow()
            if row > 0:
                self._list.setCurrentRow(row - 1)
            return
        super().keyPressEvent(event)

    def _execute_current(self) -> None:
        if self._query_timer.isActive():
            self._query_timer.stop()
            self._on_query_changed(self._input.text())
        item = self._list.currentItem()
        if not item:
            return
        act: PaletteAction = item.data(Qt.UserRole)
        self.accept()
        try:
            act.callback()
        except Exception:
            from core.logger import get_logger
            get_logger(__name__).exception("Palette action failed: %s", act.label)
