#!/usr/bin/env python3
"""OSCP Toolkit — entry point minimal.

Tout le travail d'init est delegue a app/bootstrap.py.
Ce fichier se limite a :
  1. delegate bootstrap
  2. run Qt app
  3. clean shutdown
"""
from __future__ import annotations

import os
import sys
import traceback

# S'execute depuis la racine, peu importe d'ou on lance
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from core.logger import get_logger


def _excepthook(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        get_logger("main").error("UNCAUGHT EXCEPTION:\n%s", tb)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _reset_workspace_state(result) -> None:
    """Vide les donnees de session utilisateur sans toucher aux notes."""
    try:
        result.config.save("scope", {"subnets": [], "machines": [], "pivots": []})
        result.config.invalidate("scope")
    except Exception:
        get_logger("main").exception("Cannot reset scope")
    try:
        result.config.reset("env_vars")
        result.config.invalidate("env_vars")
    except Exception:
        get_logger("main").exception("Cannot reset env vars")


def main() -> int:
    sys.excepthook = _excepthook

    from app.bootstrap import bootstrap, configure_qt_platform
    result = bootstrap()
    if result is None:
        return 2

    log = get_logger("main")

    # Qt platform (avant QApplication)
    platform = configure_qt_platform()
    log.info("Qt platform: %s", platform)

    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("OSCP Toolkit")
    app.setOrganizationName("OSCP Toolkit")

    from ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # Preflight dialog (warnings)
    from ui.preflight_dialog import PreflightDialog
    decisions = {
        "kill_orphans": False,
        "restore_session": False,
        "set_manual_ip": False,
        "reset_workspace": False,
    }
    if result.preflight_report.warnings:
        dlg = PreflightDialog(result.preflight_report)
        dlg.kill_orphans_requested.connect(lambda: decisions.update(kill_orphans=True))
        dlg.set_manual_ip_requested.connect(lambda: decisions.update(set_manual_ip=True))
        dlg.exec_()

    if decisions["kill_orphans"]:
        orphans = result.tracker.check_orphans()
        killed = result.tracker.kill_orphans(orphans)
        log.info("Killed %d orphan process(es)", killed)
    result.tracker.clear_session_file()

    # --- Demande explicite de restauration de session ---
    # Si une session existe, on demande a l'utilisateur. Comme ca, en cas
    # de session corrompue/buggee, il peut choisir "Demarrer vierge" et
    # reset le layout au passage.
    # Mode safe boot : OSCP_SAFE=1 python3 main.py -> aucun prompt, vierge.
    safe_boot = os.environ.get("OSCP_SAFE", "").lower() in ("1", "true", "yes")
    if safe_boot:
        log.info("OSCP_SAFE=1 -> skipping session restore prompt")
        try:
            result.session.clear()
        except Exception:
            pass
    elif result.session.has_previous():
        from PyQt5.QtWidgets import QMessageBox
        from datetime import datetime
        try:
            ts = result.session.path.stat().st_mtime
            age = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except OSError:
            age = "inconnue"
        box = QMessageBox()
        box.setWindowTitle("Session precedente")
        box.setIcon(QMessageBox.Question)
        box.setText(f"Une session precedente existe (sauvegardee : {age}).")
        box.setInformativeText(
            "Restaurer conserve le scope. Demarrer vierge vide IP, subnets, "
            "machines, pivots et variables de cible."
        )
        b_restore = box.addButton("Restaurer la session", QMessageBox.AcceptRole)
        b_blank = box.addButton("Demarrer vierge", QMessageBox.ActionRole)
        b_reset = box.addButton("Demarrer vierge + reset fenetre", QMessageBox.DestructiveRole)
        box.setDefaultButton(b_restore)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is b_restore:
            decisions["restore_session"] = True
        elif clicked is b_reset:
            # On supprime aussi le layout sauvegarde, donc reset complet
            try:
                layout_path = result.config.config_dir / "layout.json"
                if layout_path.exists():
                    layout_path.unlink()
                    log.info("layout.json supprime (demarrage vierge complet)")
                # Invalider le cache du ConfigManager : sinon
                # _apply_layout_from_config va lire l'ancien layout depuis
                # la RAM et la fenetre se ramene a l'ancienne position.
                result.config.invalidate("layout")
            except Exception:
                log.exception("Cannot remove layout.json")
            result.session.clear()
            decisions["reset_workspace"] = True
        else:
            # Demarrer vierge -> on garde le layout mais on jette la session
            result.session.clear()
            decisions["reset_workspace"] = True

    if decisions["reset_workspace"]:
        _reset_workspace_state(result)

    # Main window
    from ui.main_window import MainWindow
    win = MainWindow(
        config=result.config,
        tracker=result.tracker,
        session=result.session,
        preflight_report=result.preflight_report,
    )
    # Injecte app_state (optionnel, les modules peuvent l'utiliser ou pas)
    win._app_state = result.state
    win.show()

    if decisions["restore_session"] and result.session.has_previous():
        win.restore_session()
    if decisions["set_manual_ip"]:
        win.prompt_manual_ip()

    log.info("UI ready, entering event loop")
    rc = app.exec_()
    log.info("Event loop exited with code %d", rc)

    # Shutdown
    try:
        state = win.serialize_state()
        result.session.save(state)
    except Exception:
        log.exception("Error saving session")

    try:
        result.tracker.cleanup()
    except Exception:
        log.exception("Error during process cleanup")

    log.info("OSCP Toolkit stopped cleanly")
    return rc


if __name__ == "__main__":
    sys.exit(main())
