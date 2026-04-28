"""Transfer Helper — dialog.

Formulaire : chemin fichier, IP attaquante (pré-remplie), OS cible,
options (ports, dest dir). Affiche les paires (attaquant / victime)
générées par core.transfer_helper.

Bouton " Lancer un HTTP server sur ce dossier" → démarre un file_server
sur FileServerManager.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from core.transfer_helper import generate, TransferPair
from core.file_server import FileServerManager


class TransferDialog(QDialog):
    copy_to_clipboard_requested = pyqtSignal(str)

    def __init__(
        self,
        attacker_ip: str = "",
        file_server_manager: Optional[FileServerManager] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._fs = file_server_manager
        self.setWindowTitle(" Transfer Helper")
        self.setMinimumSize(820, 620)

        root = QVBoxLayout(self)

        form_box = QGroupBox("Paramètres")
        form = QFormLayout(form_box)

        # Fichier
        file_row = QHBoxLayout()
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("Ex: /opt/tools/linpeas.sh")
        file_row.addWidget(self._file_edit, 1)
        btn_browse = QPushButton("...")
        btn_browse.setMaximumWidth(40)
        btn_browse.clicked.connect(self._on_browse)
        file_row.addWidget(btn_browse)
        form.addRow("Fichier :", self._wrap(file_row))

        # Attaquant IP
        self._ip_edit = QLineEdit(attacker_ip)
        self._ip_edit.setPlaceholderText("10.10.14.5")
        form.addRow("IP attaquante :", self._ip_edit)

        # OS cible
        self._os_combo = QComboBox()
        self._os_combo.addItems(["linux", "windows", "both"])
        form.addRow("OS cible :", self._os_combo)

        # Port
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(8000)
        form.addRow("Port HTTP :", self._port)

        # Dest dir
        self._dest_linux = QLineEdit("/tmp")
        form.addRow("Dest. Linux :", self._dest_linux)
        self._dest_windows = QLineEdit(r"C:\Windows\Temp")
        form.addRow("Dest. Windows :", self._dest_windows)

        # Actions
        btn_row = QHBoxLayout()
        btn_gen = QPushButton("Générer commandes")
        btn_gen.setDefault(True)
        btn_gen.clicked.connect(self._on_generate)
        btn_row.addWidget(btn_gen)

        if self._fs is not None:
            btn_serve = QPushButton(" Lancer file server (dossier du fichier)")
            btn_serve.clicked.connect(self._on_start_file_server)
            btn_row.addWidget(btn_serve)

        btn_row.addStretch()
        form.addRow("", self._wrap(btn_row))

        root.addWidget(form_box)

        # Résultats
        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_inner = QWidget()
        self._results_layout = QVBoxLayout(self._results_inner)
        self._results_layout.setAlignment(Qt.AlignTop)
        self._results_scroll.setWidget(self._results_inner)
        root.addWidget(self._results_scroll, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    # ----------------------------------------------------------

    @staticmethod
    def _wrap(layout):
        w = QWidget(); w.setLayout(layout); return w

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Fichier à transférer",
                                               str(Path.home()))
        if path:
            self._file_edit.setText(path)

    def _on_generate(self) -> None:
        file_path = self._file_edit.text().strip()
        ip = self._ip_edit.text().strip()
        if not file_path or not ip:
            return
        os_target = self._os_combo.currentText()
        port = self._port.value()

        # Clear
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        pairs = []
        try:
            if os_target == "both":
                pairs.extend(generate(file_path, ip, "linux",
                                       port_http=port,
                                       dest_dir=self._dest_linux.text() or "/tmp"))
                pairs.extend(generate(file_path, ip, "windows",
                                       port_http=port,
                                       dest_dir=self._dest_windows.text() or r"C:\Windows\Temp"))
            else:
                dest = (self._dest_linux.text() if os_target == "linux"
                        else self._dest_windows.text())
                pairs.extend(generate(file_path, ip, os_target,
                                       port_http=port, dest_dir=dest))
        except Exception as exc:
            self._results_layout.addWidget(
                QLabel(f"<span style='color:#ef5350'>Erreur : {exc}</span>"))
            return

        for p in pairs:
            self._results_layout.addWidget(self._make_pair_widget(p))

    def _make_pair_widget(self, pair: TransferPair) -> QWidget:
        box = QGroupBox(f"{pair.label}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(6, 6, 6, 6)

        if pair.description:
            desc = QLabel(f"<i style='color:#9e9e9e'>{pair.description}</i>")
            lay.addWidget(desc)

        lay.addWidget(self._cmd_row(" Attaquant", pair.attacker_command))
        lay.addWidget(self._cmd_row(" Victime", pair.victim_command))
        return box

    def _cmd_row(self, label: str, cmd: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setMinimumWidth(100)
        row.addWidget(lbl)
        edit = QLineEdit(cmd)
        edit.setReadOnly(True)
        edit.setFont(QFont("Monospace", 10))
        row.addWidget(edit, 1)
        btn = QPushButton("")
        btn.setMaximumWidth(34)
        btn.clicked.connect(lambda: self._copy(cmd))
        row.addWidget(btn)
        return w

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.copy_to_clipboard_requested.emit(text)

    def _on_start_file_server(self) -> None:
        if self._fs is None:
            return
        file_path = self._file_edit.text().strip()
        if not file_path:
            return
        directory = str(Path(file_path).parent)
        port = self._port.value()
        try:
            share = self._fs.start_http(directory=directory, port=port)
            QApplication.clipboard().setText(
                f"http://{self._ip_edit.text().strip()}:{share.port}/"
            )
        except Exception as exc:
            from ui.dialogs import error_box
            error_box(self, "Erreur file server", str(exc))
