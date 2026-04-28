"""Bootstrap — initialisation coherente du toolkit.

Separation des responsabilites entre main.py (entry point minimal)
et les etapes d'init, pour faciliter :
  - les tests (on peut bootstrap sans main.py)
  - le reload a chaud (futur)
  - la lisibilite

main.py appelle bootstrap() puis run_gui() + shutdown().
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

from core.config_manager import ConfigManager
from core.paths import PATHS
from core.logger import init_logging, get_logger
from core.process_tracker import ProcessTracker
from core.session import SessionManager
from core.preflight import run_preflight, PreflightReport
from core.app_state import AppState


@dataclass
class BootstrapResult:
    config: ConfigManager
    state: AppState
    tracker: ProcessTracker
    session: SessionManager
    preflight_report: PreflightReport
    log_path: str


def bootstrap() -> Optional[BootstrapResult]:
    """Etape 1-4 : init sans Qt. Retourne None si preflight bloque."""
    # Logger
    log_path = init_logging()
    log = get_logger("bootstrap")
    log.info("=" * 60)
    log.info("OSCP Toolkit starting")
    log.info("=" * 60)

    # Paths : migration auto + creation dossiers
    PATHS.ensure_all()
    moved = PATHS.migrate_legacy_layout()
    if moved:
        log.info("Migrated %d legacy directories to new layout", moved)

    # Config
    cfg = ConfigManager(
        config_dir=PATHS.config_dir,
        defaults_dir=PATHS.config_dir / "defaults",
    )

    # App state (source de verite centrale)
    state = AppState(cfg)

    # Process tracker
    tracker = ProcessTracker()

    # Preflight
    report = run_preflight(cfg, tracker)
    if report.has_blocking_failure:
        print("OSCP Toolkit cannot start - blocking errors:", file=sys.stderr)
        for r in report.results:
            if not r.passed and r.blocking:
                print(f"  X {r.name} - {r.message}", file=sys.stderr)
                if r.suggestion:
                    print(f"    -> {r.suggestion}", file=sys.stderr)
        return None

    session = SessionManager()

    return BootstrapResult(
        config=cfg,
        state=state,
        tracker=tracker,
        session=session,
        preflight_report=report,
        log_path=log_path,
    )


def configure_qt_platform() -> str:
    """Detecte l'environnement display et configure QT_QPA_PLATFORM
    AVANT la creation de QApplication.

    Sur WSLg, on doit ajouter deux flags pour eviter les freezes :
      - QT_X11_NO_MITSHM=1 : desactive la shared-memory X11 (MIT-SHM).
        Le pont WSLg/XWayland gere mal MIT-SHM ; sans ce flag, l'app
        peut freeze apres un dialog modal (preflight, message box).
      - QT_AUTO_SCREEN_SCALE_FACTOR=0 + QT_SCALE_FACTOR=1 : neutralise
        le scaling auto qui cause des recalculs de geometrie infinis
        sur certaines configs WSLg + display HiDPI.
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return os.environ["QT_QPA_PLATFORM"]

    wayland = os.environ.get("WAYLAND_DISPLAY", "")
    display = os.environ.get("DISPLAY", "")
    is_wslg = os.path.isdir("/mnt/wslg")

    # WSLg : xcb (XWayland) avec les workarounds qui marchent.
    # wayland natif sur WSLg fige la fenetre, et xcb sans MIT-SHM-off
    # peut freeze apres un dialog modal (cas confirme).
    if is_wslg and display:
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        os.environ.setdefault("QT_X11_NO_MITSHM", "1")
        os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
        os.environ.setdefault("QT_SCALE_FACTOR", "1")
        return "xcb (WSLg via XWayland, MIT-SHM disabled)"

    if wayland and not is_wslg:
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        return "wayland"

    if display:
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        return "xcb (X11)"

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return "offscreen"