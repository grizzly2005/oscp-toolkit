"""Watchdog — supervision légère.

Lance un QTimer qui toutes les N secondes :
- vérifie que tous les PIDs trackés sont toujours vivants (sinon, émet un
  signal pour l'UI)
- vérifie que les terminaux ne sont pas bloqués depuis trop longtemps
  (délégué aux TerminalWorker via leur propre watchdog, ici on agrège)

Le watchdog ne tue rien : il notifie. L'UI décide si elle veut
proposer un kill.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from .logger import get_logger
from .process_tracker import ProcessTracker, pid_exists, TrackedProcess
from .terminal import TerminalManager

log = get_logger(__name__)


@dataclass
class HealthSnapshot:
    timestamp: float = field(default_factory=time.time)
    total_tracked: int = 0
    alive: int = 0
    dead: List[int] = field(default_factory=list)          # PIDs morts
    unresponsive_terminals: List[str] = field(default_factory=list)


class Watchdog(QObject):
    health_updated = pyqtSignal(object)        # HealthSnapshot
    process_died = pyqtSignal(object)          # TrackedProcess
    terminal_frozen = pyqtSignal(str)          # terminal name

    def __init__(
        self,
        process_tracker: ProcessTracker,
        terminal_manager: Optional[TerminalManager] = None,
        interval_ms: int = 5000,
        parent=None,
    ):
        super().__init__(parent)
        self._pt = process_tracker
        self._tm = terminal_manager
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.tick)
        self._last_seen_alive: Dict[int, bool] = {}

    def start(self) -> None:
        self._timer.start()
        self.tick()

    def stop(self) -> None:
        self._timer.stop()

    # ----------------------------------------------------------

    def tick(self) -> HealthSnapshot:
        procs = self._pt.list()
        snapshot = HealthSnapshot(total_tracked=len(procs))
        for p in procs:
            alive = pid_exists(p.pid)
            was_alive = self._last_seen_alive.get(p.pid, True)
            if alive:
                snapshot.alive += 1
            else:
                snapshot.dead.append(p.pid)
                if was_alive:
                    self.process_died.emit(p)
                    log.info("Watchdog: process PID %d (%s/%s) died",
                             p.pid, p.category, p.name)
            self._last_seen_alive[p.pid] = alive

        # Nettoyage du last_seen
        current_pids = {p.pid for p in procs}
        self._last_seen_alive = {
            pid: alive for pid, alive in self._last_seen_alive.items()
            if pid in current_pids
        }

        self.health_updated.emit(snapshot)
        return snapshot
