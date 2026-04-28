"""Session persistence — sauvegarde/restore de l'état UI.

Ce qui est persisté :
- Géométrie fenêtre (laissée au layout.json via ConfigManager)
- Terminaux ouverts (nom, commande, cwd, workspace)
- Notes ouvertes (chemins de fichiers)
- Workspace actif
- État des docks/splitters

Fichier : data/sessions/last_session.json (atomic write).
Auto-save sur chaque action "significative" (cf main_window).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logger import get_logger

log = get_logger(__name__)

_SESSION_FILE = Path("data/sessions/last_session.json")


@dataclass
class TerminalSession:
    title: str
    command: str = ""
    cwd: str = ""
    category: str = "default"
    tool_name: str = ""


@dataclass
class NoteSession:
    path: str
    cursor_pos: int = 0


@dataclass
class SessionState:
    workspace: str = "Default"
    terminals: List[TerminalSession] = field(default_factory=list)
    notes: List[NoteSession] = field(default_factory=list)
    active_note: Optional[str] = None
    open_panels: List[str] = field(default_factory=list)
    active_tab_index: int = 0
    timestamp: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace": self.workspace,
            "terminals": [asdict(t) for t in self.terminals],
            "notes": [asdict(n) for n in self.notes],
            "active_note": self.active_note,
            "open_panels": list(self.open_panels),
            "active_tab_index": self.active_tab_index,
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        return cls(
            workspace=data.get("workspace", "Default"),
            terminals=[TerminalSession(**t) for t in data.get("terminals", [])],
            notes=[NoteSession(**n) for n in data.get("notes", [])],
            active_note=data.get("active_note"),
            open_panels=list(data.get("open_panels", [])),
            active_tab_index=int(data.get("active_tab_index", 0)),
            timestamp=float(data.get("timestamp", time.time())),
            extra=dict(data.get("extra", {})),
        )


class SessionManager:
    """Charge/sauvegarde l'état de session."""

    def __init__(self, session_file: Path | str = _SESSION_FILE) -> None:
        self.path = Path(session_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def has_previous(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def load(self) -> Optional[SessionState]:
        if not self.has_previous():
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return SessionState.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            log.warning("Cannot load session (%s) - ignoring", exc)
            return None

    def save(self, state: SessionState) -> None:
        state.timestamp = time.time()
        tmp = self.path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, self.path)
            log.debug("Session saved (%d terminals, %d notes)",
                      len(state.terminals), len(state.notes))
        except OSError as exc:
            log.warning("Cannot save session: %s", exc)

    def clear(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
