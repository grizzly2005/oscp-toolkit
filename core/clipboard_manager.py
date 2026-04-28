"""Clipboard Manager — historique des 50 derniers éléments + pins.

- Capture les éléments copiés DEPUIS L'APP (l'app appelle `capture(text)`
  chaque fois qu'elle copie quelque chose). On ne surveille PAS le
  clipboard système global (trop invasif).
- Catégorisation auto : ip / hash / cred / url / command / text.
- Copie vers le système : priorité xclip > wl-copy > clip.exe > Qt.
- Persistence : config/clipboard_pins.json.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .config_manager import ConfigManager
from .logger import get_logger

log = get_logger(__name__)


IP_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?$")
HASH_RE = re.compile(r"^(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{40}|[a-fA-F0-9]{64}|[a-fA-F0-9]{128})$")
URL_RE = re.compile(r"^https?://[^\s]+$")
CRED_RE = re.compile(r"^[A-Za-z][\w.\-]{1,40}:[^\s]+$")


def detect_category(text: str) -> str:
    stripped = text.strip()
    if "\n" in stripped:
        return "multi"
    if IP_RE.match(stripped):
        return "ip"
    if HASH_RE.match(stripped):
        return "hash"
    if URL_RE.match(stripped):
        return "url"
    if CRED_RE.match(stripped):
        return "credential"
    # heuristique commande : commence par un nom connu
    first = stripped.split()[0] if stripped else ""
    if first in {"nmap", "nxc", "smbclient", "hydra", "john", "hashcat",
                 "impacket-secretsdump", "gobuster", "ffuf", "curl", "wget",
                 "python", "python3", "nc", "sudo", "bash", "sh", "powershell",
                 "certutil", "iwr", "evil-winrm", "msfvenom"}:
        return "command"
    return "text"


@dataclass
class ClipboardItem:
    id: str
    text: str
    category: str = "text"
    pinned: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class ClipboardManager(QObject):
    item_added = pyqtSignal(object)
    item_removed = pyqtSignal(str)
    items_changed = pyqtSignal()

    def __init__(self, config_manager: ConfigManager, max_history: int = 50, parent=None):
        super().__init__(parent)
        self._cm = config_manager
        self.max_history = max_history
        self._items: List[ClipboardItem] = []
        self._load()

    # ----------------------------------------------------------

    def _load(self) -> None:
        data = self._cm.load("clipboard_pins")
        self.max_history = int(data.get("max_history", self.max_history))
        for it in data.get("items", []):
            try:
                self._items.append(ClipboardItem(**it))
            except TypeError:
                continue
        for it in data.get("pins", []):
            try:
                c = ClipboardItem(**it)
                c.pinned = True
                self._items.append(c)
            except TypeError:
                continue

    def _save(self) -> None:
        self._cm.save("clipboard_pins", {
            "items": [i.to_dict() for i in self._items if not i.pinned],
            "pins": [i.to_dict() for i in self._items if i.pinned],
            "max_history": self.max_history,
        })

    # ---------- API ----------

    def all(self) -> List[ClipboardItem]:
        # Pins en haut, puis récents
        pins = [i for i in self._items if i.pinned]
        non = sorted(
            (i for i in self._items if not i.pinned),
            key=lambda x: x.created_at,
            reverse=True,
        )
        return pins + non

    def capture(self, text: str, also_system: bool = True) -> Optional[ClipboardItem]:
        """Enregistre un élément. Évite les doublons consécutifs."""
        if not text:
            return None
        # Si le dernier non-pinné est identique, on ne duplique pas
        recent_non_pinned = [i for i in self._items if not i.pinned]
        if recent_non_pinned and recent_non_pinned[-1].text == text:
            if also_system:
                self.copy_to_system(text)
            return recent_non_pinned[-1]

        item = ClipboardItem(
            id=f"cb_{uuid.uuid4().hex[:8]}",
            text=text,
            category=detect_category(text),
        )
        self._items.append(item)
        self._enforce_limit()
        self._save()
        self.item_added.emit(item)
        self.items_changed.emit()
        if also_system:
            self.copy_to_system(text)
        return item

    def remove(self, item_id: str) -> None:
        self._items = [i for i in self._items if i.id != item_id]
        self._save()
        self.item_removed.emit(item_id)
        self.items_changed.emit()

    def toggle_pin(self, item_id: str) -> None:
        for i in self._items:
            if i.id == item_id:
                i.pinned = not i.pinned
                self._save()
                self.items_changed.emit()
                return

    def clear_non_pinned(self) -> None:
        self._items = [i for i in self._items if i.pinned]
        self._save()
        self.items_changed.emit()

    def search(self, query: str) -> List[ClipboardItem]:
        q = query.lower()
        return [i for i in self.all() if q in i.text.lower()]

    def _enforce_limit(self) -> None:
        non_pinned = [i for i in self._items if not i.pinned]
        if len(non_pinned) > self.max_history:
            # On vire les plus vieux non-pinnés
            non_pinned.sort(key=lambda x: x.created_at, reverse=True)
            keep = set(i.id for i in non_pinned[: self.max_history])
            self._items = [
                i for i in self._items
                if i.pinned or i.id in keep
            ]

    # ---------- copy vers le clipboard système ----------

    def copy_to_system(self, text: str) -> bool:
        """Chaîne de fallback xclip > xsel > wl-copy > clip.exe > Qt.

        Optimisation : si DISPLAY et WAYLAND_DISPLAY sont vides, on skippe
        directement xclip/xsel/wl-copy qui auraient timeout 3s chacun pour
        rien (pas de serveur X/Wayland accessible). Gain : jusqu'a 9s evites
        par capture sur un environnement headless.
        """
        has_display = bool(os.environ.get("DISPLAY"))
        has_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        # xclip
        if has_display and shutil.which("xclip"):
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    timeout=3,
                    check=True,
                )
                return True
            except (OSError, subprocess.SubprocessError):
                pass
        # xsel
        if has_display and shutil.which("xsel"):
            try:
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode("utf-8"),
                    timeout=3,
                    check=True,
                )
                return True
            except (OSError, subprocess.SubprocessError):
                pass
        # wl-copy (Wayland)
        if has_wayland and shutil.which("wl-copy"):
            try:
                subprocess.run(
                    ["wl-copy"],
                    input=text.encode("utf-8"),
                    timeout=3,
                    check=True,
                )
                return True
            except (OSError, subprocess.SubprocessError):
                pass
        # WSL : clip.exe
        if shutil.which("clip.exe"):
            try:
                subprocess.run(
                    ["clip.exe"],
                    input=text.encode("utf-16le"),
                    timeout=3,
                    check=True,
                )
                return True
            except (OSError, subprocess.SubprocessError):
                pass
        # Fallback Qt (même process)
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.clipboard().setText(text)
                return True
        except Exception:
            pass
        log.warning("No clipboard backend available - copy failed")
        return False
