"""Logger centralisé pour toute l'app.

- Un fichier par session dans logs/
- Rotation : max 10 fichiers conservés
- Format structuré : [date] [niveau] [module] message
- Niveaux : DEBUG / INFO / WARNING / ERROR
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_LOGGER_INITIALIZED = False
_LOG_DIR = Path("logs")
_LOG_FILE_BASENAME = "app.log"
_MAX_BACKUPS = 10
_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def init_logging(log_dir: Optional[Path] = None, level: int = logging.INFO) -> Path:
    """Initialise le logging global. À appeler une seule fois au boot.

    Retourne le chemin du fichier log actif.
    """
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return _current_log_path()

    log_dir = Path(log_dir) if log_dir else _LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # Rotation manuelle : on renomme app.log en app.log.N avant d'en créer un nouveau.
    _rotate_old_logs(log_dir)

    log_path = log_dir / _LOG_FILE_BASENAME

    root = logging.getLogger()
    root.setLevel(level)

    # Évite la duplication si init_logging rappelé (défense en profondeur)
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # Aussi stderr pour debug console
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.WARNING)
    root.addHandler(stream_handler)

    _LOGGER_INITIALIZED = True
    logging.getLogger(__name__).info(
        "Logger initialized -> %s (session %s)",
        log_path,
        datetime.now().isoformat(timespec="seconds"),
    )
    return log_path


def _rotate_old_logs(log_dir: Path) -> None:
    """Conserve au plus _MAX_BACKUPS fichiers app.log.N."""
    base = log_dir / _LOG_FILE_BASENAME
    if not base.exists():
        return
    # Décale tous les backups : app.log.N -> app.log.N+1
    for i in range(_MAX_BACKUPS - 1, 0, -1):
        src = log_dir / f"{_LOG_FILE_BASENAME}.{i}"
        dst = log_dir / f"{_LOG_FILE_BASENAME}.{i + 1}"
        if src.exists():
            try:
                src.replace(dst)
            except OSError:
                pass
    # Le courant devient .1
    try:
        base.replace(log_dir / f"{_LOG_FILE_BASENAME}.1")
    except OSError:
        pass
    # Purge au-delà de _MAX_BACKUPS
    excess = log_dir / f"{_LOG_FILE_BASENAME}.{_MAX_BACKUPS + 1}"
    if excess.exists():
        try:
            excess.unlink()
        except OSError:
            pass


def _current_log_path() -> Path:
    return _LOG_DIR / _LOG_FILE_BASENAME


def get_logger(name: str) -> logging.Logger:
    """Récupère un logger nommé. Raccourci idiomatique pour les modules."""
    return logging.getLogger(name)
