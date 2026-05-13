"""Process Tracker — PID tracking + cleanup shutdown + orphan check.

Tout process lancé par l'app (listener, file server, tunnel, terminal
embarqué, outil externe) est enregistré ici. Au shutdown, tous les PIDs
sont SIGTERM puis SIGKILL après 3 secondes. Au boot, on détecte les
orphelins laissés par un crash précédent.

Persistance : data/runtime/sessions/pids.json (atomic write).
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, List, Optional

from .logger import get_logger
from .paths import PATHS

log = get_logger(__name__)

_SIGTERM_GRACE_SECONDS = 3.0
_SESSION_FILE = PATHS.sessions_dir / "pids.json"


@dataclass
class TrackedProcess:
    pid: int
    name: str
    category: str = "misc"          # terminal / listener / file_server / tunnel / tool
    command: str = ""
    started_at: float = field(default_factory=time.time)
    port: Optional[int] = None
    extra: dict = field(default_factory=dict)


def pid_exists(pid: int) -> bool:
    """Vrai si le PID existe (ne dit rien sur l'ownership)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            process_query_limited_information = 0x1000
            handle = kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                # 5 = access denied: le PID existe mais pas forcement a nous.
                return kernel32.GetLastError() == 5
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe mais pas à nous
    except OSError:
        return False
    return True


class ProcessTracker:
    """Singleton de fait : une instance créée dans main.py."""

    def __init__(self, session_file: Path | str = _SESSION_FILE) -> None:
        self.session_file = Path(session_file)
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self._procs: List[TrackedProcess] = []
        self._lock = threading.RLock()
        self._shutdown_done = False
        self._cleanup_callbacks: List[Callable[[TrackedProcess], None]] = []

        atexit.register(self.cleanup)
        # Signaux : on ne peut les installer que dans le thread principal.
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
        except (ValueError, OSError):
            # Appel depuis un thread secondaire ou OS ne supporte pas : tant pis.
            log.debug("Could not install signal handlers (not main thread?)")

    # ----------------------------------------------------------

    def register(
        self,
        pid: int,
        name: str,
        category: str = "misc",
        command: str = "",
        port: Optional[int] = None,
        extra: Optional[dict] = None,
    ) -> TrackedProcess:
        tp = TrackedProcess(
            pid=pid,
            name=name,
            category=category,
            command=command,
            port=port,
            extra=extra or {},
        )
        with self._lock:
            self._procs.append(tp)
            self._persist()
        log.info("Tracked PID %d (%s / %s)", pid, category, name)
        return tp

    def unregister(self, pid: int) -> None:
        with self._lock:
            before = len(self._procs)
            self._procs = [p for p in self._procs if p.pid != pid]
            if len(self._procs) != before:
                log.debug("Unregistered PID %d", pid)
                self._persist()

    def list(self, category: Optional[str] = None) -> List[TrackedProcess]:
        with self._lock:
            if category is None:
                return list(self._procs)
            return [p for p in self._procs if p.category == category]

    def is_alive(self, pid: int) -> bool:
        return pid_exists(pid)

    def on_cleanup(self, callback: Callable[[TrackedProcess], None]) -> None:
        """Callback appelé pour chaque process pendant le cleanup.

        Utile pour permettre à un module (file_server, listener, ...) de
        notifier son UI que le process est mort.
        """
        self._cleanup_callbacks.append(callback)

    # ----------------------------------------------------------

    def kill(self, pid: int, grace: float = _SIGTERM_GRACE_SECONDS) -> bool:
        """SIGTERM -> attente grace -> SIGKILL. Retourne True si mort."""
        if not pid_exists(pid):
            self.unregister(pid)
            return True
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            log.warning("SIGTERM %d failed: %s", pid, exc)

        deadline = time.time() + grace
        while time.time() < deadline:
            if not pid_exists(pid):
                self.unregister(pid)
                return True
            time.sleep(0.1)

        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            os.kill(pid, sigkill)
        except OSError as exc:
            log.warning("SIGKILL %d failed: %s", pid, exc)

        time.sleep(0.1)
        dead = not pid_exists(pid)
        if dead:
            self.unregister(pid)
        return dead

    def cleanup(self) -> None:
        """Kill tous les process trackés. Idempotent."""
        if self._shutdown_done:
            return
        with self._lock:
            snapshot = list(self._procs)
        if snapshot:
            log.info("Cleanup : killing %d tracked processes", len(snapshot))
        for p in snapshot:
            try:
                self.kill(p.pid)
                for cb in self._cleanup_callbacks:
                    try:
                        cb(p)
                    except Exception as exc:  # on ne laisse pas un cb foirer le reste
                        log.warning("Cleanup callback failed: %s", exc)
            except Exception as exc:
                log.warning("Cleanup of PID %d failed: %s", p.pid, exc)
        with self._lock:
            self._procs.clear()
            self._persist()
        self._shutdown_done = True

    def check_orphans(self) -> List[TrackedProcess]:
        """Retourne les PIDs de la session précédente encore vivants."""
        if not self.session_file.exists():
            return []
        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Cannot read %s (%s)", self.session_file, exc)
            return []
        orphans: List[TrackedProcess] = []
        for item in raw.get("procs", []):
            try:
                tp = TrackedProcess(**item)
            except TypeError:
                continue
            if pid_exists(tp.pid):
                orphans.append(tp)
        return orphans

    def kill_orphans(self, orphans: List[TrackedProcess]) -> int:
        killed = 0
        for o in orphans:
            if self.kill(o.pid):
                killed += 1
        # Reset le fichier
        self._persist()
        return killed

    def clear_session_file(self) -> None:
        """À appeler après décision utilisateur sur les orphelins."""
        try:
            if self.session_file.exists():
                self.session_file.unlink()
        except OSError:
            pass

    # ----------------------------------------------------------

    def _signal_handler(self, signum, _frame):
        log.info("Received signal %d, shutting down", signum)
        self.cleanup()
        # Re-raise le signal par défaut pour que Python/Qt fasse ce qu'il faut
        try:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
        except OSError:
            pass

    def _persist(self) -> None:
        payload = {
            "procs": [asdict(p) for p in self._procs],
            "saved_at": time.time(),
        }
        tmp = self.session_file.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, self.session_file)
        except OSError as exc:
            log.warning("Cannot persist PIDs file: %s", exc)
