"""Scope Panel — arbre des subnets + machines + pivots.

Tree widget :
    Subnet 10.10.10.0/24 (external)
        ├── 10.10.10.10 — WEB01 (linux) [?]
        ├── 10.10.10.20 — DC01  (windows) [OK]
    Subnet 10.10.11.0/24 (internal) — via WEB01
        ├── ...

Actions :
- Ajouter subnet (CIDR validé)
- Ajouter machine (IP + hostname + OS)
- Toggle status (click droit → menu)
- Ajouter pivot (context menu sur une machine rootée)
- Définir la machine active (fiche courante)

Signaux émis vers main_window :
- machine_selected(machine)  → mise à jour status_bar / notes
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAction, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLineEdit, QMenu, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QComboBox,
)

from core.scope_manager import Machine, ScopeManager, STATUSES
from .dialogs import confirm, error_box


_STATUS_ICONS = {
    "todo": "[ ]",
    "in_progress": "[?]",
    "rooted": "[OK]",
    "skipped": "*",
}


class MachineEditDialog(QDialog):
    def __init__(self, machine: Optional[Machine] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Machine" if machine else "Nouvelle machine")
        self._ip = QLineEdit(machine.ip if machine else "")
        self._host = QLineEdit(machine.hostname if machine else "")
        self._os = QComboBox()
        self._os.addItems(["", "linux", "windows", "freebsd", "macos", "other"])
        if machine:
            idx = self._os.findText(machine.os)
            self._os.setCurrentIndex(idx if idx >= 0 else 0)
        self._status = QComboBox()
        self._status.addItems(STATUSES)
        if machine:
            self._status.setCurrentText(machine.status)
        self._difficulty = QComboBox()
        self._difficulty.addItems(["", "easy", "medium", "hard", "insane"])
        if machine:
            idx = self._difficulty.findText(machine.difficulty)
            self._difficulty.setCurrentIndex(idx if idx >= 0 else 0)

        form = QFormLayout(self)
        form.addRow("IP", self._ip)
        form.addRow("Hostname", self._host)
        form.addRow("OS", self._os)
        form.addRow("Status", self._status)
        form.addRow("Difficulté", self._difficulty)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {
            "ip": self._ip.text().strip(),
            "hostname": self._host.text().strip(),
            "os": self._os.currentText(),
            "status": self._status.currentText(),
            "difficulty": self._difficulty.currentText(),
        }


class ScopePanel(QWidget):
    machine_selected = pyqtSignal(object)      # Machine or None

    def __init__(self, scope_manager: ScopeManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._scope = scope_manager

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)

        actions = QHBoxLayout()
        btn_add_subnet = QPushButton("+ Subnet")
        btn_add_subnet.clicked.connect(self._on_add_subnet)
        btn_add_machine = QPushButton("+ Machine")
        btn_add_machine.clicked.connect(self._on_add_machine)
        actions.addWidget(btn_add_subnet)
        actions.addWidget(btn_add_machine)
        actions.addStretch()
        root.addLayout(actions)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Scope", "Status", "OS"])
        self._tree.setColumnWidth(0, 240)
        self._tree.setColumnWidth(1, 90)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self._tree, 1)

        self._scope.subnets_changed.connect(self._rebuild)
        self._scope.machines_changed.connect(self._rebuild)
        self._scope.pivots_changed.connect(self._rebuild)
        self._rebuild()

    # ----------------------------------------------------------

    def _rebuild(self) -> None:
        selected_mid = None
        if self._tree.currentItem() is not None:
            selected_mid = self._tree.currentItem().data(0, Qt.UserRole)

        self._tree.clear()
        # Group machines by subnet
        subnet_items = {}
        for s in self._scope.subnets():
            label = s.cidr + (f" - {s.label}" if s.label else "")
            if s.pivot_via:
                pv = self._scope.machine(s.pivot_via)
                via = (pv.hostname or pv.ip) if pv else s.pivot_via
                label += f"[via {via}]"
            item = QTreeWidgetItem([label, "", ""])
            f = item.font(0); f.setBold(True); item.setFont(0, f)
            item.setData(0, Qt.UserRole, f"subnet:{s.cidr}")
            subnet_items[s.cidr] = item
            self._tree.addTopLevelItem(item)
            item.setExpanded(True)

        # Orphan machines sans subnet
        orphan_item = QTreeWidgetItem(["Sans subnet", "", ""])
        orphan_item.setForeground(0, QColor("#777"))
        orphan_attached = False

        for m in self._scope.machines():
            parent = None
            for s in self._scope.subnets():
                if m.id in s.machines:
                    parent = subnet_items.get(s.cidr)
                    break
            if parent is None:
                parent = orphan_item
                orphan_attached = True
            status_label = _STATUS_ICONS.get(m.status, "?") + " " + m.status
            host = m.hostname or "?"
            line = f"{m.ip} - {host}"
            mitem = QTreeWidgetItem([line, status_label, m.os or ""])
            mitem.setData(0, Qt.UserRole, m.id)
            # couleur selon status
            if m.status == "rooted":
                mitem.setForeground(1, QColor("#2e7d32"))
            elif m.status == "in_progress":
                mitem.setForeground(1, QColor("#e67e00"))
            elif m.status == "skipped":
                mitem.setForeground(1, QColor("#777"))
            parent.addChild(mitem)

            if selected_mid == m.id:
                self._tree.setCurrentItem(mitem)

        if orphan_attached:
            self._tree.addTopLevelItem(orphan_item)

    # ---------- actions ----------

    def _on_add_subnet(self) -> None:
        cidr, ok = QInputDialog.getText(self, "Ajouter subnet", "CIDR (ex: 10.10.10.0/24) :")
        if not ok or not cidr.strip():
            return
        label, _ = QInputDialog.getText(self, "Label", "Label (facultatif) :")
        try:
            self._scope.add_subnet(cidr.strip(), label=label.strip())
        except ValueError as exc:
            error_box(self, "Subnet invalide", str(exc))

    def _on_add_machine(self) -> None:
        dlg = MachineEditDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        v = dlg.values()
        try:
            self._scope.add_machine(**v)
        except ValueError as exc:
            error_box(self, "Erreur", str(exc))

    def _on_selection_changed(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            self.machine_selected.emit(None)
            return
        data = item.data(0, Qt.UserRole)
        if not data or (isinstance(data, str) and data.startswith("subnet:")):
            self.machine_selected.emit(None)
            return
        m = self._scope.machine(data)
        self.machine_selected.emit(m)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.UserRole)
        if isinstance(data, str) and not data.startswith("subnet:"):
            m = self._scope.machine(data)
            if m:
                self._edit_machine(m)

    def _edit_machine(self, m: Machine) -> None:
        dlg = MachineEditDialog(machine=m, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            v = dlg.values()
            m.ip = v["ip"]
            m.hostname = v["hostname"]
            m.os = v["os"]
            m.difficulty = v["difficulty"]
            self._scope.update_machine(m)
            if v["status"] != m.status:
                self._scope.set_status(m.id, v["status"])

    def _on_context_menu(self, point) -> None:
        item = self._tree.itemAt(point)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        menu = QMenu(self)

        if isinstance(data, str) and data.startswith("subnet:"):
            cidr = data.split(":", 1)[1]
            rm = QAction("Supprimer subnet", self)
            rm.triggered.connect(lambda: self._scope.remove_subnet(cidr))
            menu.addAction(rm)
            menu.exec_(self._tree.viewport().mapToGlobal(point))
            return

        m = self._scope.machine(data)
        if m is None:
            return

        status_menu = menu.addMenu("Statut")
        for s in STATUSES:
            act = QAction(f"{_STATUS_ICONS[s]} {s}", self)
            act.setCheckable(True)
            act.setChecked(m.status == s)
            act.triggered.connect(lambda _=False, mid=m.id, st=s: self._scope.set_status(mid, st))
            status_menu.addAction(act)

        edit_act = QAction("Éditer...", self)
        edit_act.triggered.connect(lambda: self._edit_machine(m))
        menu.addAction(edit_act)

        pivot_act = QAction("+ Pivot depuis cette machine", self)
        pivot_act.triggered.connect(lambda: self._on_add_pivot(m))
        menu.addAction(pivot_act)

        del_act = QAction("Supprimer...", self)
        del_act.triggered.connect(lambda: self._on_delete_machine(m))
        menu.addAction(del_act)

        menu.exec_(self._tree.viewport().mapToGlobal(point))

    def _on_add_pivot(self, m: Machine) -> None:
        cidr, ok = QInputDialog.getText(
            self, "Pivot", f"CIDR accessible via {m.hostname or m.ip} :"
        )
        if not ok or not cidr.strip():
            return
        try:
            self._scope.add_subnet(cidr.strip(), label=f"via {m.hostname or m.ip}", pivot_via=m.id)
            self._scope.add_pivot(m.id, cidr.strip())
        except ValueError as exc:
            error_box(self, "Erreur", str(exc))

    def _on_delete_machine(self, m: Machine) -> None:
        if confirm(self, "Supprimer", f"Supprimer la machine {m.ip} ({m.hostname}) ?"):
            self._scope.remove_machine(m.id)
