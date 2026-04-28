"""Hash Identifier — dialog.

Champ de saisie d'un hash, liste des candidats avec confiance,
commandes john / hashcat générées, bouton "envoyer au vault".
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.hash_identifier import identify, HashCandidate


_CONFIDENCE_COLOR = {
    "haute":   "#81c784",
    "moyenne": "#ffb74d",
    "faible":  "#ef5350",
}


class HashDialog(QDialog):
    send_to_vault_requested = pyqtSignal(str, str)   # hash_value, hash_type
    copy_to_clipboard_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(" Hash Identifier")
        self.setMinimumSize(760, 520)
        self._selected_candidate: Optional[HashCandidate] = None

        root = QVBoxLayout(self)

        # --- Input ---
        form = QFormLayout()
        self._input = QLineEdit()
        self._input.setFont(QFont("Monospace", 10))
        self._input.setPlaceholderText("Coller un hash ici...")
        self._input.textChanged.connect(self._on_input_changed)
        form.addRow("Hash :", self._input)

        row = QHBoxLayout()
        self._wordlist = QLineEdit("/usr/share/wordlists/rockyou.txt")
        self._wordlist.setFont(QFont("Monospace", 9))
        row.addWidget(self._wordlist, 1)
        row.addWidget(QLabel("(wordlist)"))
        form.addRow("", self._wrap(row))

        root.addLayout(form)

        # --- Candidats ---
        root.addWidget(QLabel("Candidats :"))
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Type", "Hashcat -m", "John --format", "Confiance"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.currentItemChanged.connect(self._on_candidate_selected)
        root.addWidget(self._tree, 1)

        # --- Commandes suggérées ---
        root.addWidget(QLabel("Commandes suggérées :"))
        self._cmd_view = QPlainTextEdit()
        self._cmd_view.setFont(QFont("Monospace", 10))
        self._cmd_view.setReadOnly(True)
        self._cmd_view.setMaximumHeight(120)
        root.addWidget(self._cmd_view)

        # --- Actions ---
        btn_row = QHBoxLayout()
        btn_copy_hc = QPushButton(" Copier hashcat")
        btn_copy_hc.clicked.connect(lambda: self._copy_line(0))
        btn_row.addWidget(btn_copy_hc)

        btn_copy_john = QPushButton(" Copier john")
        btn_copy_john.clicked.connect(lambda: self._copy_line(1))
        btn_row.addWidget(btn_copy_john)

        btn_row.addStretch()

        btn_vault = QPushButton(" Envoyer au Vault")
        btn_vault.clicked.connect(self._on_send_to_vault)
        btn_row.addWidget(btn_vault)

        root.addLayout(btn_row)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    # ----------------------------------------------------------

    @staticmethod
    def _wrap(layout):
        w = QWidget(); w.setLayout(layout); return w

    def _on_input_changed(self, _text: str) -> None:
        self._tree.clear()
        self._cmd_view.clear()
        self._selected_candidate = None

        value = self._input.text().strip()
        if not value:
            return

        result = identify(value)
        if not result.candidates:
            self._cmd_view.setPlainText("# Aucun type reconnu.")
            return

        for c in result.candidates:
            item = QTreeWidgetItem([
                c.name,
                c.hashcat_mode or "-",
                c.john_format or "-",
                c.confidence,
            ])
            color = _CONFIDENCE_COLOR.get(c.confidence, "#9e9e9e")
            item.setForeground(3, QColor(color))
            item.setData(0, Qt.UserRole, c)
            self._tree.addTopLevelItem(item)

        # Sélection auto du meilleur
        self._tree.setCurrentItem(self._tree.topLevelItem(0))

    def _on_candidate_selected(self, current, _prev) -> None:
        if current is None:
            self._cmd_view.clear()
            self._selected_candidate = None
            return
        c: HashCandidate = current.data(0, Qt.UserRole)
        self._selected_candidate = c

        hash_value = self._input.text().strip()
        wl = self._wordlist.text().strip() or "/usr/share/wordlists/rockyou.txt"

        lines = [
            "# Save hash to a file first:",
            f"echo '{hash_value}' > hash.txt",
            "",
            "# hashcat:",
            c.hashcat_command("hash.txt", wl),
            "",
            "# john:",
            c.john_command("hash.txt", wl),
        ]
        self._cmd_view.setPlainText("\n".join(lines))

    def _copy_line(self, which: int) -> None:
        """which=0 pour hashcat, 1 pour john."""
        if not self._selected_candidate:
            return
        hash_value = self._input.text().strip()
        wl = self._wordlist.text().strip() or "/usr/share/wordlists/rockyou.txt"
        if which == 0:
            cmd = self._selected_candidate.hashcat_command("hash.txt", wl)
        else:
            cmd = self._selected_candidate.john_command("hash.txt", wl)
        QApplication.clipboard().setText(cmd)
        self.copy_to_clipboard_requested.emit(cmd)

    def _on_send_to_vault(self) -> None:
        hash_value = self._input.text().strip()
        if not hash_value:
            return
        hash_type = (self._selected_candidate.name
                     if self._selected_candidate else "unknown")
        self.send_to_vault_requested.emit(hash_value, hash_type)
