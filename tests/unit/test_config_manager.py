"""Tests pour core.config_manager.ConfigManager."""
import json
import pytest

from core.config_manager import ConfigError


def test_load_falls_back_to_default(tmp_config_dir, config_manager):
    defaults = tmp_config_dir / "defaults"
    (defaults / "foo.default.json").write_text('{"bar": 42}', encoding="utf-8")
    # Pas de config/foo.json -> doit restaurer depuis default
    data = config_manager.load("foo")
    assert data == {"bar": 42}
    # Le fichier config/foo.json doit maintenant exister
    assert (tmp_config_dir / "foo.json").exists()


def test_load_missing_default_raises(config_manager):
    with pytest.raises(ConfigError):
        config_manager.load("nonexistent")


def test_save_then_load_roundtrip(config_manager, tmp_config_dir):
    (tmp_config_dir / "defaults" / "x.default.json").write_text('{}', encoding="utf-8")
    config_manager.load("x")
    config_manager.save("x", {"a": 1, "b": [2, 3]})
    # Invalidate cache et relire
    config_manager.invalidate("x")
    data = config_manager.load("x")
    assert data == {"a": 1, "b": [2, 3]}


def test_save_atomic(config_manager, tmp_config_dir):
    (tmp_config_dir / "defaults" / "y.default.json").write_text('{}', encoding="utf-8")
    config_manager.load("y")
    config_manager.save("y", {"k": "v"})
    # Pas de .tmp residuel
    assert not (tmp_config_dir / "y.json.tmp").exists()
    assert (tmp_config_dir / "y.json").exists()


def test_migrations(config_manager, tmp_config_dir):
    (tmp_config_dir / "defaults" / "z.default.json").write_text('{"v": 1}', encoding="utf-8")
    data = config_manager.load("z")
    assert data == {"v": 1}

    # Enregistre une migration v1 -> v2
    def m1(old):
        new = dict(old)
        new["migrated"] = True
        return new

    config_manager.register_migration("z", 1, 2, m1)
    config_manager.set_target_version("z", 2)
    config_manager.invalidate("z")

    data = config_manager.load("z")
    assert data.get("migrated") is True

    # Verifie que version.json a ete mis a jour
    versions = json.loads((tmp_config_dir / "version.json").read_text())
    assert versions["z"] == 2
