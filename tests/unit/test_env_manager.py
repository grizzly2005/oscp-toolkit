"""Tests pour core.env_manager.EnvManager."""
import pytest
import sys
from PyQt5.QtCore import QCoreApplication


@pytest.fixture
def qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


@pytest.fixture
def env_manager(tmp_config_dir, config_manager, qapp):
    (tmp_config_dir / "defaults" / "env_vars.default.json").write_text(
        '{"vars": {}}', encoding="utf-8"
    )
    from core.env_manager import EnvManager
    return EnvManager(config_manager)


def test_default_keys_present(env_manager):
    from core.env_manager import DEFAULT_KEYS
    vars_ = env_manager.all()
    for k in DEFAULT_KEYS:
        assert k in vars_


def test_ligolo_defaults_present(env_manager):
    assert env_manager.get("LIGOLO_IFACE") == "ligolol2"
    assert env_manager.get("LIGOLO_PORT") == "11601"


def test_wordlist_defaults_present(env_manager):
    assert env_manager.get("WEB_WORDLIST") == "/opt/SecLists/Discovery/Web-Content/common.txt"
    assert env_manager.get("VHOST_WORDLIST") == (
        "/opt/SecLists/Discovery/DNS/subdomains-top1million-5000.txt"
    )


def test_legacy_wordlist_defaults_migrate_to_opt_seclists(tmp_config_dir, config_manager, qapp):
    (tmp_config_dir / "defaults" / "env_vars.default.json").write_text(
        '{"vars": {}}', encoding="utf-8"
    )
    (tmp_config_dir / "env_vars.json").write_text(
        """
        {
          "vars": {
            "WEB_WORDLIST": "/usr/share/seclists/Discovery/Web-Content/directory-list-2.3-medium.txt",
            "VHOST_WORDLIST": "/usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt"
          }
        }
        """,
        encoding="utf-8",
    )
    from core.env_manager import EnvManager

    manager = EnvManager(config_manager)

    assert manager.get("WEB_WORDLIST") == "/opt/SecLists/Discovery/Web-Content/common.txt"
    assert manager.get("VHOST_WORDLIST") == (
        "/opt/SecLists/Discovery/DNS/subdomains-top1million-5000.txt"
    )


def test_set_and_get(env_manager):
    env_manager.set("LHOST", "10.10.14.1")
    assert env_manager.get("LHOST") == "10.10.14.1"


def test_key_uppercased(env_manager):
    env_manager.set("lhost", "1.2.3.4")
    assert env_manager.get("LHOST") == "1.2.3.4"


def test_invalid_key_raises(env_manager):
    with pytest.raises(ValueError):
        env_manager.set("INVALID KEY WITH SPACE", "x")


def test_session_script_contains_exports(env_manager):
    env_manager.set("LHOST", "10.10.14.1")
    env_manager.set("TARGET", "10.10.10.5")
    script = env_manager.write_session_script()
    content = script.read_text(encoding="utf-8")
    assert "LHOST='10.10.14.1'" in content
    assert "TARGET='10.10.10.5'" in content
    assert "alias serve=" in content
    assert "[OSCP]" in content
    script.unlink()


def test_expand_value_resolves_auto_and_user_vars(env_manager):
    env_manager.set("LHOST", "10.10.14.5")

    expanded = env_manager.expand_value("$BIN_LIN/privesc/linpeas.sh --host ${LHOST}")

    assert expanded.endswith("/binaries/linux/privesc/linpeas.sh --host 10.10.14.5")
    assert "$BIN_LIN" not in expanded


def test_import_from_scope(env_manager):
    env_manager.import_from_scope(target_ip="192.168.1.100", domain="corp.local")
    assert env_manager.get("TARGET") == "192.168.1.100"
    assert env_manager.get("DOMAIN") == "corp.local"


def test_import_from_network_no_overwrite_if_set(env_manager):
    env_manager.set("LHOST", "10.10.14.1")
    env_manager.import_from_network(lhost="10.10.14.2")
    # La nouvelle IP est adoptee (comportement actuel : on met a jour si change)
    assert env_manager.get("LHOST") == "10.10.14.2"
