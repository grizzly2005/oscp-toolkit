"""Smoke tests for the compact UI polish pass."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget

from core.config_manager import ConfigManager
from core.preflight import PreflightReport
from core.process_tracker import ProcessTracker
from core.session import SessionManager
from ui.main_window import MainWindow
from ui.terminal_tab import TerminalTab
from ui.widgets import frozen_updates


def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        if os.name == "nt":
            os.environ["QT_QPA_PLATFORM"] = "minimal"
        app = QApplication([])
    return app


def test_ui_prefs_default_contains_compact_polish_keys() -> None:
    data = json.loads(Path("config/defaults/ui_prefs.default.json").read_text())
    assert data["visual_density"] == "compact"
    assert data["terminal_fast_render_indicator"] is True
    assert data["reduce_motion"] is True
    assert data["toolbar_style"] == "compact"


@pytest.mark.skipif(os.name == "nt", reason="Qt widget smoke is unstable in headless Windows")
def test_frozen_updates_restores_previous_state() -> None:
    _qapp()
    widget = QWidget()
    assert widget.updatesEnabled()
    with frozen_updates(widget):
        assert not widget.updatesEnabled()
    assert widget.updatesEnabled()


class _DummyWorker(QObject):
    output_received = pyqtSignal(str)
    finished_signal = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    unresponsive = pyqtSignal()
    alive_again = pyqtSignal()

    def send_input(self, _data: str) -> None:
        pass

    def notify_input_sent(self) -> None:
        pass

    def request_stop(self, graceful: bool = True) -> None:
        pass


@pytest.mark.skipif(os.name == "nt", reason="Qt widget smoke is unstable in headless Windows")
def test_terminal_fast_render_badge_shows_on_large_output() -> None:
    _qapp()
    worker = _DummyWorker()
    tab = TerminalTab(worker)  # type: ignore[arg-type]
    tab._on_output_raw("ffuf-progress\r" + ("x" * 50_000))
    tab._flush_pending()
    assert tab._fast_badge.isVisible()
    tab.disconnect_worker_signals()
    tab.deleteLater()


@pytest.mark.skipif(os.name == "nt", reason="Qt widget smoke is unstable in headless Windows")
def test_main_window_smoke_instantiates_compact_launcher(tmp_path) -> None:
    _qapp()
    cfg_dir = tmp_path / "config"
    shutil.copytree(Path("config/defaults"), cfg_dir / "defaults")
    cfg = ConfigManager(config_dir=cfg_dir)
    tracker = ProcessTracker(tmp_path / "pids.json")
    session = SessionManager(tmp_path / "last_session.json")
    win = MainWindow(cfg, tracker, session, PreflightReport())
    try:
        assert win.findChild(QWidget, "welcomePage") is not None
        assert win.findChild(QWidget, "main_toolbar") is not None
        win._central.set_mode("quad")
        win._central.set_mode("tabs")
        win._dock_docs.show()
        win._dock_docs.hide()
    finally:
        win._network.stop()
        win._session_autosave_timer.stop()
        tracker.cleanup()
        win.close()
