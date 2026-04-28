"""Status bar — info permanente en bas de l'app.

Affiche :
- IP attaquante (cliquable pour override manuel)
- État VPN ([OK] / [KO])
- Workspace actif
- Compteurs : terminaux actifs, listeners, file servers, tunnels
- Machine active (contexte courant, alimenté par scope panel)
- Heure
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QTime
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QWidget,
)

from core.file_server import FileServerManager
from core.listener_manager import ListenerManager
from core.network_info import NetworkInfo, NetworkSnapshot
from core.terminal import TerminalManager
from core.tunnel_manager import TunnelManager


class StatusBar(QWidget):
    ip_override_requested = pyqtSignal(str)
    workspace_switch_requested = pyqtSignal(str)

    def __init__(
        self,
        network: NetworkInfo,
        terminals: TerminalManager,
        listeners: Optional[ListenerManager] = None,
        file_servers: Optional[FileServerManager] = None,
        tunnels: Optional[TunnelManager] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._network = network
        self._terminals = terminals
        self._listeners = listeners
        self._file_servers = file_servers
        self._tunnels = tunnels

        self.setFixedHeight(26)
        self.setStyleSheet("""
            StatusBar { background: #263238; color: #eceff1; }
            QLabel { color: #eceff1; padding: 0 8px; }
            QLabel[kind="ip"] { background: #37474f; color: #80deea; border-radius: 3px; }
            QLabel[kind="vpn-on"] { color: #b9f6ca; }
            QLabel[kind="vpn-off"] { color: #ff8a80; }
            QLabel[kind="ws"] { color: #fff59d; }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        self._lbl_ip = QLabel("IP: ?")
        self._lbl_ip.setProperty("kind", "ip")
        self._lbl_ip.setCursor(QCursor(Qt.PointingHandCursor))
        self._lbl_ip.mouseReleaseEvent = self._on_ip_clicked   # type: ignore
        self._lbl_ip.setToolTip("Cliquer pour forcer une IP manuellement")
        layout.addWidget(self._lbl_ip)

        self._lbl_vpn = QLabel("VPN: ?")
        self._lbl_vpn.setProperty("kind", "vpn-off")
        layout.addWidget(self._lbl_vpn)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.VLine); sep1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep1)

        self._lbl_ws = QLabel("WS: Default")
        self._lbl_ws.setProperty("kind", "ws")
        self._lbl_ws.setCursor(QCursor(Qt.PointingHandCursor))
        self._lbl_ws.mouseReleaseEvent = self._on_ws_clicked   # type: ignore
        layout.addWidget(self._lbl_ws)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine); sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        self._lbl_counters = QLabel("T:0 L:0 F:0 P:0")
        self._lbl_counters.setToolTip("Terminaux / Listeners / File servers / Pivots")
        layout.addWidget(self._lbl_counters)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.VLine); sep3.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep3)

        self._lbl_machine = QLabel("Cible : -")
        layout.addWidget(self._lbl_machine)

        layout.addStretch()

        self._lbl_time = QLabel("")
        layout.addWidget(self._lbl_time)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()

        # Subscribe
        self._network.refreshed.connect(self._on_network_refresh)
        self._network.vpn_state_changed.connect(self._on_vpn_changed)

        self._refresh_counters_timer = QTimer(self)
        self._refresh_counters_timer.timeout.connect(self._refresh_counters)
        self._refresh_counters_timer.start(2000)

        self._on_network_refresh(self._network.snapshot())
        self._refresh_counters()

    # ----------------------------------------------------------

    def set_workspace(self, name: str) -> None:
        self._lbl_ws.setText(f"WS: {name}")

    def set_target_machine(self, text: str) -> None:
        self._lbl_machine.setText(f"Cible : {text or '-'}")

    def _tick_clock(self) -> None:
        self._lbl_time.setText(QTime.currentTime().toString("HH:mm:ss"))

    def _on_network_refresh(self, snap: NetworkSnapshot) -> None:
        ip = self._network.attacker_ip() or "-"
        self._lbl_ip.setText(f"IP: {ip}")

    def _on_vpn_changed(self, up: bool) -> None:
        self._lbl_vpn.setText("VPN: [OK]" if up else "VPN: [KO]")
        self._lbl_vpn.setProperty("kind", "vpn-on" if up else "vpn-off")
        # Repolish pour que le sélecteur [kind=...] ré-applique le CSS
        self._lbl_vpn.style().unpolish(self._lbl_vpn)
        self._lbl_vpn.style().polish(self._lbl_vpn)

    def _refresh_counters(self) -> None:
        t = len(self._terminals.all()) if self._terminals else 0
        l = len(self._listeners.all()) if self._listeners else 0
        f = len(self._file_servers.all()) if self._file_servers else 0
        p = len(self._tunnels.all()) if self._tunnels else 0
        self._lbl_counters.setText(f"T:{t} L:{l} F:{f} P:{p}")

    def _on_ip_clicked(self, event) -> None:
        current = self._network.attacker_ip() or ""
        text, ok = QInputDialog.getText(
            self,
            "Forcer IP attaquante",
            "IP manuelle (laisser vide pour auto) :",
            text=current,
        )
        if ok:
            # Émission via signal (contrat UI/core) ; main_window fait set_manual_ip.
            # Le signal est str ; on envoie "" pour "auto".
            self.ip_override_requested.emit(text.strip())

    def _on_ws_clicked(self, event) -> None:
        text, ok = QInputDialog.getText(
            self,
            "Changer de workspace",
            "Nom du workspace :",
            text=self._lbl_ws.text().replace("WS: ", ""),
        )
        if ok and text.strip():
            self.workspace_switch_requested.emit(text.strip())
