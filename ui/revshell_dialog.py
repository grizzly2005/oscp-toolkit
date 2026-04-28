"""Reverse Shell Generator — dialog.

Formulaire : LHOST (pré-rempli auto), LPORT, OS filter, encodings.
Liste des variantes générées avec bouton copie par ligne.
Commande listener et msfvenom associées en bas.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QTabWidget, QVBoxLayout, QWidget, QApplication,
)

from core.revshell_generator import RevshellGenerator, GeneratedShell


_OS_CHOICES = ["multi", "linux", "windows"]


class RevshellDialog(QDialog):
    copy_to_clipboard_requested = pyqtSignal(str)

    def __init__(
        self,
        generator: RevshellGenerator,
        lhost_default: str = "",
        lport_default: int = 4444,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._gen = generator
        self.setWindowTitle(" Reverse Shell Generator")
        self.setMinimumSize(820, 640)

        root = QVBoxLayout(self)

        # --- Form en haut ---
        form_box = QGroupBox("Paramètres")
        form = QFormLayout(form_box)
        self._lhost = QLineEdit(lhost_default)
        self._lhost.setPlaceholderText("ex: 10.10.14.5")
        form.addRow("LHOST :", self._lhost)

        self._lport = QSpinBox()
        self._lport.setRange(1, 65535)
        self._lport.setValue(lport_default)
        form.addRow("LPORT :", self._lport)

        self._os_filter = QComboBox()
        self._os_filter.addItems(_OS_CHOICES)
        form.addRow("Cible OS :", self._os_filter)

        row_enc = QHBoxLayout()
        self._enc_b64 = QCheckBox("Base64")
        self._enc_url = QCheckBox("URL")
        self._enc_ps = QCheckBox("PowerShell -Enc")
        for cb in (self._enc_b64, self._enc_url, self._enc_ps):
            row_enc.addWidget(cb)
        row_enc.addStretch()
        form.addRow("Encodings :", self._wrap_layout(row_enc))

        btn_row = QHBoxLayout()
        self._gen_btn = QPushButton("Générer")
        self._gen_btn.setDefault(True)
        self._gen_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self._gen_btn)
        btn_row.addStretch()
        form.addRow("", self._wrap_layout(btn_row))

        root.addWidget(form_box)

        # --- Résultats ---
        self._tabs = QTabWidget()
        self._tab_shells = QWidget()
        self._tab_shells_layout = QVBoxLayout(self._tab_shells)
        self._tab_shells_scroll = QScrollArea()
        self._tab_shells_scroll.setWidgetResizable(True)
        self._tab_shells_inner = QWidget()
        self._tab_shells_inner_layout = QVBoxLayout(self._tab_shells_inner)
        self._tab_shells_inner_layout.setAlignment(Qt.AlignTop)
        self._tab_shells_scroll.setWidget(self._tab_shells_inner)
        self._tab_shells_layout.addWidget(self._tab_shells_scroll)
        self._tabs.addTab(self._tab_shells, "Shells")

        self._listener_view = QPlainTextEdit()
        self._listener_view.setReadOnly(True)
        self._listener_view.setFont(QFont("Monospace", 10))
        self._tabs.addTab(self._listener_view, "Listeners")

        self._msfvenom_view = QPlainTextEdit()
        self._msfvenom_view.setReadOnly(True)
        self._msfvenom_view.setFont(QFont("Monospace", 10))
        self._tabs.addTab(self._msfvenom_view, "msfvenom")

        root.addWidget(self._tabs, 1)

        # Close
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Génération initiale si LHOST pré-rempli
        if lhost_default:
            self._on_generate()

    # ----------------------------------------------------------

    @staticmethod
    def _wrap_layout(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _selected_encodings(self) -> List[str]:
        enc = []
        if self._enc_b64.isChecked(): enc.append("base64")
        if self._enc_url.isChecked(): enc.append("url")
        if self._enc_ps.isChecked():  enc.append("powershell_b64")
        return enc

    # ----------------------------------------------------------

    def _on_generate(self) -> None:
        lhost = self._lhost.text().strip()
        lport = self._lport.value()
        if not lhost:
            return

        os_filter = self._os_filter.currentText()
        os_f: Optional[str] = None if os_filter == "multi" else os_filter
        encodings = self._selected_encodings()

        # --- Shells ---
        self._clear_layout(self._tab_shells_inner_layout)
        try:
            shells = self._gen.generate_variants(lhost, lport, os_f, encodings)
        except Exception as exc:
            self._tab_shells_inner_layout.addWidget(
                QLabel(f"<span style='color:#ef5350'>Erreur : {exc}</span>"))
            return

        for s in shells:
            self._tab_shells_inner_layout.addWidget(self._make_shell_row(s))

        # --- Listeners ---
        lines = []
        for key in self._gen.listener_keys():
            try:
                lines.append(f"# {key}")
                lines.append(self._gen.listener_command(key, lport))
                lines.append("")
            except Exception as exc:
                lines.append(f"# {key}: erreur ({exc})")
        self._listener_view.setPlainText("\n".join(lines))

        # --- msfvenom ---
        lines = []
        for key in self._gen.msfvenom_keys():
            try:
                lines.append(f"# {key}")
                lines.append(self._gen.msfvenom_command(key, lhost, lport))
                lines.append("")
            except Exception as exc:
                lines.append(f"# {key}: erreur ({exc})")
        self._msfvenom_view.setPlainText("\n".join(lines))

    def _make_shell_row(self, shell: GeneratedShell) -> QWidget:
        box = QGroupBox(f"{shell.key} - {shell.lang} / {shell.os}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(6, 6, 6, 6)

        if shell.description:
            desc = QLabel(f"<i style='color:#9e9e9e'>{shell.description}</i>")
            lay.addWidget(desc)

        # Payload brut
        lay.addWidget(self._payload_block("payload", shell.payload))
        # Encodés
        for enc_name, enc_val in shell.encoded.items():
            lay.addWidget(self._payload_block(enc_name, enc_val))

        return box

    def _payload_block(self, label: str, payload: str) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(f"<code>{label}</code>")
        lbl.setMinimumWidth(90)
        lay.addWidget(lbl)

        edit = QLineEdit(payload)
        edit.setReadOnly(True)
        edit.setFont(QFont("Monospace", 10))
        lay.addWidget(edit, 1)

        btn = QPushButton("")
        btn.setMaximumWidth(30)
        btn.setToolTip("Copier")
        btn.clicked.connect(lambda: self._copy(payload))
        lay.addWidget(btn)
        return w

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.copy_to_clipboard_requested.emit(text)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
