"""Wordlist Manager — catalogue + génération custom.

Deux responsabilités :

1. Catalogue : liste des wordlists connues (chemins, catégories,
   vérification de présence / taille).

2. Génération custom : à partir d'une base (noms de users, mots du
   domaine cible), produire une wordlist avec mutations classiques :
       - capitalize (john / root / Root / ROOT)
       - nombres suffixés (root123, root2024, root01)
       - caractères spéciaux (!, @, #)
       - leet (a->4, e->3, i->1, o->0, s->5, t->7)
       - année courante +/- 5
       - combos (Root@2024, root!2024, Password123!)

On NE lance AUCUN scan. La wordlist est écrite sur disque et l'user
la passe à son outil (hashcat, hydra, crackmapexec, ...).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional, Set

from PyQt5.QtCore import QObject, pyqtSignal

from .config_manager import ConfigManager
from .logger import get_logger

log = get_logger(__name__)

_SECLISTS_ROOT = "/opt/SecLists"
_COMMON_SECLISTS_WORDLISTS = [
    (
        "SecLists web common",
        "Discovery/Web-Content/common.txt",
        "web-directories",
        "Web content rapide et fiable",
    ),
    (
        "SecLists web quickhits",
        "Discovery/Web-Content/quickhits.txt",
        "web-directories",
        "Web content tres rapide",
    ),
    (
        "SecLists raft small dirs",
        "Discovery/Web-Content/raft-small-directories.txt",
        "web-directories",
        "Repertoires web small",
    ),
    (
        "SecLists raft medium dirs",
        "Discovery/Web-Content/raft-medium-directories.txt",
        "web-directories",
        "Repertoires web medium",
    ),
    (
        "SecLists DirBuster medium",
        "Discovery/Web-Content/DirBuster-2007_directory-list-2.3-medium.txt",
        "web-directories",
        "DirBuster 2.3 medium",
    ),
    (
        "SecLists raft medium files",
        "Discovery/Web-Content/raft-medium-files.txt",
        "web-files",
        "Fichiers web medium",
    ),
    (
        "SecLists DNS top 5000",
        "Discovery/DNS/subdomains-top1million-5000.txt",
        "dns",
        "DNS/vhost shortlist",
    ),
    (
        "SecLists DNS top 20000",
        "Discovery/DNS/subdomains-top1million-20000.txt",
        "dns",
        "DNS/vhost medium",
    ),
    (
        "SecLists usernames shortlist",
        "Usernames/top-usernames-shortlist.txt",
        "usernames",
        "Usernames tres communs",
    ),
    (
        "SecLists names",
        "Usernames/Names/names.txt",
        "usernames",
        "Prenoms et noms courants",
    ),
    (
        "SecLists passwords top 1000",
        "Passwords/Common-Credentials/xato-net-10-million-passwords-1000.txt",
        "passwords",
        "Mots de passe top 1000",
    ),
    (
        "SecLists passwords top 10000",
        "Passwords/Common-Credentials/xato-net-10-million-passwords-10000.txt",
        "passwords",
        "Mots de passe top 10000",
    ),
    (
        "SecLists probable top 12000",
        "Passwords/Common-Credentials/probable-v2_top-12000.txt",
        "passwords",
        "Mots de passe probables",
    ),
    (
        "SecLists rockyou archive",
        "Passwords/Leaked-Databases/rockyou.txt.tar.gz",
        "passwords",
        "Rockyou compresse dans SecLists",
    ),
]


@dataclass
class WordlistEntry:
    name: str
    path: str
    category: str = "misc"
    description: str = ""
    size_bytes: int = 0
    lines: int = 0
    present: bool = False


class WordlistManager(QObject):
    catalog_changed = pyqtSignal()

    def __init__(
        self,
        config_manager: ConfigManager,
        custom_dir: Path | str = "data/wordlists",
        parent=None,
    ):
        super().__init__(parent)
        self._cm = config_manager
        self.custom_dir = Path(custom_dir)
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        self._entries: List[WordlistEntry] = []
        self._load()

    # ----------------------------------------------------------

    def _load(self) -> None:
        data = self._cm.load("wordlists")
        self._entries = []
        for it in data.get("wordlists", []):
            try:
                e = WordlistEntry(**it)
            except TypeError:
                continue
            self._append_entry(e)
        for e in self._load_default_entries():
            self._append_entry(e)
        for e in self._common_seclists_entries():
            self._append_entry(e)
        # Custom générées : on les ajoute au catalogue
        for p in sorted(self.custom_dir.glob("*.txt")):
            self._append_entry(WordlistEntry(
                    name=p.stem, path=str(p), category="custom",
                    description="Wordlist générée localement",
                ))
        self.refresh_metadata()

    def _load_default_entries(self) -> List[WordlistEntry]:
        path = self._cm.defaults_dir / "wordlists.default.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        entries: List[WordlistEntry] = []
        for it in data.get("wordlists", []):
            try:
                entries.append(WordlistEntry(**it))
            except TypeError:
                continue
        return entries

    def _common_seclists_entries(self) -> List[WordlistEntry]:
        entries: List[WordlistEntry] = []
        for name, relative_path, category, description in _COMMON_SECLISTS_WORDLISTS:
            entries.append(WordlistEntry(
                name=name,
                path=f"{_SECLISTS_ROOT}/{relative_path}",
                category=category,
                description=description,
            ))
        return entries

    def _append_entry(self, entry: WordlistEntry) -> None:
        normalized = str(Path(entry.path))
        for existing in self._entries:
            if str(Path(existing.path)) == normalized:
                return
        self._entries.append(entry)

    def _save(self) -> None:
        self._cm.save("wordlists", {
            "wordlists": [
                {
                    "name": e.name,
                    "path": e.path,
                    "category": e.category,
                    "description": e.description,
                    "size_bytes": e.size_bytes,
                    "lines": e.lines,
                }
                for e in self._entries
            ],
            "custom": [],
        })

    # ---------- catalogue ----------

    def all(self) -> List[WordlistEntry]:
        return list(self._entries)

    def by_category(self) -> dict:
        out: dict = {}
        for e in self._entries:
            out.setdefault(e.category, []).append(e)
        return out

    def refresh_metadata(self) -> None:
        for e in self._entries:
            p = Path(e.path)
            local_exists = p.exists()
            if local_exists or _wsl_file_exists(e.path):
                e.present = True
                if local_exists:
                    try:
                        e.size_bytes = p.stat().st_size
                    except OSError:
                        e.size_bytes = 0
                    # Estimation rapide du nb de lignes pour les petits fichiers
                    if e.size_bytes < 5 * 1024 * 1024:        # <5 MB
                        try:
                            with open(p, "rb") as f:
                                e.lines = sum(1 for _ in f)
                        except OSError:
                            e.lines = 0
                    else:
                        e.lines = 0        # on évite de scanner rockyou
                else:
                    e.size_bytes = 0
                    e.lines = 0
            else:
                e.present = False

    def add(self, entry: WordlistEntry) -> None:
        self._entries.append(entry)
        self._save()
        self.catalog_changed.emit()

    def remove(self, path: str) -> None:
        self._entries = [e for e in self._entries if e.path != path]
        self._save()
        self.catalog_changed.emit()

    # ---------- mutations ----------

    def generate_custom(
        self,
        base_words: Iterable[str],
        output_name: str,
        capitalize: bool = True,
        numbers: bool = True,
        specials: bool = True,
        years: bool = True,
        leet: bool = True,
        combos: bool = True,
    ) -> Path:
        """Crée une wordlist depuis `base_words` avec les mutations demandées.

        Écrit dans data/wordlists/<output_name>.txt.
        """
        base = [w.strip() for w in base_words if w and w.strip()]
        if not base:
            raise ValueError("No base words provided")

        seen: Set[str] = set()
        out: List[str] = []

        def add(word: str) -> None:
            if word and word not in seen:
                seen.add(word)
                out.append(word)

        current_year = datetime.datetime.now().year
        year_list = [str(y) for y in range(current_year - 5, current_year + 2)]
        nums = ["123", "1234", "12345", "0", "1", "01", "11", "69", "99", "007", "321"]
        specials_list = ["!", "@", "#", "$", "?", "*", "!!", "@@", "!@", "!1"]

        for word in base:
            variants = [word]
            if capitalize:
                variants += [
                    word.capitalize(),
                    word.upper(),
                    word.lower(),
                    word.title(),
                ]
            # doublon interne, on laisse le set s'en occuper
            base_variants = list(dict.fromkeys(variants))

            for v in base_variants:
                add(v)
                if leet:
                    add(_leet(v))
                if numbers:
                    for n in nums:
                        add(v + n)
                        add(n + v)
                if years:
                    for y in year_list:
                        add(v + y)
                if specials:
                    for s in specials_list:
                        add(v + s)
                        add(s + v)
                if combos:
                    for y in year_list[:3]:                 # moins de combos
                        for s in specials_list[:4]:
                            add(v + y + s)
                            add(v + s + y)
                            add(v.capitalize() + y + s)

        safe = re.sub(r"[^\w\-.]+", "_", output_name).strip("_") or "custom"
        target = self.custom_dir / f"{safe}.txt"
        with open(target, "w", encoding="utf-8") as f:
            for w in out:
                f.write(w + "\n")

        log.info("Generated wordlist %s (%d words)", target, len(out))
        # Ajout au catalogue si pas déjà là
        if not any(e.path == str(target) for e in self._entries):
            self._entries.append(WordlistEntry(
                name=safe, path=str(target), category="custom",
                description=f"{len(out)} mots générés",
                size_bytes=target.stat().st_size, lines=len(out),
                present=True,
            ))
            self._save()
            self.catalog_changed.emit()
        return target


# --------------------------------------------------------------
# Helpers
# --------------------------------------------------------------

_LEET_MAP = str.maketrans({
    "a": "4", "A": "4",
    "e": "3", "E": "3",
    "i": "1", "I": "1",
    "o": "0", "O": "0",
    "s": "5", "S": "5",
    "t": "7", "T": "7",
    "g": "9", "G": "9",
    "b": "8", "B": "8",
})


def _leet(word: str) -> str:
    return word.translate(_LEET_MAP)


@lru_cache(maxsize=512)
def _wsl_file_exists(path: str) -> bool:
    if os.name != "nt" or not path.startswith("/"):
        return False
    if shutil.which("wsl") is None:
        return False
    try:
        proc = subprocess.run(
            ["wsl", "-e", "test", "-f", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0
