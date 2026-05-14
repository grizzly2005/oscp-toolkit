"""Credential Vault Panel.

Table : user | secret (mot de passe ou hash) | type | source | cible.
Actions : ajouter, modifier, supprimer, copier user/pass/hash en 1 clic.
Filtres : source, type, hash_type.
Exports : users.txt, passwords.txt, hashes.txt (pour john/hashcat).
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMenu, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from core.credential_vault import CredentialVault, Credential
from .widgets import frozen_updates


class _CredEditDialog(QDialog):
    def __init__(self, cred: Optional[Credential] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Credential" if cred else "Nouveau credential")
        self._cred = cred

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._user = QLineEdit(cred.username if cred else "")
        form.addRow("Username :", self._user)
        self._domain = QLineEdit(cred.domain if cred else "")
        form.addRow("Domain :", self._domain)
        self._pass = QLineEdit(cred.password if cred else "")
        form.addRow("Password :", self._pass)
        self._hash = QLineEdit(cred.hash if cred else "")
        form.addRow("Hash :", self._hash)
        self._hash_type = QLineEdit(cred.hash_type if cred else "")
        self._hash_type.setPlaceholderText("ex: NTLM, SHA256, bcrypt...")
        form.addRow("Hash type :", self._hash_type)
        self._source = QLineEdit(cred.source if cred else "")
        self._source.setPlaceholderText("ex: WEB01")
        form.addRow("Source :", self._source)
        self._target = QLineEdit(cred.target if cred else "*")
        self._target.setPlaceholderText("* = multi-cibles")
        form.addRow("Cible :", self._target)
        self._notes = QTextEdit(cred.notes if cred else "")
        self._notes.setMaximumHeight(80)
        form.addRow("Notes :", self._notes)
        layout.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def to_credential(self) -> Credential:
        if self._cred is not None:
            c = self._cred
            c.username = self._user.text().strip()
            c.domain = self._domain.text().strip()
            c.password = self._pass.text()
            c.hash = self._hash.text().strip()
            c.hash_type = self._hash_type.text().strip()
            c.source = self._source.text().strip()
            c.target = self._target.text().strip() or "*"
            c.notes = self._notes.toPlainText().strip()
            return c
        return Credential.new(
            username=self._user.text().strip(),
            domain=self._domain.text().strip(),
            password=self._pass.text(),
            hash=self._hash.text().strip(),
            hash_type=self._hash_type.text().strip(),
            source=self._source.text().strip(),
            target=self._target.text().strip() or "*",
            notes=self._notes.toPlainText().strip(),
            type=("ntlm" if self._hash_type.text().strip().upper() in ("NTLM", "NT")
                  else "password" if self._pass.text() else "hash"),
        )


class CredentialPanel(QWidget):
    def __init__(self, vault: CredentialVault, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._vault = vault

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # --- Barre d'actions ---
        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(" Filtrer...")
        self._search.textChanged.connect(self._refresh)
        bar.addWidget(self._search, 1)

        btn_add = QPushButton("+")
        btn_add.setToolTip("Ajouter")
        btn_add.clicked.connect(self._on_add)
        bar.addWidget(btn_add)

        btn_export = QPushButton("")
        btn_export.setToolTip("Exporter users/passwords/hashes pour hashcat/john")
        btn_export.clicked.connect(self._on_export_menu)
        bar.addWidget(btn_export)

        root.addLayout(bar)

        # --- Table ---
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["User", "Secret", "Type", "Source", "Cible", ""])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        root.addWidget(self._table, 1)

        # Wire vault signals
        self._vault.vault_changed.connect(self._refresh)
        self._refresh()

    # ----------------------------------------------------------

    def _refresh(self) -> None:
        query = self._search.text().strip().lower()
        creds: List[Credential] = self._vault.all()
        if query:
            creds = [c for c in creds if self._match(c, query)]

        with frozen_updates(self._table):
            self._table.setRowCount(0)
            for c in creds:
                row = self._table.rowCount()
                self._table.insertRow(row)

                user = c.username + (f"@{c.domain}" if c.domain else "")
                self._table.setItem(row, 0, QTableWidgetItem(user or "-"))

                secret = c.password if c.password else self._short_hash(c.hash)
                secret_item = QTableWidgetItem(secret or "-")
                if c.hash and not c.password:
                    secret_item.setForeground(QColor("#ffb74d"))   # hash en orange
                self._table.setItem(row, 1, secret_item)

                t = c.hash_type if c.hash else c.type
                self._table.setItem(row, 2, QTableWidgetItem(t))

                self._table.setItem(row, 3, QTableWidgetItem(c.source or "-"))
                self._table.setItem(row, 4, QTableWidgetItem(c.target or "*"))

                # Col copier
                copy_item = QTableWidgetItem("")
                copy_item.setTextAlignment(Qt.AlignCenter)
                copy_item.setToolTip("Double-clic = copier user:secret")
                self._table.setItem(row, 5, copy_item)

                # On stocke l'ID sur le premier item
                self._table.item(row, 0).setData(Qt.UserRole, c.id)

            if self._table.rowCount() < 250:
                self._table.resizeColumnsToContents()

    @staticmethod
    def _match(c: Credential, q: str) -> bool:
        hay = " ".join([
            c.username, c.domain, c.password, c.hash, c.hash_type,
            c.source, c.target, c.notes,
        ]).lower()
        return q in hay

    @staticmethod
    def _short_hash(h: str) -> str:
        return h if len(h) <= 32 else h[:14] + "..." + h[-12:]

    def _selected_cred(self) -> Optional[Credential]:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        cid = item.data(Qt.UserRole)
        return self._vault.get(cid)

    # ----------------------------------------------------------

    def _on_context_menu(self, point) -> None:
        cred = self._selected_cred()
        if cred is None:
            return
        menu = QMenu(self)
        menu.addAction("Copier le username",
                       lambda: self._copy(cred.username))
        menu.addAction("Copier le password",
                       lambda: self._copy(cred.password))
        menu.addAction("Copier le hash",
                       lambda: self._copy(cred.hash))
        menu.addAction(f"Copier {cred.username}:{self._short_hash(cred.display_secret())}",
                       lambda: self._copy(f"{cred.username}:{cred.display_secret()}"))
        menu.addSeparator()
        menu.addAction("Modifier...", self._on_edit)
        menu.addAction("Supprimer", self._on_remove)
        menu.exec_(self._table.viewport().mapToGlobal(point))

    def _on_double_click(self, row: int, col: int) -> None:
        cred = self._selected_cred()
        if cred is None:
            return
        if col == 5:       # colonne copier
            self._copy(f"{cred.username}:{cred.display_secret()}")
        else:
            self._on_edit()

    def _on_add(self) -> None:
        dlg = _CredEditDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            try:
                self._vault.add(dlg.to_credential())
            except Exception as exc:
                from ui.dialogs import error_box
                error_box(self, "Erreur", str(exc))

    def _on_edit(self) -> None:
        cred = self._selected_cred()
        if cred is None:
            return
        dlg = _CredEditDialog(cred=cred, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._vault.update(dlg.to_credential())

    def _on_remove(self) -> None:
        cred = self._selected_cred()
        if cred is None:
            return
        from ui.dialogs import confirm
        if confirm(self, "Supprimer credential",
                   f"Supprimer {cred.username} ({cred.source}) ?"):
            self._vault.remove(cred.id)

    def _on_export_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Exporter users.txt", lambda: self._export("users"))
        menu.addAction("Exporter passwords.txt", lambda: self._export("passwords"))
        menu.addAction("Exporter hashes.txt", lambda: self._export("hashes"))
        menu.exec_(self.cursor().pos())

    def _export(self, kind: str) -> None:
        from pathlib import Path
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exporter {kind}", f"{kind}.txt", "Text (*.txt)")
        if not path:
            return
        try:
            if kind == "users":
                n = self._vault.export_users_file(path)
            elif kind == "passwords":
                n = self._vault.export_passwords_file(path)
            else:
                n = self._vault.export_hashes_file(path)
            from ui.dialogs import info_box
            info_box(self, "Export OK", f"{n} entrées -> {path}")
        except Exception as exc:
            from ui.dialogs import error_box
            error_box(self, "Export KO", str(exc))

    def _copy(self, text: str) -> None:
        if text:
            QApplication.clipboard().setText(text)
