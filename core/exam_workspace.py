"""Exam workspace layout manager.

Creates and remembers the working folder where notes, scans, screenshots,
loot and transfer tools should live during an exam or lab run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .config_manager import ConfigManager
from .logger import get_logger

log = get_logger(__name__)


STRUCTURE = {
    "scans": ("nmap", "udp", "services"),
    "loot": ("interesting_files",),
    "exploits": (),
    "screenshots": (),
    "notes": (),
    "tools": (),
    "web": (),
}

LOOT_FILES = ("creds.txt", "hashes.txt", "users.txt")


def default_exam_root() -> Path:
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.exists() else Path.home()
    return base / "oscp-exam"


class ExamWorkspaceManager(QObject):
    changed = pyqtSignal(object)

    def __init__(
        self,
        config: ConfigManager,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._cfg = config
        self._root = self._load_root()
        self.ensure_structure()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def notes_dir(self) -> Path:
        return self._root / "notes"

    @property
    def screenshots_dir(self) -> Path:
        return self._root / "screenshots"

    @property
    def tools_dir(self) -> Path:
        return self._root / "tools"

    @property
    def scans_dir(self) -> Path:
        return self._root / "scans"

    @property
    def loot_dir(self) -> Path:
        return self._root / "loot"

    def env_exports(self) -> Dict[str, str]:
        return {
            "OSCP_EXAM": self._shell_path(self._root),
            "OSCP_SCANS": self._shell_path(self.scans_dir),
            "OSCP_NMAP": self._shell_path(self.scans_dir / "nmap"),
            "OSCP_UDP": self._shell_path(self.scans_dir / "udp"),
            "OSCP_SERVICES": self._shell_path(self.scans_dir / "services"),
            "OSCP_LOOT": self._shell_path(self.loot_dir),
            "OSCP_TOOLS": self._shell_path(self.tools_dir),
            "OSCP_WEB": self._shell_path(self._root / "web"),
        }

    def set_root(self, path: Path | str) -> Path:
        root = Path(path).expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        self._root = root
        self.ensure_structure()
        self._cfg.save("exam_workspace", {"root_path": str(self._root)})
        self.changed.emit(self._root)
        return self._root

    def ensure_structure(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        for top, children in STRUCTURE.items():
            top_dir = self._root / top
            top_dir.mkdir(parents=True, exist_ok=True)
            for child in children:
                (top_dir / child).mkdir(parents=True, exist_ok=True)
        for name in LOOT_FILES:
            p = self.loot_dir / name
            if not p.exists():
                p.write_text("", encoding="utf-8")
        log.info("Exam workspace ready: %s", self._root)

    def _load_root(self) -> Path:
        try:
            data = self._cfg.load("exam_workspace")
        except Exception:
            log.exception("Could not load exam workspace config")
            return default_exam_root()
        raw = str(data.get("root_path", "")).strip()
        return Path(raw).expanduser() if raw else default_exam_root()

    @staticmethod
    def _shell_path(path: Path) -> str:
        raw = str(path)
        drive = path.drive.rstrip(":").lower()
        if drive:
            rest = raw[2:].replace("\\", "/")
            return f"/mnt/{drive}{rest}"
        return raw.replace("\\", "/")
