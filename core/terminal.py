"""Terminal manager — QThread isolé par terminal.

Architecture :
    main_thread (UI) <-signal/slot-> TerminalWorker (QThread)
                                      |
                                      v
                                   PTY + process

Chaque terminal est isolé dans son QThread. Si un worker crash,
les autres terminaux survivent. L'UI reçoit uniquement des signaux
`output_received`, `finished`, `error`.

Sécurités :
- Buffer max : 50_000 lignes en mémoire, dump auto vers fichier au-delà.
- Sanitize : filtrage caractères non-UTF8 / non-imprimables.
- Watchdog : pas de réponse > 10s = signal `unresponsive`.
- Fermeture propre : SIGTERM -> 3s -> SIGKILL -> close fd PTY.

Fallback : si `pty` n'est pas disponible, on tombe sur un subprocess
classique (pas de PTY, moins bon mais ça tourne).
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, QMutex, QMutexLocker

from .logger import get_logger
from .paths import PATHS
from .process_tracker import ProcessTracker

log = get_logger(__name__)

try:
    import pty
    import select
    _HAS_PTY = True
except ImportError:  # pragma: no cover - Windows fallback
    pty = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]
    _HAS_PTY = False


_MAX_BUFFER_LINES = 50_000
_WATCHDOG_TIMEOUT_SEC = 10.0
_DUMP_DIR = PATHS.terminal_dumps_dir
_SIGTERM_GRACE_SEC = 3.0


def _default_shell_command() -> List[str]:
    if os.name == "nt":
        return [os.environ.get("COMSPEC", "cmd.exe")]
    return [os.environ.get("SHELL", "/bin/bash")]


def _sanitize(raw_bytes: bytes) -> str:
    """Décode UTF-8 avec replacement, retire NULLs et BEL."""
    s = raw_bytes.decode("utf-8", errors="replace")
    # On garde les ANSI escapes et les \r\n, on vire juste NUL et quelques autres.
    return s.replace("\x00", "").replace("\x07", "")


class TerminalWorker(QThread):
    """Un QThread par terminal. Porte un PTY + fork d'un shell (ou commande)."""

    output_received = pyqtSignal(str)       # chunks décodés
    finished_signal = pyqtSignal(int)       # exit code
    error_occurred = pyqtSignal(str)        # message
    unresponsive = pyqtSignal()             # watchdog : aucun output depuis timeout
    alive_again = pyqtSignal()              # après unresponsive, quand ça revient

    def __init__(
        self,
        command: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        process_tracker: Optional[ProcessTracker] = None,
        terminal_name: str = "terminal",
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.command = command or _default_shell_command()
        self.cwd = cwd
        self.env = env
        self._process_tracker = process_tracker
        self._terminal_name = terminal_name

        self._pid: Optional[int] = None
        self._master_fd: Optional[int] = None
        self._proc: Optional[subprocess.Popen] = None

        self._stop_requested = False
        self._input_queue: List[bytes] = []
        self._output_queue: "queue.Queue[bytes]" = queue.Queue()
        self._input_mutex = QMutex()

        self._buffer_lines = 0
        self._dump_file: Optional[Path] = None
        self._last_output_ts = time.time()
        self._last_input_ts:  float = 0.0   # timestamp dernier input envoyé
        self._was_unresponsive = False

    # ----------------------------------------------------------

    def pid(self) -> Optional[int]:
        return self._pid

    def send_input(self, data: str) -> None:
        if not data:
            return
        self._last_input_ts = time.time()
        with QMutexLocker(self._input_mutex):
            self._input_queue.append(data.encode("utf-8", errors="ignore"))

    def notify_input_sent(self) -> None:
        """Appelé depuis l'UI quand l'utilisateur envoie une commande.
        Active la surveillance du watchdog pour cette commande.
        """
        self._last_input_ts = time.time()

    def request_stop(self, graceful: bool = True) -> None:
        """Signal au worker qu'il doit se terminer. Appelé depuis UI thread."""
        self._stop_requested = True
        pid = self._pid
        if pid is None:
            return
        if graceful:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                except OSError:
                    pass
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass

    def force_kill(self) -> None:
        pid = self._pid
        if pid is None:
            return
        if self._proc is not None:
            try:
                self._proc.kill()
            except OSError:
                pass
            return
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            os.kill(pid, sigkill)
        except OSError:
            pass

    # ----------------------------------------------------------

    def run(self) -> None:
        """Boucle principale du thread : fork PTY + select I/O."""
        exit_code = -1
        try:
            if _HAS_PTY and os.name != "nt":
                self._spawn()
                exit_code = self._io_loop()
            else:
                self._spawn_subprocess()
                exit_code = self._io_loop_subprocess()
        except Exception as exc:
            log.exception("Terminal spawn/loop failed")
            self.error_occurred.emit(f"Terminal failed: {exc}")
        finally:
            self._teardown()
            self.finished_signal.emit(exit_code)

    # ----------------------------------------------------------

    def _spawn(self) -> None:
        assert pty is not None
        pid, fd = pty.fork()
        if pid == 0:
            # Process enfant
            try:
                if self.cwd:
                    os.chdir(self.cwd)
                # Si l'utilisateur n'a pas fourni d'env perso, on construit un
                # env propre : pas de PROMPT_COMMAND (qui envoie OSC titre que
                # le terminal embarque ne sait pas interpreter -> apparait
                # comme "]0;user@host:..." dans la sortie). PS1 simple en plus
                # pour eviter tout escape sequence dans le prompt.
                if self.env is None:
                    env = os.environ.copy()
                    env.pop("PROMPT_COMMAND", None)
                    env["PS1"] = r"\u@\h:\w\$ "
                    # TERM=xterm-256color permet aux outils (ls, grep --color)
                    # de renvoyer du SGR couleur que notre parser sait gerer.
                    env.setdefault("TERM", "xterm-256color")
                    os.execvpe(self.command[0], self.command, env)
                else:
                    os.execvpe(self.command[0], self.command, self.env)
            except OSError as exc:
                os.write(2, f"exec failed: {exc}\n".encode())
                os._exit(127)
        # Parent
        self._pid = pid
        self._master_fd = fd

        if self._process_tracker:
            self._process_tracker.register(
                pid=pid,
                name=self._terminal_name,
                category="terminal",
                command=" ".join(self.command),
            )
        log.info("Terminal spawned PID=%d cmd=%s", pid, " ".join(self.command))

    def _spawn_subprocess(self) -> None:
        env = self.env or os.environ.copy()
        if os.name != "nt":
            env.pop("PROMPT_COMMAND", None)
            env["PS1"] = r"\u@\h:\w\$ "
            env.setdefault("TERM", "xterm-256color")
        self._proc = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        self._pid = self._proc.pid
        if self._process_tracker:
            self._process_tracker.register(
                pid=self._proc.pid,
                name=self._terminal_name,
                category="terminal",
                command=" ".join(self.command),
            )
        log.info("Terminal subprocess spawned PID=%d cmd=%s",
                 self._proc.pid, " ".join(self.command))

    def _io_loop(self) -> int:
        assert self._master_fd is not None
        assert self._pid is not None
        assert select is not None
        fd = self._master_fd

        while not self._stop_requested:
            # Input pending ?
            with QMutexLocker(self._input_mutex):
                pending_input = b"".join(self._input_queue)
                self._input_queue.clear()
            if pending_input:
                # os.write peut retourner < len(data) en cas de buffer plein
                # ou EINTR. On boucle pour ne rien perdre.
                offset = 0
                while offset < len(pending_input):
                    try:
                        n = os.write(fd, pending_input[offset:])
                        if n <= 0:
                            # cas pathologique : on log et on abandonne
                            log.warning("os.write returned %d, stopping", n)
                            break
                        offset += n
                    except InterruptedError:
                        continue   # EINTR : on reessaie
                    except OSError as exc:
                        self.error_occurred.emit(f"write failed: {exc}")
                        offset = len(pending_input)   # break clean
                        break
                if offset < len(pending_input):
                    break

            try:
                readable, _, _ = select.select([fd], [], [], 0.2)
            except OSError:
                break

            if fd in readable:
                try:
                    chunk = os.read(fd, 65_536)
                except OSError as exc:
                    # EIO = PTY closed (enfant mort)
                    if exc.errno == 5:
                        break
                    self.error_occurred.emit(f"read failed: {exc}")
                    break
                if not chunk:
                    break
                self._handle_output(chunk)
                if self._was_unresponsive:
                    self._was_unresponsive = False
                    self.alive_again.emit()

            # Watchdog : ne fire que si une commande a été envoyée
            # et qu'il n'y a pas eu de réponse depuis _WATCHDOG_TIMEOUT_SEC.
            # Évite le faux positif sur shell idle (prompt qui attend).
            now = time.time()
            waiting_for_output = (
                self._last_input_ts > self._last_output_ts          # commande envoyée
                and (now - self._last_input_ts) > _WATCHDOG_TIMEOUT_SEC  # timeout dépassé
            )
            if waiting_for_output and not self._was_unresponsive:
                self._was_unresponsive = True
                self.unresponsive.emit()
            elif not waiting_for_output and self._was_unresponsive:
                # Reset si plus en attente (process a répondu)
                self._was_unresponsive = False

            # Process toujours vivant ?
            try:
                done_pid, status = os.waitpid(self._pid, os.WNOHANG)
            except ChildProcessError:
                break
            if done_pid == self._pid:
                return os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (
                    os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
                )

        # Stop demandé : SIGTERM propre puis SIGKILL après grace
        return self._terminate_child()

    def _io_loop_subprocess(self) -> int:
        assert self._proc is not None

        def _reader() -> None:
            stream = self._proc.stdout
            if stream is None:
                return
            while True:
                try:
                    chunk = stream.read(4096)
                except OSError:
                    break
                if not chunk:
                    break
                self._output_queue.put(chunk)

        threading.Thread(
            target=_reader,
            daemon=True,
            name=f"{self._terminal_name}-stdout",
        ).start()

        while not self._stop_requested:
            with QMutexLocker(self._input_mutex):
                pending_input = b"".join(self._input_queue)
                self._input_queue.clear()
            if pending_input and self._proc.stdin is not None:
                try:
                    self._proc.stdin.write(pending_input)
                    self._proc.stdin.flush()
                except (BrokenPipeError, OSError) as exc:
                    self.error_occurred.emit(f"write failed: {exc}")
                    break

            while True:
                try:
                    chunk = self._output_queue.get_nowait()
                except queue.Empty:
                    break
                self._handle_output(chunk)
                if self._was_unresponsive:
                    self._was_unresponsive = False
                    self.alive_again.emit()

            now = time.time()
            waiting_for_output = (
                self._last_input_ts > self._last_output_ts
                and (now - self._last_input_ts) > _WATCHDOG_TIMEOUT_SEC
            )
            if waiting_for_output and not self._was_unresponsive:
                self._was_unresponsive = True
                self.unresponsive.emit()
            elif not waiting_for_output and self._was_unresponsive:
                self._was_unresponsive = False

            rc = self._proc.poll()
            if rc is not None:
                while True:
                    try:
                        chunk = self._output_queue.get_nowait()
                    except queue.Empty:
                        break
                    self._handle_output(chunk)
                return int(rc)

            time.sleep(0.05)

        return self._terminate_child()

    def _terminate_child(self) -> int:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            try:
                return int(self._proc.wait(timeout=_SIGTERM_GRACE_SEC))
            except subprocess.TimeoutExpired:
                try:
                    self._proc.kill()
                except OSError:
                    pass
                try:
                    return int(self._proc.wait(timeout=1.0))
                except subprocess.TimeoutExpired:
                    log.warning("Terminal PID %d did not stop after kill", self._pid or -1)
                    return -1
        if self._pid is None:
            return -1
        try:
            os.kill(self._pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.time() + _SIGTERM_GRACE_SEC
        while time.time() < deadline:
            try:
                done, status = os.waitpid(self._pid, os.WNOHANG)
            except ChildProcessError:
                return 0
            if done == self._pid:
                return os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
            time.sleep(0.1)
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            os.kill(self._pid, sigkill)
        except OSError:
            pass
        # Apres SIGKILL, on attend la mort avec un timeout pour eviter le
        # blocage infini si le process est zombie / parent change. Si waitpid
        # ne retourne pas en 1s, on abandonne (le processus est dans un etat
        # bizarre, mais ce n'est plus notre probleme).
        deadline2 = time.time() + 1.0
        while time.time() < deadline2:
            try:
                done, status = os.waitpid(self._pid, os.WNOHANG)
            except ChildProcessError:
                return -1
            if done == self._pid:
                return os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
            time.sleep(0.05)
        log.warning("Terminal PID %d did not respond to SIGKILL within 1s", self._pid)
        return -1

    def _handle_output(self, chunk: bytes) -> None:
        self._last_output_ts = time.time()
        text = _sanitize(chunk)
        self.output_received.emit(text)
        # Comptage de lignes pour dumping
        new_lines = text.count("\n")
        self._buffer_lines += new_lines
        if self._buffer_lines >= _MAX_BUFFER_LINES:
            self._dump(text)

    def _dump(self, text: str) -> None:
        """Au dépassement de buffer, on commence à dump dans un fichier."""
        if self._dump_file is None:
            _DUMP_DIR.mkdir(parents=True, exist_ok=True)
            safe = self._terminal_name.replace(" ", "_").replace("/", "_")
            self._dump_file = _DUMP_DIR / f"{safe}_{int(time.time())}.log"
            log.info("Terminal %s: buffer overflow -> dumping to %s",
                     self._terminal_name, self._dump_file)
        try:
            with open(self._dump_file, "a", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            log.warning("Dump failed: %s", exc)

    def _teardown(self) -> None:
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._proc is not None:
            for stream in (self._proc.stdin, self._proc.stdout):
                try:
                    if stream:
                        stream.close()
                except OSError:
                    pass
        if self._pid is not None and self._process_tracker:
            self._process_tracker.unregister(self._pid)


class TerminalManager(QObject):
    """Registre central des terminaux (appelé depuis main_window)."""

    terminal_created = pyqtSignal(object)     # TerminalWorker
    terminal_closed = pyqtSignal(int)         # pid

    def __init__(
        self,
        process_tracker: Optional[ProcessTracker] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._pt = process_tracker
        self._workers: List[TerminalWorker] = []

    def spawn(
        self,
        command: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        terminal_name: str = "terminal",
    ) -> TerminalWorker:
        worker = TerminalWorker(
            command=command,
            cwd=cwd,
            env=env,
            process_tracker=self._pt,
            terminal_name=terminal_name,
        )
        worker.finished_signal.connect(lambda _: self._on_finished(worker))
        self._workers.append(worker)
        worker.start()
        self.terminal_created.emit(worker)
        return worker

    def _on_finished(self, worker: TerminalWorker) -> None:
        pid = worker.pid() or -1
        if worker in self._workers:
            self._workers.remove(worker)
        self.terminal_closed.emit(pid)

    def all(self) -> List[TerminalWorker]:
        return list(self._workers)

    def stop_all(self) -> None:
        for w in list(self._workers):
            w.request_stop(graceful=True)
            w.wait(1000)
            if w.isRunning():
                w.force_kill()
                w.wait(1000)
