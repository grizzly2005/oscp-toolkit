"""Transfer Helper — dialog visuel et commandes prêtes à copier."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from core.transfer_helper import TransferPair, generate
from core.file_server import DEFAULT_SERVING_DIR, FileServerManager


_METHOD_COLORS = {
    "http": "#4fc3f7",
    "smb": "#ba68c8",
    "base64": "#ffb74d",
    "nc": "#81c784",
    "scp": "#90a4ae",
}


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
        self._attacker_ip = attacker_ip
        self._last_pairs: List[TransferPair] = []
        self._pulse_on = False

        self.setWindowTitle("Transfer Helper")
        self.setMinimumSize(900, 680)
        self._install_local_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_header())
        root.addWidget(self._build_form())

        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_inner = QWidget()
        self._results_layout = QVBoxLayout(self._results_inner)
        self._results_layout.setAlignment(Qt.AlignTop)
        self._results_layout.setSpacing(8)
        self._results_scroll.setWidget(self._results_inner)
        root.addWidget(self._results_scroll, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(650)
        self._pulse_timer.timeout.connect(self._pulse_status)
        self._pulse_timer.start()

    # -- Build ---------------------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("transferHero")
        row = QHBoxLayout(header)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        logo = QLabel("TX")
        logo.setObjectName("transferLogo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(38, 38)
        row.addWidget(logo)

        texts = QVBoxLayout()
        title = QLabel("Transfert rapide")
        title.setObjectName("transferTitle")
        subtitle = QLabel("HTTP, SMB, Netcat, SCP et Base64 avec commandes attaquant/victime.")
        subtitle.setObjectName("transferSubtitle")
        texts.addWidget(title)
        texts.addWidget(subtitle)
        row.addLayout(texts, 1)

        self._status_dot = QLabel()
        self._status_dot.setObjectName("transferDot")
        self._status_dot.setFixedSize(12, 12)
        row.addWidget(self._status_dot)

        self._summary = QLabel("Prêt")
        self._summary.setObjectName("transferSummary")
        self._summary.setMinimumWidth(170)
        row.addWidget(self._summary)
        return header

    def _build_form(self) -> QWidget:
        form_box = QGroupBox("Paramètres")
        form = QFormLayout(form_box)
        form.setLabelAlignment(Qt.AlignRight)

        file_row = QHBoxLayout()
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("Ex: /opt/tools/linpeas.sh")
        file_row.addWidget(self._file_edit, 1)
        btn_browse = QPushButton("...")
        btn_browse.setObjectName("transferSmallButton")
        btn_browse.setMaximumWidth(42)
        btn_browse.clicked.connect(self._on_browse)
        file_row.addWidget(btn_browse)
        form.addRow("Fichier :", self._wrap(file_row))

        self._ip_edit = QLineEdit()
        self._ip_edit.setText(self._attacker_ip)
        self._ip_edit.setPlaceholderText("10.10.14.5")
        form.addRow("IP attaquante :", self._ip_edit)

        self._os_combo = QComboBox()
        self._os_combo.addItems(["linux", "windows", "both"])
        form.addRow("OS cible :", self._os_combo)

        port_row = QHBoxLayout()
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(8000)
        port_row.addWidget(self._port)
        port_row.addStretch()
        form.addRow("Port HTTP :", self._wrap(port_row))

        self._dest_linux = QLineEdit("/tmp")
        form.addRow("Dest. Linux :", self._dest_linux)
        self._dest_windows = QLineEdit(r"C:\Windows\Temp")
        form.addRow("Dest. Windows :", self._dest_windows)

        btn_row = QHBoxLayout()
        btn_gen = QPushButton("Générer")
        btn_gen.setObjectName("transferPrimary")
        btn_gen.setDefault(True)
        btn_gen.clicked.connect(self._on_generate)
        btn_row.addWidget(btn_gen)

        self._btn_copy_all = QPushButton("Copier tout")
        self._btn_copy_all.setObjectName("transferCopyAll")
        self._btn_copy_all.setEnabled(False)
        self._btn_copy_all.clicked.connect(self._copy_all)
        btn_row.addWidget(self._btn_copy_all)

        if self._fs is not None:
            self._btn_serve = QPushButton("Démarrer HTTP")
            self._btn_serve.setObjectName("transferServer")
            self._btn_serve.clicked.connect(self._on_start_file_server)
            btn_row.addWidget(self._btn_serve)

        btn_row.addStretch()
        form.addRow("", self._wrap(btn_row))
        return form_box

    @staticmethod
    def _wrap(layout):
        w = QWidget()
        w.setLayout(layout)
        return w

    # -- Actions -------------------------------------------------------------

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Fichier à transférer",
            str(Path.home()),
        )
        if path:
            self._file_edit.setText(path)
            self._on_generate()

    def _on_generate(self) -> None:
        file_path = self._file_edit.text().strip()
        ip = self._ip_edit.text().strip()
        if not file_path or not ip:
            self._set_summary("Fichier et IP requis", "#ef5350")
            return

        self._clear_results()
        os_target = self._os_combo.currentText()
        port = self._port.value()
        pairs: List[TransferPair] = []

        try:
            if os_target == "both":
                pairs.extend(generate(
                    file_path, ip, "linux",
                    port_http=port,
                    dest_dir=self._dest_linux.text() or "/tmp",
                ))
                pairs.extend(generate(
                    file_path, ip, "windows",
                    port_http=port,
                    dest_dir=self._dest_windows.text() or r"C:\Windows\Temp",
                ))
            else:
                dest = (
                    self._dest_linux.text()
                    if os_target == "linux"
                    else self._dest_windows.text()
                )
                pairs.extend(generate(file_path, ip, os_target, port_http=port, dest_dir=dest))
        except Exception as exc:
            self._results_layout.addWidget(
                QLabel(f"<span style='color:#ef5350'>Erreur : {exc}</span>")
            )
            self._set_summary("Erreur génération", "#ef5350")
            return

        self._last_pairs = pairs
        self._btn_copy_all.setEnabled(bool(pairs))
        for pair in pairs:
            self._results_layout.addWidget(self._make_pair_widget(pair))
        self._set_summary(f"{len(pairs)} commande(s)", "#81c784")

    def _clear_results(self) -> None:
        self._last_pairs = []
        self._btn_copy_all.setEnabled(False)
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _make_pair_widget(self, pair: TransferPair) -> QWidget:
        box = QGroupBox()
        box.setObjectName("transferCard")
        color = _METHOD_COLORS.get(pair.method, "#4fc3f7")
        box.setStyleSheet(
            "QGroupBox#transferCard {"
            f"border-left: 4px solid {color};"
            "border-top: 1px solid #333;"
            "border-right: 1px solid #333;"
            "border-bottom: 1px solid #333;"
            "border-radius: 4px; margin-top: 4px; padding-top: 4px;"
            "}"
        )

        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        badge = QLabel(pair.method.upper())
        badge.setObjectName("transferBadge")
        badge.setStyleSheet(
            f"QLabel#transferBadge {{ background:{color}; color:#101010; "
            "border-radius:3px; padding:2px 7px; font-weight:bold; }}"
        )
        head.addWidget(badge)

        title = QLabel(pair.label)
        title.setObjectName("transferCardTitle")
        head.addWidget(title, 1)

        if pair.recommended:
            rec = QLabel("RECOMMANDÉ")
            rec.setObjectName("transferRecommended")
            head.addWidget(rec)
        lay.addLayout(head)

        if pair.description:
            desc = QLabel(pair.description)
            desc.setObjectName("transferCardDesc")
            desc.setWordWrap(True)
            lay.addWidget(desc)

        lay.addWidget(self._cmd_row("Attaquant", pair.attacker_command, "#4fc3f7"))
        lay.addWidget(self._cmd_row("Victime", pair.victim_command, "#81c784"))
        return box

    def _cmd_row(self, label: str, cmd: str, color: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        lbl = QLabel(label)
        lbl.setMinimumWidth(82)
        lbl.setStyleSheet(f"color:{color}; font-weight:bold;")
        row.addWidget(lbl)

        edit = QLineEdit(cmd)
        edit.setReadOnly(True)
        edit.setFont(QFont("Monospace", 10))
        row.addWidget(edit, 1)

        btn = QPushButton("Copier")
        btn.setObjectName("transferCopy")
        btn.clicked.connect(lambda: self._copy(cmd))
        row.addWidget(btn)
        return w

    def _copy_all(self) -> None:
        if not self._last_pairs:
            return
        lines = []
        for pair in self._last_pairs:
            lines.append(f"# {pair.label}")
            lines.append(f"# Attaquant: {pair.attacker_command}")
            lines.append(pair.victim_command)
            lines.append("")
        self._copy("\n".join(lines).strip())

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.copy_to_clipboard_requested.emit(text)
        self._set_summary("Copié", "#4fc3f7", reset=True)

    def _on_start_file_server(self) -> None:
        if self._fs is None:
            return
        file_path = self._file_edit.text().strip()
        DEFAULT_SERVING_DIR.mkdir(parents=True, exist_ok=True)
        directory = str(DEFAULT_SERVING_DIR)
        if file_path:
            src = Path(file_path)
            if not src.is_file():
                self._set_summary("Fichier introuvable", "#ef5350", reset=True)
                return
            staged = DEFAULT_SERVING_DIR / src.name
            try:
                if src.resolve() != staged.resolve():
                    shutil.copy2(src, staged)
                self._file_edit.setText(str(staged))
            except OSError as exc:
                from ui.dialogs import error_box
                error_box(self, "Erreur transfert", f"Copie impossible : {exc}")
                self._set_summary("Copie KO", "#ef5350", reset=True)
                return
        port = self._port.value()
        try:
            share = self._fs.start_http(directory=directory, port=port)
            self._port.setValue(share.port)
            url = f"http://{self._ip_edit.text().strip()}:{share.port}/"
            QApplication.clipboard().setText(url)
            if file_path:
                self._set_summary(f"Fichier servi :{share.port}", "#81c784")
                self._on_generate()
            else:
                self._set_summary(f"HTTP actif :{share.port}", "#81c784")
        except Exception as exc:
            from ui.dialogs import error_box
            error_box(self, "Erreur file server", str(exc))
            self._set_summary("Serveur KO", "#ef5350", reset=True)

    # -- Visual feedback -----------------------------------------------------

    def _set_summary(self, text: str, color: str = "#9e9e9e", reset: bool = False) -> None:
        self._summary.setText(text)
        self._summary.setStyleSheet(f"color:{color}; font-weight:bold;")
        if reset:
            QTimer.singleShot(1300, lambda: self._set_summary("Prêt"))

    def _pulse_status(self) -> None:
        self._pulse_on = not self._pulse_on
        color = "#4fc3f7" if self._pulse_on else "#2d7f9f"
        self._status_dot.setStyleSheet(
            f"background:{color}; border-radius:6px; border:1px solid #8ee7ff;"
        )

    def _install_local_style(self) -> None:
        self.setStyleSheet("""
            QWidget#transferHero {
                background: #202a30;
                border: 1px solid #36515d;
                border-radius: 6px;
            }
            QLabel#transferLogo {
                background: #4fc3f7;
                color: #101820;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13pt;
            }
            QLabel#transferTitle {
                color: #ffffff;
                font-size: 13pt;
                font-weight: bold;
            }
            QLabel#transferSubtitle, QLabel#transferCardDesc {
                color: #9e9e9e;
            }
            QLabel#transferSummary {
                color: #9e9e9e;
                font-weight: bold;
            }
            QLabel#transferCardTitle {
                color: #eceff1;
                font-weight: bold;
            }
            QLabel#transferRecommended {
                background: #263b2c;
                color: #81c784;
                border: 1px solid #3d6b48;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 8pt;
                font-weight: bold;
            }
            QPushButton#transferPrimary {
                background: #2c4a5e;
                border-color: #4fc3f7;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton#transferCopyAll {
                background: #3a3a3d;
                border-color: #5a5a5e;
            }
            QPushButton#transferServer {
                background: #263b2c;
                border-color: #81c784;
                color: #dff5e3;
                font-weight: bold;
            }
            QPushButton#transferCopy {
                min-width: 62px;
                background: #2d2d30;
                border-color: #4a4a4d;
            }
            QPushButton#transferCopy:hover {
                border-color: #4fc3f7;
            }
        """)
