"""Shared fixtures pour les tests."""
import os
import sys
from pathlib import Path
import pytest

# Force offscreen Qt pour les tests
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("DISPLAY", "")

# Ajoute la racine du projet au path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Cree un dossier config/ temporaire avec defaults minimaux."""
    cdir = tmp_path / "config"
    cdir.mkdir()
    defaults = cdir / "defaults"
    defaults.mkdir()
    return cdir


@pytest.fixture
def config_manager(tmp_config_dir):
    """ConfigManager qui pointe vers un tmp."""
    from core.config_manager import ConfigManager
    return ConfigManager(config_dir=tmp_config_dir)
