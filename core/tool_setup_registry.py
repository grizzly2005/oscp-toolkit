"""Tool Setup Registry — lance des outils qui necessitent un setup.

Certains outils (ligolo proxy, responder, etc.) ne sont pas des commandes
one-shot : il faut les demarrer, surveiller, arreter. Ce registry centralise
les "setup actions" pour que le main_window puisse les exposer dans un menu.

Chaque SetupAction connait :
  - son nom (display)
  - comment la demarrer (commande + env)
  - si elle tourne (via ProcessTracker)
  - comment l'arreter

Utilisation :
  reg = ToolSetupRegistry(tracker, env_manager)
  reg.start("ligolo-proxy")
  reg.stop("ligolo-proxy")
"""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from core.logger import get_logger
from core.process_tracker import ProcessTracker

log = get_logger(__name__)


@dataclass
class SetupAction:
    key: str              # identifiant unique, e.g. "ligolo-proxy"
    name: str             # display, e.g. "Ligolo-ng Proxy"
    description: str
    command: List[str]    # argv
    cwd: Optional[str] = None
    category: str = "network"


# Definitions des outils setup supportes.
#
# IMPORTANT : les paths sont resolus dynamiquement par rapport a la racine du
# toolkit. La structure attendue est :
#   <pentest_root>/
#     toolkit/                   <- ce projet (paths.py est ici/core/paths.py)
#     binaries/
#       linux/network/ligolo/ligolo_proxy_lin
#       linux/network/Responder-3.1.7.0/Responder.py
#       windows/ad/BloodHound-CE/docker-compose.yml
#
# Si la structure differe chez l'utilisateur, il peut customiser via
# config/services_overrides.json (cf _apply_service_overrides dans
# main_window.py) sans toucher au code.
from core.paths import PATHS as _PATHS

# pentest_root = parent du toolkit (../). Cf paths.py : project_root = toolkit/
_PENTEST_ROOT = _PATHS.project_root.parent
_BIN_LIN = _PENTEST_ROOT / "binaries" / "linux"
_BIN_WIN = _PENTEST_ROOT / "binaries" / "windows"

_ACTIONS: List[SetupAction] = [
    SetupAction(
        key="ligolo-proxy",
        name="Ligolo-ng Proxy",
        description="Lance le proxy Ligolo-ng avec sudo (self-cert). Ecoute sur :11601.",
        command=[
            "sudo",
            str(_BIN_LIN / "network" / "ligolo" / "ligolo_proxy_lin"),
            "-selfcert",
            "-laddr", "0.0.0.0:11601",
        ],
        cwd=str(_BIN_LIN / "network" / "ligolo"),
        category="pivot",
    ),
    SetupAction(
        key="responder",
        name="Responder (LLMNR/NBT-NS)",
        description="Lance Responder sur tun0 (sudo requis).",
        command=[
            "sudo",
            "python3",
            str(_BIN_LIN / "network" / "Responder-3.1.7.0" / "Responder.py"),
            "-I", "tun0",
        ],
        cwd=str(_BIN_LIN / "network" / "Responder-3.1.7.0"),
        category="ad",
    ),
    SetupAction(
        key="bloodhound",
        name="BloodHound-CE (docker)",
        description="Demarre le container BloodHound Community Edition.",
        command=[
            "docker", "compose", "up", "-d",
        ],
        cwd=str(_BIN_WIN / "ad" / "BloodHound-CE"),
        category="ad",
    ),
]


class ToolSetupRegistry(QObject):
    """Registre des outils a setup via bouton."""

    started = pyqtSignal(str)    # key
    stopped = pyqtSignal(str)    # key

    def __init__(self, process_tracker: ProcessTracker, parent=None):
        super().__init__(parent)
        self._pt = process_tracker
        self._running: Dict[str, int] = {}   # key -> pid
        self._actions = {a.key: a for a in _ACTIONS}

    def all_actions(self) -> List[SetupAction]:
        return list(self._actions.values())

    def is_running(self, key: str) -> bool:
        pid = self._running.get(key)
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            self._running.pop(key, None)
            return False

    def start(self, key: str) -> Optional[int]:
        act = self._actions.get(key)
        if act is None:
            raise ValueError(f"Action inconnue : {key}")
        if self.is_running(key):
            return self._running[key]

        # Verifier que l'executable existe (path absolu OU dans PATH)
        exe = act.command[0]
        if exe in ("sudo", "docker"):
            pass  # system cmds
        elif "/" in exe:
            # Path absolu ou relatif : on verifie l'existence directement
            if not Path(exe).exists():
                raise FileNotFoundError(f"Executable introuvable : {exe}")
        else:
            # Nom court : lookup dans PATH
            import shutil
            if not shutil.which(exe):
                raise FileNotFoundError(f"Executable '{exe}' introuvable dans le PATH")

        cwd = act.cwd if act.cwd and Path(act.cwd).exists() else None

        proc = subprocess.Popen(
            act.command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._running[key] = proc.pid
        self._pt.register(
            pid=proc.pid,
            name=f"setup:{key}",
            category=act.category,
            command=" ".join(act.command),
        )
        log.info("ToolSetup start: %s pid=%d", key, proc.pid)
        self.started.emit(key)
        return proc.pid

    def stop(self, key: str) -> bool:
        pid = self._running.get(key)
        if pid is None:
            return False
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        self._running.pop(key, None)
        log.info("ToolSetup stop: %s pid=%d", key, pid)
        self.stopped.emit(key)
        return True

    def shutdown(self) -> None:
        """Arrete tous les outils setup au shutdown du toolkit."""
        for key in list(self._running.keys()):
            try:
                self.stop(key)
            except Exception:
                log.exception("Shutdown stop %s failed", key)
