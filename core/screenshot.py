"""Screenshot helper — capture ecran ou fenetre avec naming automatique.

proof_<IP>_<timestamp>.png dans data/user/screenshots/

Methodes :
  - capture_active_window() : capture la fenetre active du toolkit
  - capture_screen() : capture ecran complet (primary screen)
  - capture_region(rect) : capture une region specifique (utilitaire)

Retourne le Path du fichier cree.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QRect
from PyQt5.QtGui import QPixmap, QScreen
from PyQt5.QtWidgets import QApplication, QWidget

from .logger import get_logger
from .paths import PATHS

log = get_logger(__name__)


# Aligne sur PATHS pour eviter la divergence avec le reste du code
# (data/user/screenshots/ et pas data/screenshots/).
SCREENSHOT_DIR = PATHS.screenshots_dir


def set_screenshot_dir(path: Path | str) -> None:
    global SCREENSHOT_DIR
    SCREENSHOT_DIR = Path(path)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_dir() -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_DIR


def _build_filename(ip: Optional[str] = None, tag: str = "proof") -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_ip = (ip or "unknown").replace(":", "_").replace("/", "_") if ip else "unknown"
    return f"{tag}_{safe_ip}_{ts}.png"


def capture_active_window(parent: Optional[QWidget] = None, ip: Optional[str] = None) -> Optional[Path]:
    """Capture la fenetre active Qt. Retourne le chemin du PNG."""
    try:
        app = QApplication.instance()
        if not app:
            return None
        win = app.activeWindow() or (parent.window() if parent else None)
        if not win:
            return None
        screen: QScreen = win.screen() if hasattr(win, "screen") else app.primaryScreen()
        geom = win.frameGeometry()
        pix: QPixmap = screen.grabWindow(
            0, geom.x(), geom.y(), geom.width(), geom.height()
        )
        _ensure_dir()
        path = SCREENSHOT_DIR / _build_filename(ip, "proof")
        if pix.save(str(path), "PNG"):
            log.info("Screenshot window: %s", path)
            return path
    except Exception:
        log.exception("capture_active_window failed")
    return None


def capture_screen(ip: Optional[str] = None) -> Optional[Path]:
    """Capture ecran complet (primary screen)."""
    try:
        app = QApplication.instance()
        if not app:
            return None
        screen: QScreen = app.primaryScreen()
        pix: QPixmap = screen.grabWindow(0)
        _ensure_dir()
        path = SCREENSHOT_DIR / _build_filename(ip, "screen")
        if pix.save(str(path), "PNG"):
            log.info("Screenshot fullscreen: %s", path)
            return path
    except Exception:
        log.exception("capture_screen failed")
    return None
