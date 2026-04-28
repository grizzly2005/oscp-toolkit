"""Repository pour les screenshots (proof, enum, etc.).

Structure sur disque :
  data/user/screenshots/<ip>/<tag>_<timestamp>.png
  data/user/screenshots/.index.json   # index des metadata

L'index permet de retrouver rapidement les screenshots par machine
sans scanner tout le FS.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..logger import get_logger

log = get_logger(__name__)


@dataclass
class ScreenshotMeta:
    path: str           # chemin relatif a la racine screenshots/
    ip: str = ""
    machine: str = ""
    tag: str = "proof"
    timestamp: int = 0
    note_name: str = ""
    description: str = ""


class ScreenshotRepository:
    """Gere les screenshots + leur index."""

    def __init__(self, root: Path | str):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path = self._root / ".index.json"
        self._index: Optional[Dict[str, ScreenshotMeta]] = None

    def _load_index(self) -> Dict[str, ScreenshotMeta]:
        if self._index is not None:
            return self._index
        if not self._index_path.exists():
            self._index = {}
            return self._index
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            self._index = {k: ScreenshotMeta(**v) for k, v in raw.items()}
        except (OSError, ValueError, TypeError) as exc:
            log.error("Screenshot index corrupted: %s", exc)
            self._index = {}
        return self._index

    def _flush_index(self) -> None:
        if self._index is None:
            return
        data = {k: asdict(v) for k, v in self._index.items()}
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._index_path)

    # -- API -----------------------------------------------------------------

    def register(self, abs_path: Path, meta: ScreenshotMeta) -> str:
        """Enregistre un fichier existant dans l'index. Retourne sa cle.
        Le fichier doit etre DEJA ecrit sur disque.
        """
        try:
            rel = abs_path.relative_to(self._root)
        except ValueError:
            rel = abs_path.name
        meta.path = str(rel)
        if not meta.timestamp:
            meta.timestamp = int(time.time())
        key = str(rel)
        self._load_index()[key] = meta
        self._flush_index()
        return key

    def get(self, key: str) -> Optional[ScreenshotMeta]:
        return self._load_index().get(key)

    def all(self) -> List[ScreenshotMeta]:
        return list(self._load_index().values())

    def by_ip(self, ip: str) -> List[ScreenshotMeta]:
        return [m for m in self.all() if m.ip == ip]

    def by_machine(self, machine: str) -> List[ScreenshotMeta]:
        return [m for m in self.all() if m.machine == machine]

    def delete(self, key: str, remove_file: bool = False) -> bool:
        idx = self._load_index()
        meta = idx.pop(key, None)
        if meta is None:
            return False
        self._flush_index()
        if remove_file:
            abs_p = self._root / meta.path
            try:
                abs_p.unlink(missing_ok=True)
            except OSError:
                log.warning("Cannot remove screenshot file: %s", abs_p)
        return True

    def root(self) -> Path:
        return self._root
