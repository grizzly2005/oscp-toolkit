"""Encoder / Decoder dialog.

Deux QPlainTextEdit (input / output), combo du mode, radio
encode/decode, bouton copier, bouton chaîner (output → input).
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout,
    QWidget, QButtonGroup,
)

from core.encoder import ENCODERS, apply


_LABELS = {
    "base64":         "Base64",
    "url":            "URL",
    "url_full":       "URL (tout)",
    "hex":            "Hex",
    "powershell_b64": "PowerShell -Enc (UTF-16LE+B64)",
    "rot13":          "ROT13",
}


class EncoderDialog(QDialog):
    copy_to_clipboard_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(" Encoder / Decoder")
        self.setMinimumSize(720, 540)

        root = QVBoxLayout(self)

        # --- Barre de contrôles ---
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Mode :"))
        self._combo = QComboBox()
        for k in ENCODERS.keys():
            self._combo.addItem(_LABELS.get(k, k), k)
        ctrl.addWidget(self._combo)

        self._rb_encode = QRadioButton("Encode")
        self._rb_decode = QRadioButton("Decode")
        self._rb_encode.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self._rb_encode)
        grp.addButton(self._rb_decode)
        ctrl.addWidget(self._rb_encode)
        ctrl.addWidget(self._rb_decode)

        ctrl.addStretch()

        btn_apply = QPushButton("> Appliquer")
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self._on_apply)
        ctrl.addWidget(btn_apply)

        btn_swap = QPushButton("<> Output -> Input")
        btn_swap.setToolTip("Chaîner : place l'output dans le champ input")
        btn_swap.clicked.connect(self._on_swap)
        ctrl.addWidget(btn_swap)

        root.addLayout(ctrl)

        # --- Input ---
        root.addWidget(QLabel("Input :"))
        self._input = QPlainTextEdit()
        self._input.setFont(QFont("Monospace", 10))
        self._input.setPlaceholderText("Coller le texte ici...")
        root.addWidget(self._input, 1)

        # --- Output ---
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output :"))
        out_row.addStretch()
        btn_copy = QPushButton(" Copier")
        btn_copy.clicked.connect(self._on_copy)
        out_row.addWidget(btn_copy)
        root.addLayout(out_row)

        self._output = QPlainTextEdit()
        self._output.setFont(QFont("Monospace", 10))
        self._output.setReadOnly(True)
        root.addWidget(self._output, 1)

        # --- Close ---
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # Auto-apply on input change ? Coût bas — on garde manuel pour
        # éviter les "decode plante" visuels intempestifs.
        self._input.textChanged.connect(self._maybe_auto_apply)

    # ----------------------------------------------------------

    def _current_mode(self) -> str:
        return self._combo.currentData()

    def _on_apply(self) -> None:
        text = self._input.toPlainText()
        if not text:
            self._output.clear()
            return
        mode = self._current_mode()
        decode = self._rb_decode.isChecked()
        try:
            result = apply(mode, text, decode=decode)
        except Exception as exc:
            self._output.setPlainText(f"[ERREUR] {exc}")
            return
        self._output.setPlainText(result)

    def _maybe_auto_apply(self) -> None:
        # Auto-apply seulement si c'est pas trop long, et seulement en encode
        if len(self._input.toPlainText()) > 5000:
            return
        if self._rb_decode.isChecked():
            # Ne pas auto-apply en decode (trop facile de voir des erreurs)
            return
        self._on_apply()

    def _on_copy(self) -> None:
        text = self._output.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.copy_to_clipboard_requested.emit(text)

    def _on_swap(self) -> None:
        out = self._output.toPlainText()
        if not out:
            return
        self._input.setPlainText(out)
        self._output.clear()
