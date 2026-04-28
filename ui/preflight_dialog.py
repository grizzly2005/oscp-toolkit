"""Preflight Dialog — affiche le rapport de run_preflight.

Mode bloquant : si `has_blocking_failure`, on n'offre QUE le bouton
"Quitter" (pas moyen de continuer).

Mode warning : résultats WARN affichés, bouton "Continuer" dispo, et
boutons spécifiques pour les actions proposées (kill orphelins,
restore session précédente, éditer IP manuellement).
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.preflight import PreflightReport, CheckResult


class PreflightDialog(QDialog):
    kill_orphans_requested = pyqtSignal()
    restore_session_requested = pyqtSignal()
    set_manual_ip_requested = pyqtSignal()

    def __init__(self, report: PreflightReport, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Pre-flight checks")
        self.setMinimumSize(760, 520)
        self._report = report

        layout = QVBoxLayout(self)

        # Résumé
        ok = sum(1 for r in report.results if r.passed)
        total = len(report.results)
        warnings = len(report.warnings)
        blocking = report.has_blocking_failure
        header = QLabel(
            f"<b>{ok}/{total}</b> checks OK - <b>{warnings}</b> warning(s)"
            + (" - <span style='color:#c62828'><b>BLOQUANT</b></span>" if blocking else "")
        )
        header.setTextFormat(Qt.RichText)
        layout.addWidget(header)

        # Tree des checks
        tree = QTreeWidget()
        tree.setHeaderLabels(["Check", "Statut", "Détails"])
        tree.setColumnWidth(0, 220)
        tree.setColumnWidth(1, 80)
        tree.setAlternatingRowColors(True)

        for r in report.results:
            item = QTreeWidgetItem([r.name, self._status_label(r), r.message])
            if not r.passed and r.blocking:
                item.setForeground(1, QColor("#c62828"))
            elif not r.passed:
                item.setForeground(1, QColor("#e67e00"))
            else:
                item.setForeground(1, QColor("#2e7d32"))

            details_parts = []
            if r.details:
                details_parts.append(r.details)
            if r.suggestion:
                details_parts.append(f"-> {r.suggestion}")
            if details_parts:
                sub = QTreeWidgetItem(["", "", "\n".join(details_parts)])
                sub.setFirstColumnSpanned(True)
                item.addChild(sub)
                item.setExpanded(not r.passed)
            tree.addTopLevelItem(item)
        layout.addWidget(tree)

        # Actions spécifiques selon payloads
        actions_row = QHBoxLayout()
        self._action_widgets: list[QWidget] = []

        for r in report.results:
            if r.name == "Process orphelins" and not r.passed and r.payload.get("orphans"):
                btn = QPushButton("[X] Kill orphelins")
                btn.clicked.connect(self.kill_orphans_requested)
                actions_row.addWidget(btn)
                self._action_widgets.append(btn)
            if r.name == "Session précédente" and r.payload.get("session_file"):
                btn = QPushButton("<- Restaurer session précédente")
                btn.clicked.connect(self.restore_session_requested)
                actions_row.addWidget(btn)
                self._action_widgets.append(btn)
            if r.name == "VPN / tun0" and not r.passed:
                btn = QPushButton(" IP attaquante manuelle...")
                btn.clicked.connect(self.set_manual_ip_requested)
                actions_row.addWidget(btn)
                self._action_widgets.append(btn)
        actions_row.addStretch()
        layout.addLayout(actions_row)

        # Mode dev : "skip les warnings"
        self._never_show_again = QCheckBox("Ne plus afficher ce dialog si tout est OK")
        layout.addWidget(self._never_show_again)

        # Boutons finaux
        final_row = QHBoxLayout()
        final_row.addStretch()
        quit_btn = QPushButton("Quitter")
        quit_btn.clicked.connect(self.reject)
        final_row.addWidget(quit_btn)

        if not blocking:
            cont_btn = QPushButton("Continuer ->")
            cont_btn.setDefault(True)
            cont_btn.clicked.connect(self.accept)
            final_row.addWidget(cont_btn)
        layout.addLayout(final_row)

    @staticmethod
    def _status_label(r: CheckResult) -> str:
        if r.passed:
            return "OK OK"
        return "X BLOQ" if r.blocking else "[!] WARN"

    def never_show_again(self) -> bool:
        return self._never_show_again.isChecked()
