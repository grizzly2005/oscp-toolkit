"""Base repository interface + JsonRepository reference impl."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, TypeVar

from ..logger import get_logger

log = get_logger(__name__)

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    """Interface minimale CRUD pour un repository."""

    @abstractmethod
    def get(self, key: str) -> Optional[T]: ...

    @abstractmethod
    def all(self) -> List[T]: ...

    @abstractmethod
    def save(self, key: str, entity: T) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> bool: ...


class JsonRepository(Repository[Dict[str, Any]]):
    """Repository JSON : {key: dict} persiste dans un seul fichier.

    Chaque entite est un dict (serialisable JSON).
    Le fichier entier est reecrit atomiquement a chaque save/delete.
    Adapte pour < 1000 entites ; au-dela, passer a SQLite.
    """

    def __init__(self, file_path: Path | str):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[Dict[str, Dict[str, Any]]] = None

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        if not self._path.exists():
            self._cache = {}
            return self._cache
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                log.warning("JsonRepo %s: not a dict, resetting", self._path)
                data = {}
            self._cache = data
        except (OSError, ValueError) as exc:
            log.error("JsonRepo %s: corrupted (%s), starting fresh", self._path, exc)
            self._cache = {}
        return self._cache

    def _flush(self) -> None:
        if self._cache is None:
            return
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(self._cache, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(self._path)
        except OSError as exc:
            log.error("JsonRepo flush %s failed: %s", self._path, exc)
            # Cleanup du tmp en cas d'echec partiel : sinon il reste
            # sur disque indefiniment.
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

    # -- API -----------------------------------------------------------------

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        # Bug : "dict(self._load().get(key, {})) or None" retourne None
        # pour un dict vide {} valide. On distingue absence vs vide.
        data = self._load()
        if key not in data:
            return None
        return dict(data[key])

    def all(self) -> List[Dict[str, Any]]:
        return [dict(v) for v in self._load().values()]

    def save(self, key: str, entity: Dict[str, Any]) -> None:
        self._load()[key] = dict(entity)
        self._flush()

    def delete(self, key: str) -> bool:
        data = self._load()
        if key in data:
            del data[key]
            self._flush()
            return True
        return False

    def clear_cache(self) -> None:
        self._cache = None
