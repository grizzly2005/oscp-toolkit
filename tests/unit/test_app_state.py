"""Tests pour core.app_state.AppState."""
import pytest
from PyQt5.QtCore import QCoreApplication
import sys


@pytest.fixture
def qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


def test_env_get_set(tmp_config_dir, config_manager, qapp):
    (tmp_config_dir / "defaults" / "env_vars.default.json").write_text(
        '{"vars": {"LHOST": "10.10.14.1"}}', encoding="utf-8"
    )
    from core.app_state import AppState
    state = AppState(config_manager)

    assert state.env_get("LHOST") == "10.10.14.1"
    state.env_set("TARGET", "10.10.10.5")
    assert state.env_get("TARGET") == "10.10.10.5"


def test_update_partial(tmp_config_dir, config_manager, qapp):
    (tmp_config_dir / "defaults" / "ui_prefs.default.json").write_text(
        '{"theme": "dark", "central_mode": "tabs"}', encoding="utf-8"
    )
    from core.app_state import AppState
    state = AppState(config_manager)

    state.update("ui_prefs", {"central_mode": "quad"})
    prefs = state.ui_prefs()
    assert prefs["theme"] == "dark"
    assert prefs["central_mode"] == "quad"


def test_namespace_changed_signal(tmp_config_dir, config_manager, qapp):
    (tmp_config_dir / "defaults" / "env_vars.default.json").write_text(
        '{"vars": {}}', encoding="utf-8"
    )
    from core.app_state import AppState
    state = AppState(config_manager)

    received = []
    state.namespace_changed.connect(lambda ns: received.append(ns))
    state.set("env_vars", {"vars": {"LHOST": "1.2.3.4"}})

    # Process pending signals
    qapp.processEvents()
    assert "env_vars" in received
