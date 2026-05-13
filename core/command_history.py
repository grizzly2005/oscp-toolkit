"""Command History — log global de toutes les commandes lancées.

Persisté dans data/runtime/sessions/command_history.jsonl (un JSON par ligne,
append-only). Rotation à 10 000 entrées : on renomme en
command_history.1.jsonl et on recommence.

Chaque entrée :
  {
    "ts": 1690000000.12,
    "tool": "nxc",
    "command": "nxc smb 10.10.10.10 -u admin -p P@ss",
    "terminal": "terminal-2",
    "machine": "10.10.10.10",
    "workspace": "default",
    "exit_code": null,        # rempli après exécution si connu
    "tags": ["ad", "smb"]
  }

Recherche : substring + filtre par tool/machine/workspace.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger
from .paths import PATHS

log = get_logger(__name__)


_HISTORY_FILE = PATHS.sessions_dir / "command_history.jsonl"
_MAX_ENTRIES = 10_000
_MAX_ROTATIONS = 3


@dataclass
class HistoryEntry:
    ts: float
    command: str
    tool: str = ""
    terminal: str = ""
    machine: str = ""
    workspace: str = ""
    exit_code: Optional[int] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        # on ignore silencieusement les clés inconnues (forward-compat)
        known = {"ts", "command", "tool", "terminal", "machine",
                 "workspace", "exit_code", "tags"}
        return cls(**{k: v for k, v in d.items() if k in known})


class CommandHistory(QObject):
    entry_added = pyqtSignal(object)          # HistoryEntry
    history_rotated = pyqtSignal()
    history_changed = pyqtSignal()

    def __init__(
        self,
        path: Path | str = _HISTORY_FILE,
        max_entries: int = _MAX_ENTRIES,
        parent=None,
    ):
        super().__init__(parent)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self._cache: List[HistoryEntry] = []
        self._load()

    # ----------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._cache.append(HistoryEntry.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError as exc:
            log.warning("Cannot load history: %s", exc)
        log.info("Command history: %d entries loaded", len(self._cache))

    def _append_disk(self, entry: HistoryEntry) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("Cannot append history: %s", exc)

    def _rotate_if_needed(self) -> None:
        if len(self._cache) < self.max_entries:
            return
        # Garder seulement les max_entries plus récents dans le cache
        self._cache = self._cache[-self.max_entries:]
        # Rotation disque
        for i in range(_MAX_ROTATIONS - 1, 0, -1):
            src = self.path.with_suffix(f".jsonl.{i}")
            dst = self.path.with_suffix(f".jsonl.{i + 1}")
            if src.exists():
                try:
                    src.replace(dst)
                except OSError:
                    pass
        try:
            if self.path.exists():
                self.path.replace(self.path.with_suffix(".jsonl.1"))
        except OSError:
            pass
        # On réécrit un fichier courant avec le cache rogné
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                for e in self._cache:
                    f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("History rotation write failed: %s", exc)
        self.history_rotated.emit()

    # ----------------------------------------------------------

    def record(
        self,
        command: str,
        tool: str = "",
        terminal: str = "",
        machine: str = "",
        workspace: str = "",
        tags: Optional[List[str]] = None,
    ) -> HistoryEntry:
        entry = HistoryEntry(
            ts=time.time(),
            command=command,
            tool=tool,
            terminal=terminal,
            machine=machine,
            workspace=workspace,
            tags=tags or [],
        )
        self._cache.append(entry)
        self._append_disk(entry)
        self._rotate_if_needed()
        self.entry_added.emit(entry)
        self.history_changed.emit()
        return entry

    def update_exit_code(self, ts: float, command: str, exit_code: int) -> None:
        """Met à jour l'exit_code a posteriori. On réécrit le fichier."""
        target = None
        for e in reversed(self._cache):
            if e.ts == ts and e.command == command:
                target = e
                break
        if target is None:
            return
        target.exit_code = exit_code
        # Réécriture complète (simple, pas fréquent)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                for e in self._cache:
                    f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("History rewrite failed: %s", exc)
        self.history_changed.emit()

    # ---------- lecture ----------

    def all(self) -> List[HistoryEntry]:
        return list(self._cache)

    def recent(self, n: int = 50) -> List[HistoryEntry]:
        return self._cache[-n:][::-1]

    def search(
        self,
        query: str = "",
        tool: Optional[str] = None,
        machine: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> List[HistoryEntry]:
        q = query.lower().strip()
        out = []
        for e in reversed(self._cache):   # plus récents d'abord
            if q and q not in e.command.lower():
                continue
            if tool and e.tool != tool:
                continue
            if machine and e.machine != machine:
                continue
            if workspace and e.workspace != workspace:
                continue
            out.append(e)
        return out

    def clear(self) -> None:
        self._cache.clear()
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
        self.history_changed.emit()

    def iter_all(self) -> Iterator[HistoryEntry]:
        yield from self._cache
