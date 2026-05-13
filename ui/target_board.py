"""Target Board — kanban simplifié des machines du scope.

4 colonnes : À faire / En cours / Rooted / Skip.
Drag & drop entre colonnes → met à jour le status dans ScopeManager.
Clic sur une machine → signal (la main_window ouvre la note).
"""
from __future__ import annotations

from typing import Dict, Optional

from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)

from core.scope_manager import ScopeManager, Machine, STATUSES


_STATUS_META: Dict[str, dict] = {
    "todo": {
        "label": "À faire", "tag": "TODO", "color": "#bcaaa4", "bg": "#292321",
    },
    "in_progress": {
        "label": "En cours", "tag": "RUN", "color": "#ffb74d", "bg": "#302719",
    },
    "rooted": {
        "label": "Rooted", "tag": "ROOT", "color": "#81c784", "bg": "#1f2d22",
    },
    "skipped": {
        "label": "Ignoré", "tag": "SKIP", "color": "#9e9e9e", "bg": "#252526",
    },
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
        self.setSpacing(4)
        self.setStyleSheet("""
            QListWidget {
                background: #181818;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item { border: none; }
            QListWidget::item:selected { background: #263f50; }
        """)

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


class _MachineCard(QWidget):
    def __init__(self, machine: Machine, status: str, parent=None):
        super().__init__(parent)
        meta = _STATUS_META.get(status, _STATUS_META["todo"])
        self.setObjectName("machineCard")
        self.setStyleSheet(
            "QWidget#machineCard {"
            f"background:{meta['bg']};"
            f"border-left:4px solid {meta['color']};"
            "border-top:1px solid #333;"
            "border-right:1px solid #333;"
            "border-bottom:1px solid #333;"
            "border-radius:4px;"
            "}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 5)
        root.setSpacing(3)

        top = QHBoxLayout()
        title = QLabel(machine.hostname or machine.ip or machine.id)
        title.setStyleSheet("color:#eceff1; font-weight:bold;")
        top.addWidget(title, 1)

        tag = QLabel(meta["tag"])
        tag.setAlignment(Qt.AlignCenter)
        tag.setStyleSheet(
            f"background:{meta['color']}; color:#101010; border-radius:3px; "
            "padding:1px 5px; font-size:8pt; font-weight:bold;"
        )
        top.addWidget(tag)
        root.addLayout(top)

        bits = []
        if machine.ip and machine.hostname:
            bits.append(machine.ip)
        if machine.os:
            bits.append(machine.os)
        if machine.difficulty:
            bits.append(machine.difficulty)
        if machine.points:
            bits.append(f"{machine.points} pts")
        detail = QLabel("  |  ".join(bits) if bits else "Aucun détail")
        detail.setStyleSheet("color:#9e9e9e; font-size:8pt;")
        root.addWidget(detail)

        if machine.status == "rooted" and not machine.proof.is_complete():
            warn = QLabel("Proof à compléter")
            warn.setStyleSheet("color:#ef5350; font-size:8pt; font-weight:bold;")
            root.addWidget(warn)


class TargetBoard(QWidget):
    machine_selected = pyqtSignal(object)        # Machine

    def __init__(self, scope: ScopeManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._scope = scope
        self._columns = {}         # status -> _StatusColumn
        self._headers: Dict[str, QLabel] = {}
        self._counts: Dict[str, int] = {s: 0 for s in STATUSES}
        self._pulse_on = False

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        for status in STATUSES:
            meta = _STATUS_META.get(status, _STATUS_META["todo"])
            col_container = QWidget()
            col_layout = QVBoxLayout(col_container)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(5)

            lbl = QLabel()
            lbl.setAlignment(Qt.AlignCenter)
            self._headers[status] = lbl
            col_layout.addWidget(lbl)

            lst = _StatusColumn(status)
            lst.itemDoubleClicked.connect(self._on_item_double_clicked)
            lst.status_changed.connect(self._on_status_changed)
            col_layout.addWidget(lst, 1)

            root.addWidget(col_container, 1)
            self._columns[status] = lst

        self._scope.machines_changed.connect(self._refresh)
        self._scope.machine_status_changed.connect(lambda *_: self._refresh())
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(800)
        self._pulse_timer.timeout.connect(self._pulse_active_header)
        self._pulse_timer.start()
        self._refresh()

    # ----------------------------------------------------------

    def _refresh(self) -> None:
        self._counts = {s: 0 for s in STATUSES}
        for col in self._columns.values():
            col.clear()
        for m in self._scope.machines():
            col = self._columns.get(m.status)
            if col is None:
                col = self._columns.get("todo")
            self._counts[m.status if m.status in self._counts else "todo"] += 1
            item = QListWidgetItem()
            item.setData(Qt.UserRole, m.id)
            item.setSizeHint(QSize(170, 62))
            item.setToolTip(
                f"IP: {m.ip}\nOS: {m.os}\nDifficulty: {m.difficulty}\n"
                f"Points: {m.points}"
            )
            col.addItem(item)
            col.setItemWidget(item, _MachineCard(m, m.status, col))
        for status, col in self._columns.items():
            if col.count() == 0:
                item = QListWidgetItem("Aucune cible")
                item.setFlags(Qt.NoItemFlags)
                item.setForeground(QColor("#666"))
                item.setTextAlignment(Qt.AlignCenter)
                col.addItem(item)
        self._refresh_headers()

    @staticmethod
    def _format_machine(m: Machine) -> str:
        tag = m.hostname or m.ip or m.id
        pts = f" [{m.points}]" if m.points else ""
        return f"{tag}{pts}"

    def _refresh_headers(self) -> None:
        for status, label in self._headers.items():
            self._apply_header_style(status, pulse=False)

    def _apply_header_style(self, status: str, pulse: bool = False) -> None:
        label = self._headers.get(status)
        if label is None:
            return
        meta = _STATUS_META.get(status, _STATUS_META["todo"])
        count = self._counts.get(status, 0)
        bg = "#3a2a18" if pulse and status == "in_progress" else "#252526"
        border = meta["color"] if count else "#333"
        label.setText(f"{meta['label']}  {count}")
        label.setStyleSheet(
            f"color:{meta['color']}; font-weight:bold; padding:5px; "
            f"background:{bg}; border:1px solid {border}; border-radius:4px;"
        )

    def _pulse_active_header(self) -> None:
        active = self._counts.get("in_progress", 0) > 0
        if not active:
            self._apply_header_style("in_progress", pulse=False)
            return
        self._pulse_on = not self._pulse_on
        self._apply_header_style("in_progress", pulse=self._pulse_on)

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
