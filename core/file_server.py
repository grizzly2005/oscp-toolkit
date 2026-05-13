"""File Server — sert un dossier en HTTP et/ou SMB pour transferts.

HTTP : `python3 -m http.server <port>` (simple et toujours dispo)
SMB  : `impacket-smbserver <share> <path> -smb2support` si dispo

Les process sont trackés via ProcessTracker. On expose des URLs prêtes
à copier, et le manager peut proposer des commandes pour le côté
cible (wget / curl / certutil / iwr / copy) — mais pour la génération
complète des commandes cible/attaquant, voir transfer_helper.py.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger
from .process_tracker import ProcessTracker, pid_exists

log = get_logger(__name__)


def _free_port(preferred: int) -> int:
    """Retourne `preferred` si dispo, sinon un port libre proche."""
    def available(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", p))
                return True
            except OSError:
                return False
    if available(preferred):
        return preferred
    for p in range(preferred + 1, preferred + 50):
        if available(p):
            return p
    # Dernier recours : on laisse l'OS choisir
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@dataclass
class FileShare:
    id: str
    kind: str                      # 'http' / 'smb'
    directory: str
    port: int
    pid: int
    share_name: str = ""           # pour SMB
    started_at: float = field(default_factory=time.time)

    def urls(self, attacker_ip: Optional[str] = None) -> List[str]:
        ip = attacker_ip or "ATTACKER_IP"
        if self.kind == "http":
            return [f"http://{ip}:{self.port}/"]
        # SMB
        return [f"\\\\{ip}\\{self.share_name or 'SHARE'}"]


class FileServerManager(QObject):
    share_started = pyqtSignal(object)      # FileShare
    share_stopped = pyqtSignal(str)         # share id
    shares_changed = pyqtSignal()

    def __init__(self, process_tracker: ProcessTracker, parent=None):
        super().__init__(parent)
        self._pt = process_tracker
        self._shares: Dict[str, FileShare] = {}
        self._monitor_stop = threading.Event()
        self._monitor = threading.Thread(
            target=self._monitor_loop, daemon=True, name="file-server-monitor"
        )
        self._monitor.start()

    # ----------------------------------------------------------

    def all(self) -> List[FileShare]:
        return list(self._shares.values())

    def start_http(self, directory: str, port: int = 8000) -> FileShare:
        d = Path(directory)
        if not d.is_dir():
            raise ValueError(f"Not a directory: {directory}")
        actual_port = _free_port(port)
        cmd = [sys.executable, "-m", "http.server", str(actual_port)]
        proc = subprocess.Popen(
            cmd,
            cwd=str(d),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        if proc.poll() is not None:
            raise RuntimeError(
                f"HTTP server failed to start on port {actual_port}"
            )
        sid = f"http_{uuid.uuid4().hex[:8]}"
        share = FileShare(
            id=sid, kind="http", directory=str(d),
            port=actual_port, pid=proc.pid,
        )
        self._shares[sid] = share
        self._pt.register(
            pid=proc.pid, name=f"http:{actual_port}",
            category="file_server", command=" ".join(cmd),
            port=actual_port, extra={"directory": str(d)},
        )
        log.info("HTTP server started on port %d (dir=%s, pid=%d)",
                 actual_port, d, proc.pid)
        self.share_started.emit(share)
        self.shares_changed.emit()
        return share

    def start_smb(
        self,
        directory: str,
        share_name: str = "ATTACK",
        port: int = 445,
    ) -> FileShare:
        if not shutil.which("impacket-smbserver") and not shutil.which("smbserver.py"):
            raise RuntimeError(
                "impacket-smbserver absent. Install avec : pipx install impacket"
            )
        d = Path(directory)
        if not d.is_dir():
            raise ValueError(f"Not a directory: {directory}")
        binary = shutil.which("impacket-smbserver") or shutil.which("smbserver.py")
        cmd = [binary, share_name, str(d), "-smb2support"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        sid = f"smb_{uuid.uuid4().hex[:8]}"
        share = FileShare(
            id=sid, kind="smb", directory=str(d),
            port=port, pid=proc.pid, share_name=share_name,
        )
        self._shares[sid] = share
        self._pt.register(
            pid=proc.pid, name=f"smb:{share_name}",
            category="file_server", command=" ".join(cmd),
            port=port, extra={"directory": str(d), "share": share_name},
        )
        log.info("SMB server started share=%s dir=%s pid=%d",
                 share_name, d, proc.pid)
        self.share_started.emit(share)
        self.shares_changed.emit()
        return share

    def stop(self, share_id: str) -> bool:
        share = self._shares.get(share_id)
        if share is None:
            return False
        killed = self._pt.kill(share.pid)
        self._shares.pop(share_id, None)
        self.share_stopped.emit(share_id)
        self.shares_changed.emit()
        log.info("Share %s stopped (killed=%s)", share_id, killed)
        return killed

    def stop_all(self) -> None:
        for sid in list(self._shares.keys()):
            self.stop(sid)

    def shutdown(self) -> None:
        self._monitor_stop.set()
        self.stop_all()

    # ----------------------------------------------------------

    def _monitor_loop(self) -> None:
        """Polling 2s : détecte les process morts et nettoie."""
        while not self._monitor_stop.wait(2.0):
            dead: List[str] = []
            for sid, share in list(self._shares.items()):
                if not pid_exists(share.pid):
                    dead.append(sid)
            for sid in dead:
                log.info("File server %s died externally, cleaning up", sid)
                share = self._shares.pop(sid, None)
                if share:
                    self._pt.unregister(share.pid)
                self.share_stopped.emit(sid)
                self.shares_changed.emit()
