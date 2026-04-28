"""Paths — chemins canoniques du toolkit.

Separation claire entre :
  - data/user/   : donnees cree par l'utilisateur (notes, screenshots,
                   exports, wordlists custom). A garder, a exporter,
                   a versionner eventuellement.
  - data/runtime/ : etat volatile (sessions Qt, cache, PIDs tracker).
                    Peut etre supprime sans perte utilisateur.
  - logs/         : logs rotatifs (jamais vers data/).
  - config/       : config + defaults.

Migration automatique : si on voit de vieux chemins (data/notes/,
data/screenshots/) on les deplace vers data/user/ au premier demarrage.

Usage :
  from core.paths import PATHS
  PATHS.notes_dir           # data/user/notes
  PATHS.screenshots_dir     # data/user/screenshots
  PATHS.sessions_dir        # data/runtime/sessions
  PATHS.cache_dir           # data/runtime/cache
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ToolkitPaths:
    """Chemins canoniques. frozen=True pour eviter les mutations accidentelles."""
    project_root: Path

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"

    @property
    def logs_dir(self) -> Path:
        return self.project_root / "logs"

    # -- User data (a garder) ---------------------------------------------

    @property
    def user_dir(self) -> Path:
        return self.data_dir / "user"

    @property
    def notes_dir(self) -> Path:
        return self.user_dir / "notes"

    @property
    def screenshots_dir(self) -> Path:
        return self.user_dir / "screenshots"

    @property
    def exports_dir(self) -> Path:
        return self.user_dir / "exports"

    @property
    def wordlists_dir(self) -> Path:
        return self.user_dir / "wordlists"

    # -- Runtime (jetable) -------------------------------------------------

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def sessions_dir(self) -> Path:
        return self.runtime_dir / "sessions"

    @property
    def cache_dir(self) -> Path:
        return self.runtime_dir / "cache"

    @property
    def terminal_dumps_dir(self) -> Path:
        return self.runtime_dir / "terminal_dumps"

    # -- Create all --------------------------------------------------------

    def ensure_all(self) -> None:
        for p in [
            self.user_dir, self.notes_dir, self.screenshots_dir,
            self.exports_dir, self.wordlists_dir,
            self.runtime_dir, self.sessions_dir, self.cache_dir,
            self.terminal_dumps_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)

    # -- Migration des anciens layouts (data/notes -> data/user/notes) ----

    def migrate_legacy_layout(self) -> int:
        """Migre les anciens chemins vers data/user/ et data/runtime/.
        Retourne le nombre d'items (fichiers ou dossiers) deplaces.
        Idempotent : peut etre appele plusieurs fois sans risque.
        """
        moved = 0

        # user/
        pairs_user = [
            (self.data_dir / "notes",       self.notes_dir),
            (self.data_dir / "screenshots", self.screenshots_dir),
            (self.data_dir / "exports",     self.exports_dir),
            (self.data_dir / "wordlists",   self.wordlists_dir),
        ]
        # runtime/
        pairs_runtime = [
            (self.data_dir / "sessions",    self.sessions_dir),
        ]

        for old, new in pairs_user + pairs_runtime:
            if old == new:
                continue
            if not (old.exists() and old.is_dir()):
                continue
            new.parent.mkdir(parents=True, exist_ok=True)

            # Fusion systematique : on iter sur les items et on move
            try:
                items = list(old.iterdir())
            except OSError:
                continue

            if not items:
                # Ancien dossier vide : on le supprime simplement
                try:
                    old.rmdir()
                except OSError:
                    pass
                continue

            new.mkdir(parents=True, exist_ok=True)
            for item in items:
                target = new / item.name
                if target.exists():
                    # Conflit : on laisse l'ancien. Log en debug.
                    log.debug("Migration skip (target exists): %s", target)
                    continue
                try:
                    shutil.move(str(item), str(target))
                    moved += 1
                except OSError:
                    log.warning("Move failed: %s -> %s", item, target)

            # Essaie de supprimer l'ancien dossier maintenant vide
            try:
                old.rmdir()
            except OSError:
                pass

        return moved


# Instance globale.  Le project_root est le dossier contenant main.py.
# Recalcule pour s'adapter a n'importe quel chemin de clone.
_THIS = Path(__file__).resolve()
PROJECT_ROOT = _THIS.parent.parent   # .../core/paths.py -> .../

PATHS = ToolkitPaths(project_root=PROJECT_ROOT)
