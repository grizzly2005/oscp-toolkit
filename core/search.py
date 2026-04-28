"""Global Search — index inversé en mémoire.

Sources indexées :
- notes (via NotesManager)
- outils (via ToolManager) : nom, description, tags, templates
- cheatsheets (fichiers .md dans cheatsheets/)
- command history (via CommandHistory)

Index : dict[token -> set[doc_id]]. Incrémental sur add/update/remove
des sources. Rebuild complet à la demande.

Retourne des SearchHit avec snippets de contexte.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from PyQt5.QtCore import QObject, pyqtSignal

from .command_history import CommandHistory, HistoryEntry
from .logger import get_logger
from .notes import NotesManager, Note
from .tool_manager import Tool, ToolManager

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[\w\-.]{2,}", re.UNICODE)
_MIN_TOKEN_LEN = 2


def _tokenize(text: str) -> Set[str]:
    if not text:
        return set()
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}


@dataclass
class SearchHit:
    source: str            # "note" / "tool" / "cheatsheet" / "history"
    doc_id: str            # identifiant dans le source
    title: str
    snippet: str = ""
    score: int = 0


class SearchIndex(QObject):
    rebuilt = pyqtSignal(int)         # nombre de docs indexés

    def __init__(
        self,
        notes: Optional[NotesManager] = None,
        tools: Optional[ToolManager] = None,
        history: Optional[CommandHistory] = None,
        cheatsheets_dir: Optional[Path | str] = "cheatsheets",
        parent=None,
    ):
        super().__init__(parent)
        self._notes = notes
        self._tools = tools
        self._history = history
        self._cheats_dir = Path(cheatsheets_dir) if cheatsheets_dir else None

        self._lock = threading.RLock()
        # Pour chaque doc_id, on stocke (source, title, text_complet)
        self._docs: Dict[str, tuple] = {}
        self._index: Dict[str, Set[str]] = {}

        self._wire_signals()

    def _wire_signals(self) -> None:
        if self._notes:
            self._notes.note_created.connect(self._on_note_change)
            self._notes.note_changed.connect(self._on_note_change)
            self._notes.note_deleted.connect(self._on_note_delete)
        if self._tools:
            self._tools.tool_added.connect(self._on_tool_change)
            self._tools.tool_updated.connect(self._on_tool_change)
            self._tools.tool_removed.connect(
                lambda name: self._remove_doc(f"tool:{name}")
            )
        if self._history:
            self._history.entry_added.connect(self._on_history_add)

    # ----------------------------------------------------------

    def rebuild(self) -> int:
        with self._lock:
            self._docs.clear()
            self._index.clear()
            count = 0
            if self._notes:
                for n in self._notes.all():
                    self._add_note(n)
                    count += 1
            if self._tools:
                for t in self._tools.all():
                    self._add_tool(t)
                    count += 1
            if self._cheats_dir and self._cheats_dir.exists():
                for p in self._cheats_dir.rglob("*.md"):
                    self._add_cheatsheet(p)
                    count += 1
            if self._history:
                for e in self._history.all():
                    self._add_history(e)
                    count += 1
        log.info("Search index rebuilt: %d docs / %d tokens",
                 count, len(self._index))
        self.rebuilt.emit(count)
        return count

    # ---------- adders ----------

    def _add_note(self, note: Note) -> None:
        doc_id = f"note:{note.name}"
        text = f"{note.name}\n{note.content}"
        self._add_doc(doc_id, "note", note.name, text)

    def _add_tool(self, t: Tool) -> None:
        doc_id = f"tool:{t.name}"
        text = " ".join([
            t.name, t.category, t.description,
            " ".join(t.tags), " ".join(t.templates),
        ])
        self._add_doc(doc_id, "tool", t.name, text)

    def _add_cheatsheet(self, path: Path) -> None:
        doc_id = f"cheatsheet:{path.stem}"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self._add_doc(doc_id, "cheatsheet", path.stem, text)

    def _add_history(self, entry: HistoryEntry) -> None:
        # clé unique par timestamp+hash de commande (pas crucial, juste distinct)
        key = f"history:{int(entry.ts*1000)}_{hash(entry.command) & 0xFFFF}"
        text = f"{entry.command} {entry.tool} {entry.machine} {entry.workspace}"
        title = entry.command[:80]
        self._add_doc(key, "history", title, text)

    def _add_doc(self, doc_id: str, source: str, title: str, text: str) -> None:
        with self._lock:
            self._remove_doc(doc_id)
            self._docs[doc_id] = (source, title, text)
            for tok in _tokenize(text):
                if len(tok) < _MIN_TOKEN_LEN:
                    continue
                self._index.setdefault(tok, set()).add(doc_id)

    def _remove_doc(self, doc_id: str) -> None:
        with self._lock:
            if doc_id in self._docs:
                _, _, text = self._docs.pop(doc_id)
                for tok in _tokenize(text):
                    s = self._index.get(tok)
                    if s:
                        s.discard(doc_id)
                        if not s:
                            self._index.pop(tok, None)

    # ---------- signal slots ----------

    def _on_note_change(self, note: Note) -> None:
        self._add_note(note)

    def _on_note_delete(self, name: str) -> None:
        self._remove_doc(f"note:{name}")

    def _on_tool_change(self, tool: Tool) -> None:
        self._add_tool(tool)

    def _on_history_add(self, entry: HistoryEntry) -> None:
        self._add_history(entry)

    # ---------- query ----------

    def search(self, query: str, limit: int = 50) -> List[SearchHit]:
        tokens = list(_tokenize(query))
        if not tokens:
            return []

        with self._lock:
            # Intersection (AND) de tous les tokens
            sets = [self._index.get(tok, set()) for tok in tokens]
            if not all(sets):
                # Si un token n'est nulle part, on tente en OR (meilleur UX)
                result_ids: Set[str] = set()
                for s in sets:
                    result_ids |= s
            else:
                result_ids = set.intersection(*sets)

            hits: List[SearchHit] = []
            for doc_id in result_ids:
                item = self._docs.get(doc_id)
                if not item:
                    continue
                source, title, text = item
                score = sum(text.lower().count(t) for t in tokens)
                hits.append(SearchHit(
                    source=source,
                    doc_id=doc_id,
                    title=title,
                    snippet=_make_snippet(text, tokens),
                    score=score,
                ))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]


def _make_snippet(text: str, tokens: List[str], context: int = 60) -> str:
    low = text.lower()
    for tok in tokens:
        idx = low.find(tok.lower())
        if idx >= 0:
            start = max(0, idx - context)
            end = min(len(text), idx + len(tok) + context)
            snippet = text[start:end].replace("\n", " ")
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(text) else ""
            return f"{prefix}{snippet}{suffix}"
    return text[:context].replace("\n", " ")
