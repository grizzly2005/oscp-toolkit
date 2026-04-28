r"""Listener Manager — gestion des listeners reverse shell.

Supporte :
- nc classique       : `nc -lvnp <port>`
- rlwrap + nc        : `rlwrap nc -lvnp <port>`
- ncat --ssl         : `ncat --ssl -lvnp <port>`
- pwncat-cs          : `pwncat-cs -lp <port>`
- socat PTY listener : `socat file:\`tty\`,raw,echo=0 tcp-listen:<port>`

Lancés hors du terminal embarqué (dans leur propre sous-process), PID
tracké. Heuristique de détection de connexion entrante en surveillant
la sortie stderr (nc, ncat).

Pour un VRAI I/O interactif, l'utilisateur utilisera un terminal tab
dédié ; ce manager est pour les listeners "en tâche de fond" dont on
veut juste savoir s'ils sont montés et si quelqu'un se connecte.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger
from .process_tracker import ProcessTracker, pid_exists

log = get_logger(__name__)


LISTENER_TYPES = ["nc", "rlwrap_nc", "ncat_ssl", "socat_tty", "pwncat"]


@dataclass
class Listener:
    id: str
    kind: str
    port: int
    pid: int
    label: str = ""
    ssl: bool = False
    started_at: float = field(default_factory=time.time)
    connected: bool = False
    remote_peer: str = ""


class ListenerManager(QObject):
    listener_started = pyqtSignal(object)
    listener_stopped = pyqtSignal(str)
    incoming_connection = pyqtSignal(object)       # Listener
    listeners_changed = pyqtSignal()

    def __init__(self, process_tracker: ProcessTracker, parent=None):
        super().__init__(parent)
        self._pt = process_tracker
        self._listeners: Dict[str, Listener] = {}
        # procs : stocke aussi le Popen pour lire stderr (pas dans la dataclass)
        self._procs: Dict[str, subprocess.Popen] = {}
        self._reader_threads: Dict[str, threading.Thread] = {}
        self._monitor_stop = threading.Event()
        self._monitor = threading.Thread(
            target=self._monitor_loop, daemon=True, name="listener-monitor"
        )
        self._monitor.start()

    # ----------------------------------------------------------

    def all(self) -> List[Listener]:
        return list(self._listeners.values())

    def start(
        self,
        kind: str,
        port: int,
        label: str = "",
    ) -> Listener:
        if kind not in LISTENER_TYPES:
            raise ValueError(f"Unknown listener kind '{kind}'")
        cmd = self._build_command(kind, port)
        if cmd is None:
            raise RuntimeError(f"Tool for '{kind}' not installed")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        lid = f"lst_{uuid.uuid4().hex[:8]}"
        listener = Listener(
            id=lid, kind=kind, port=port, pid=proc.pid,
            label=label or f"{kind}:{port}",
            ssl=(kind == "ncat_ssl"),
        )
        self._listeners[lid] = listener
        self._procs[lid] = proc
        self._pt.register(
            pid=proc.pid, name=listener.label,
            category="listener", command=" ".join(cmd), port=port,
        )

        # Thread lecture stderr pour détecter "connect to" etc.
        t = threading.Thread(
            target=self._reader, args=(lid, proc),
            daemon=True, name=f"listener-reader-{port}",
        )
        t.start()
        self._reader_threads[lid] = t

        log.info("Listener %s started on port %d (pid=%d)", kind, port, proc.pid)
        self.listener_started.emit(listener)
        self.listeners_changed.emit()
        return listener

    def stop(self, lid: str) -> bool:
        listener = self._listeners.get(lid)
        if listener is None:
            return False
        killed = self._pt.kill(listener.pid)
        self._listeners.pop(lid, None)
        self._procs.pop(lid, None)
        self.listener_stopped.emit(lid)
        self.listeners_changed.emit()
        log.info("Listener %s stopped (killed=%s)", lid, killed)
        return killed

    def stop_all(self) -> None:
        for lid in list(self._listeners.keys()):
            self.stop(lid)

    def shutdown(self) -> None:
        self._monitor_stop.set()
        self.stop_all()

    # ----------------------------------------------------------

    def _build_command(self, kind: str, port: int) -> Optional[List[str]]:
        if kind == "nc":
            if not shutil.which("nc"):
                return None
            return ["nc", "-lvnp", str(port)]
        if kind == "rlwrap_nc":
            if not (shutil.which("rlwrap") and shutil.which("nc")):
                return None
            return ["rlwrap", "nc", "-lvnp", str(port)]
        if kind == "ncat_ssl":
            if not shutil.which("ncat"):
                return None
            return ["ncat", "--ssl", "-lvnp", str(port)]
        if kind == "socat_tty":
            if not shutil.which("socat"):
                return None
            # subprocess.Popen ne lance pas un shell, donc \`tty\` ne sera PAS
            # interprete. On resout tty cote Python via os.ttyname si on a un
            # tty, sinon on tombe sur /dev/tty (qui marche dans la majorite
            # des cas avec setsid + un terminal allocator).
            tty_path = "/dev/tty"
            try:
                # Si le toolkit tourne dans un terminal, on peut recuperer
                # son tty pour que socat tape les frappes attaquant dessus.
                if os.isatty(0):
                    tty_path = os.ttyname(0)
            except (OSError, AttributeError):
                pass
            return ["socat", f"FILE:{tty_path},raw,echo=0", f"tcp-listen:{port}"]
        if kind == "pwncat":
            binary = shutil.which("pwncat-cs") or shutil.which("pwncat")
            if not binary:
                return None
            return [binary, "-lp", str(port)]
        return None

    def _reader(self, lid: str, proc: subprocess.Popen) -> None:
        """Lit stderr (où nc/ncat logguent les connexions) pour détecter
        'connect to' / 'connection from' et mettre connected=True."""
        listener = self._listeners.get(lid)
        if listener is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                decoded = line.decode("utf-8", errors="replace").strip()
                if not decoded:
                    continue
                low = decoded.lower()
                if "connect to" in low or "connection from" in low or "connection received" in low:
                    listener.connected = True
                    # Essayer d'extraire l'IP source
                    import re
                    m = re.search(r"(?:from|to)\s+\[?([\w.:]+)\]?", decoded)
                    if m:
                        listener.remote_peer = m.group(1)
                    self.incoming_connection.emit(listener)
                    self.listeners_changed.emit()
                    log.info("Incoming connection on listener %s (%s): %s",
                             lid, listener.port, decoded)
        except Exception as exc:  # la lecture peut être tuée par SIGTERM
            log.debug("Listener reader %s exiting (%s)", lid, exc)

    def _monitor_loop(self) -> None:
        """Détecte les listeners morts (externe)."""
        while not self._monitor_stop.wait(2.0):
            dead: List[str] = []
            for lid, listener in list(self._listeners.items()):
                if not pid_exists(listener.pid):
                    dead.append(lid)
            for lid in dead:
                log.info("Listener %s died externally", lid)
                listener = self._listeners.pop(lid, None)
                if listener:
                    self._pt.unregister(listener.pid)
                self._procs.pop(lid, None)
                self.listener_stopped.emit(lid)
                self.listeners_changed.emit()
