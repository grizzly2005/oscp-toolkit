"""Env Dialog — UI pour editer les variables d'environnement de session.

Table editable des variables (cle=valeur).
Boutons "Pull LHOST" / "Pull TARGET" pour importer depuis scope/network.
Aucune action automatique : l'utilisateur pilote.
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.env_manager import EnvManager, DEFAULT_KEYS


class EnvDialog(QDialog):
    """Dialog d'edition des variables d'environnement."""

    def __init__(
        self,
        env_manager: EnvManager,
        suggested_lhost: str = "",
        suggested_target: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._env = env_manager
        self._suggested_lhost = suggested_lhost
        self._suggested_target = suggested_target

        self.setWindowTitle("Variables d'environnement - session OSCP")
        self.setMinimumSize(620, 480)

        root = QVBoxLayout(self)

        # Help
        help_label = QLabel(
            "Ces variables sont injectees dans chaque terminal externe "
            "(wt.exe / xterm) lance depuis le toolkit. Pilotage manuel - "
            "rien n'est modifie sans ton action."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color:#9e9e9e; padding:4px;")
        root.addWidget(help_label)

        # Import buttons
        import_row = QHBoxLayout()
        if suggested_lhost:
            btn_pull_lhost = QPushButton(f"<- LHOST depuis reseau ({suggested_lhost})")
            btn_pull_lhost.clicked.connect(self._pull_lhost)
            import_row.addWidget(btn_pull_lhost)
        if suggested_target:
            btn_pull_target = QPushButton(f"<- TARGET depuis scope ({suggested_target})")
            btn_pull_target.clicked.connect(self._pull_target)
            import_row.addWidget(btn_pull_target)
        import_row.addStretch()
        if import_row.count() > 0:
            root.addLayout(import_row)

        # Table
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Variable", "Valeur"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        font = QFont("Monospace")
        self._table.setFont(font)
        root.addWidget(self._table, 1)

        # Actions row
        actions = QHBoxLayout()
        btn_add = QPushButton("+ Ajouter variable")
        btn_add.clicked.connect(self._on_add)
        actions.addWidget(btn_add)

        btn_remove = QPushButton("- Retirer")
        btn_remove.clicked.connect(self._on_remove)
        actions.addWidget(btn_remove)

        btn_clear = QPushButton("Vider valeur")
        btn_clear.clicked.connect(self._on_clear_value)
        actions.addWidget(btn_clear)

        actions.addStretch()
        root.addLayout(actions)

        # Buttons
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._refresh()

    # -- Refresh -------------------------------------------------------------

    def _refresh(self) -> None:
        current = self._env.all()
        # DEFAULT_KEYS en premier, puis le reste
        keys = list(DEFAULT_KEYS) + sorted(k for k in current if k not in DEFAULT_KEYS)

        self._table.blockSignals(True)
        self._table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            key_item = QTableWidgetItem(key)
            if key in DEFAULT_KEYS:
                key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
                key_item.setForeground(Qt.cyan)
            self._table.setItem(row, 0, key_item)

            val_item = QTableWidgetItem(current.get(key, ""))
            self._table.setItem(row, 1, val_item)
        self._table.blockSignals(False)

    # -- Actions -------------------------------------------------------------

    def _on_add(self) -> None:
        key, ok = QInputDialog.getText(
            self, "Nouvelle variable", "Nom (ex: SHARE, CREDFILE) :"
        )
        if not ok or not key.strip():
            return
        try:
            self._env.set(key.strip().upper(), "")
            self._refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "Erreur", str(exc))

    def _on_remove(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        key = self._table.item(row, 0).text()
        if key in DEFAULT_KEYS:
            QMessageBox.information(
                self, "Info",
                f"'{key}' est une variable par defaut et ne peut pas etre supprimee. "
                f"Utilise 'Vider valeur' pour l'effacer."
            )
            return
        self._env.remove(key)
        self._refresh()

    def _on_clear_value(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        key = self._table.item(row, 0).text()
        self._env.clear_value(key)
        self._refresh()

    def _pull_lhost(self) -> None:
        for row in range(self._table.rowCount()):
            if self._table.item(row, 0).text() == "LHOST":
                self._table.item(row, 1).setText(self._suggested_lhost)
                return

    def _pull_target(self) -> None:
        for row in range(self._table.rowCount()):
            if self._table.item(row, 0).text() == "TARGET":
                self._table.item(row, 1).setText(self._suggested_target)
                return

    def _on_save(self) -> None:
        # Persiste toutes les valeurs du tableau
        try:
            for row in range(self._table.rowCount()):
                # Les cells peuvent etre None si jamais editees -> skip
                key_item = self._table.item(row, 0)
                val_item = self._table.item(row, 1)
                key = key_item.text().strip() if key_item else ""
                val = val_item.text().strip() if val_item else ""
                if key:
                    self._env.set(key, val)
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, "Erreur", str(exc))
