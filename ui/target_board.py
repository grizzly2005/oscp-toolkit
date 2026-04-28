"""Target Board — kanban simplifié des machines du scope.

4 colonnes : À faire / En cours / Rooted / Skip.
Drag & drop entre colonnes → met à jour le status dans ScopeManager.
Clic sur une machine → signal (la main_window ouvre la note).
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)

from core.scope_manager import ScopeManager, Machine, STATUSES


_STATUS_META = {
    "todo":        (" À faire",    "#bcaaa4"),
    "in_progress": (" En cours",   "#ffb74d"),
    "rooted":      ("[OK] Rooted",     "#81c784"),
    "skipped":     ("-> Ignoré",     "#9e9e9e"),
}


class _StatusColumn(QListWidget):
    status_changed = pyqtSignal(str, str)    # machine_id, new_status

    def __init__(self, status: str, parent=None):
        super().__init__(parent)
        self.status = status
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setAcceptDrops(True)

    def dropEvent(self, event):
        # Récupère l'item drag source + machine_id
        source = event.source()
        if source is None or not isinstance(source, _StatusColumn):
            return super().dropEvent(event)
        if source is self:
            return super().dropEvent(event)

        item = source.currentItem()
        if item is None:
            return super().dropEvent(event)
        mid = item.data(Qt.UserRole)
        if not mid:
            return super().dropEvent(event)

        # Accepter le drop : supprimer de la source, ajouter ici, émettre signal
        row = source.row(item)
        source.takeItem(row)
        new_item = QListWidgetItem(item.text())
        new_item.setData(Qt.UserRole, mid)
        self.addItem(new_item)
        event.accept()
        self.status_changed.emit(mid, self.status)


class TargetBoard(QWidget):
    machine_selected = pyqtSignal(object)        # Machine

    def __init__(self, scope: ScopeManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._scope = scope
        self._columns = {}         # status -> _StatusColumn

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        for status in STATUSES:
            label, color = _STATUS_META.get(status, (status, "#ccc"))
            col_container = QWidget()
            col_layout = QVBoxLayout(col_container)
            col_layout.setContentsMargins(0, 0, 0, 0)

            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"color:{color}; font-weight:bold; padding:4px; "
                f"background:#252526; border:1px solid #333; border-radius:3px;"
            )
            col_layout.addWidget(lbl)

            lst = _StatusColumn(status)
            lst.itemDoubleClicked.connect(self._on_item_double_clicked)
            lst.status_changed.connect(self._on_status_changed)
            col_layout.addWidget(lst, 1)

            root.addWidget(col_container, 1)
            self._columns[status] = lst

        self._scope.machines_changed.connect(self._refresh)
        self._scope.machine_status_changed.connect(lambda *_: self._refresh())
        self._refresh()

    # ----------------------------------------------------------

    def _refresh(self) -> None:
        for col in self._columns.values():
            col.clear()
        for m in self._scope.machines():
            col = self._columns.get(m.status)
            if col is None:
                col = self._columns.get("todo")
            label = self._format_machine(m)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, m.id)
            item.setToolTip(
                f"IP: {m.ip}\nOS: {m.os}\nDifficulty: {m.difficulty}\n"
                f"Points: {m.points}"
            )
            if m.status == "rooted" and not m.proof.is_complete():
                item.setForeground(QColor("#ef5350"))       # signale proof manquante
            col.addItem(item)

    @staticmethod
    def _format_machine(m: Machine) -> str:
        tag = m.hostname or m.ip or m.id
        pts = f" [{m.points}]" if m.points else ""
        return f"{tag}{pts}"

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        mid = item.data(Qt.UserRole)
        m = self._scope.machine(mid)
        if m is not None:
            self.machine_selected.emit(m)

    def _on_status_changed(self, machine_id: str, new_status: str) -> None:
        try:
            self._scope.set_status(machine_id, new_status)
        except Exception as exc:
            from ui.dialogs import error_box
            error_box(self, "Erreur", str(exc))
            self._refresh()
