"""Tool Manager.

Catalogue d'outils (config/tools.json). Responsabilités :

- CRUD sur la liste d'outils
- Vérif intégrité : pour chaque outil, check que le binaire existe
- Parsing des templates avec placeholders {{XXX}}
- Placeholders spéciaux : {{CRED:user}}, {{CRED:pass}}, {{CRED:hash}}
  résolus depuis le Credential Vault.
- Historique d'exécution par outil
- Signaux Qt pour la UI

Un outil :
{
  "name": "nxc",
  "category": "Enumeration",
  "tags": ["smb"],
  "path": "/usr/bin/nxc",
  "os_target": "multi",
  "description": "...",
  "dependencies": [],
  "templates": ["nxc smb {{IP}} -u {{CRED:user}} -p {{CRED:pass}}"],
  "doc_link": "cheatsheets/nxc.md",
  "favorite": true,
  "history": []
}
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from .config_manager import ConfigManager
from .logger import get_logger

log = get_logger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)(?::([A-Za-z0-9_]+))?\}\}")

_LEGACY_NMAP_TEMPLATES = {
    "nmap -sC -sV -oN \"$OSCP_NMAP/{{IP}}_tcp.txt\" {{IP}}",
    "nmap -A {{IP}} -oN \"$OSCP_NMAP/{{IP}}_advanced.txt\" {{IP}}",
    "sudo nmap -p- -sS -sU --min-rate 1000 --max-retries 1 -T4 -oN \"$OSCP_NMAP/{{IP}}_fast_tcp_udp.txt\" {{IP}}",
    "nmap -p- -T4 -n -Pn -oN \"$OSCP_NMAP/{{IP}}_fast_ports.txt\" {{IP}}",
    "sudo nmap --min-rate 5000 -p- -vvv -Pn -n -oG \"$OSCP_NMAP/{{IP}}_openPorts.gnmap\" {{IP}}",
    "nmap -p- -oN \"$OSCP_NMAP/{{IP}}_all_ports.txt\" {{IP}}",
    "nmap --top-ports {{TOP_PORTS}} -oN \"$OSCP_NMAP/{{IP}}_top_{{TOP_PORTS}}.txt\" {{IP}}",
    "nmap -sU --top-ports 100 -oN \"$OSCP_UDP/{{IP}}_udp_top100.txt\" {{IP}}",
    "nmap -sC -sV -p {{PORTS}} -oN \"$OSCP_SERVICES/{{IP}}_targeted.txt\" {{IP}}",
    "nmap --script=smb-vuln* -p 445 -oN \"$OSCP_SERVICES/{{IP}}_smb_vulns.txt\" {{IP}}",
    "nmap --script=ldap* -p 389,636 -oN \"$OSCP_SERVICES/{{IP}}_ldap.txt\" {{IP}}",
}

_LEGACY_GOBUSTER_TEMPLATES = {
    "gobuster dir -u http://{{IP}} -w /usr/share/wordlists/dirb/common.txt",
    "gobuster dir -u http://{{IP}} -w {{WORDLIST}} -x php,html,txt -t 50",
    "gobuster dir -u http://{{IP}} -w {{WORDLIST}} -x php,html,txt -t 50 -k",
    "gobuster vhost -u http://{{IP}} -w {{WORDLIST}} --append-domain",
    "gobuster dns -d {{DOMAIN}} -w {{WORDLIST}}",
}


class _IntegrityWorker(QThread):
    checked = pyqtSignal(dict)

    def __init__(self, items: List[Tuple[str, str]], parent: Optional[QObject] = None):
        super().__init__(parent)
        self._items = items

    def run(self) -> None:
        result: Dict[str, bool] = {}
        for name, path in self._items:
            if not path:
                result[name] = False
                continue
            p = Path(path)
            result[name] = p.exists() or bool(shutil.which(path))
        self.checked.emit(result)


@dataclass
class Tool:
    name: str
    category: str = "Divers"
    tags: List[str] = field(default_factory=list)
    path: str = ""
    os_target: str = "multi"
    description: str = ""
    dependencies: List[str] = field(default_factory=list)
    templates: List[str] = field(default_factory=list)
    doc_link: str = ""
    favorite: bool = False
    transfer_asset: bool = False
    history: List[Dict] = field(default_factory=list)
    present: Optional[bool] = None  # rempli par check_integrity

    def extract_placeholders(self, template: str) -> List[Tuple[str, Optional[str]]]:
        """Retourne [(key, subkey_or_None), ...] uniques dans l'ordre d'apparition."""
        seen = set()
        out = []
        for m in _PLACEHOLDER_RE.finditer(template):
            key = m.group(1)
            sub = m.group(2)
            token = (key, sub)
            if token not in seen:
                seen.add(token)
                out.append(token)
        return out

    def to_dict(self) -> Dict:
        d = asdict(self)
        d.pop("present", None)
        return d


class ToolManager(QObject):
    """Manager de la liste d'outils. Émis en broadcast pour la UI."""

    tools_changed = pyqtSignal()               # catalogue modifié
    tool_added = pyqtSignal(object)             # Tool
    tool_removed = pyqtSignal(str)              # tool name
    tool_updated = pyqtSignal(object)           # Tool
    integrity_checked = pyqtSignal(dict)        # {name: bool}

    def __init__(self, config_manager: ConfigManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cm = config_manager
        self._tools: Dict[str, Tool] = {}
        # Cache pour check_integrity : evite les os.path.exists() repetes
        # sur 42 outils dont certains sur /mnt/c/... (slow sur WSL).
        self._integrity_cache_ts: float = 0.0
        self._integrity_cache_data: Dict[str, bool] = {}
        self._integrity_cache_ttl: float = 60.0
        self._integrity_worker: Optional[_IntegrityWorker] = None
        self._load()

    # ----------------------------------------------------------

    def _load(self) -> None:
        data = self._cm.load("tools")
        defaults = self._load_default_tool_entries()
        self._tools = {}
        for item in data.get("tools", []):
            try:
                t = Tool(**item)
            except TypeError as exc:
                log.warning("Skip bad tool entry %s: %s", item, exc)
                continue
            default_item = defaults.get(t.name, {})
            if default_item.get("transfer_asset") and not t.transfer_asset:
                t.transfer_asset = True
            if not t.transfer_asset and "(transfer)" in t.description.lower():
                t.transfer_asset = True
            if t.name == "nmap":
                t.templates = self._merge_default_templates(
                    t.templates,
                    default_item.get("templates", []),
                    legacy_predicate=self._is_legacy_nmap_template,
                )
            elif t.name == "ligolo-ng":
                t.templates = self._merge_default_templates(
                    t.templates,
                    default_item.get("templates", []),
                    legacy_predicate=self._is_legacy_ligolo_template,
                )
                if not t.doc_link and default_item.get("doc_link"):
                    t.doc_link = default_item["doc_link"]
            elif t.name == "gobuster":
                t.templates = self._merge_default_templates(
                    t.templates,
                    default_item.get("templates", []),
                    legacy_predicate=self._is_legacy_gobuster_template,
                )
            self._tools[t.name] = t
        log.info("Loaded %d tools", len(self._tools))

    def _load_default_tool_entries(self) -> Dict[str, Dict]:
        path = self._cm.defaults_dir / "tools.default.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return {
            item.get("name", ""): item
            for item in data.get("tools", [])
            if isinstance(item, dict) and item.get("name")
        }

    @staticmethod
    def _merge_templates(current: List[str], defaults: List[str]) -> List[str]:
        merged = list(current)
        seen = set(current)
        for template in defaults:
            if template not in seen:
                merged.append(template)
                seen.add(template)
        return merged

    @staticmethod
    def _merge_default_templates(
        current: List[str],
        defaults: List[str],
        legacy_predicate=None,
    ) -> List[str]:
        if not defaults:
            return list(current)
        merged = list(defaults)
        seen = set(merged)
        for template in current:
            if legacy_predicate is not None and legacy_predicate(template):
                continue
            if template not in seen:
                merged.append(template)
                seen.add(template)
        return merged

    @staticmethod
    def _is_legacy_nmap_template(template: str) -> bool:
        return template in _LEGACY_NMAP_TEMPLATES

    @staticmethod
    def _is_legacy_ligolo_template(template: str) -> bool:
        normalized = template.replace("\\", "/")
        if normalized == "$BIN_LIN/network/ligolo/ligolo_proxy_lin -selfcert":
            return True
        if normalized.endswith("/network/ligolo/ligolo_proxy_lin -selfcert"):
            return True
        if "ligolo_agent_win.exe" in normalized and "/Temp/ag.exe" in normalized:
            return True
        if "ligolo_agent_lin" in normalized and "/tmp/ag" in normalized:
            return True
        return False

    @staticmethod
    def _is_legacy_gobuster_template(template: str) -> bool:
        return template in _LEGACY_GOBUSTER_TEMPLATES

    def _save(self) -> None:
        self._cm.save(
            "tools",
            {"tools": [t.to_dict() for t in self._tools.values()]},
        )

    # ---------- lecture ----------

    def all(self) -> List[Tool]:
        return list(self._tools.values())

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def by_category(self) -> Dict[str, List[Tool]]:
        buckets: Dict[str, List[Tool]] = {}
        for t in self._tools.values():
            buckets.setdefault(t.category, []).append(t)
        for lst in buckets.values():
            lst.sort(key=lambda x: (not x.favorite, x.name.lower()))
        return buckets

    def search(self, query: str) -> List[Tool]:
        q = query.lower().strip()
        if not q:
            return self.all()
        out = []
        for t in self._tools.values():
            hay = " ".join([
                t.name,
                t.category,
                t.description,
                " ".join(t.tags),
            ]).lower()
            if q in hay:
                out.append(t)
        return out

    def favorites(self) -> List[Tool]:
        return [t for t in self._tools.values() if t.favorite]

    # ---------- écriture ----------

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already exists")
        self._tools[tool.name] = tool
        self._save()
        self.invalidate_integrity_cache()
        self.tool_added.emit(tool)
        self.tools_changed.emit()

    def remove(self, name: str) -> None:
        if name not in self._tools:
            return
        del self._tools[name]
        self._save()
        self.invalidate_integrity_cache()
        self.tool_removed.emit(name)
        self.tools_changed.emit()

    def update(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self._save()
        self.invalidate_integrity_cache()
        self.tool_updated.emit(tool)
        self.tools_changed.emit()

    def toggle_favorite(self, name: str) -> None:
        t = self._tools.get(name)
        if t is None:
            return
        t.favorite = not t.favorite
        self._save()
        self.tool_updated.emit(t)
        self.tools_changed.emit()

    def record_usage(self, name: str, command: str) -> None:
        t = self._tools.get(name)
        if t is None:
            return
        t.history.append({"ts": time.time(), "command": command})
        if len(t.history) > 100:
            t.history = t.history[-100:]
        self._save()

    # ---------- intégrité ----------

    def check_integrity(self, force: bool = False) -> Dict[str, bool]:
        """Verifie la presence sur disque de chaque outil.

        Cache TTL : 60s. Passer `force=True` pour rafraichir (F5 ou
        modification d'un outil).
        """
        now = time.time()
        if (
            not force
            and self._integrity_cache_data
            and (now - self._integrity_cache_ts) < self._integrity_cache_ttl
        ):
            # Re-emit signal pour que les listeners rafraichissent
            # leur affichage meme avec le cache.
            self.integrity_checked.emit(self._integrity_cache_data)
            return self._integrity_cache_data

        result: Dict[str, bool] = {}
        for t in self._tools.values():
            if not t.path:
                t.present = None          # outils sans path (a transferer sur cible)
                result[t.name] = False
                continue
            p = Path(t.path)
            ok = p.exists() or bool(shutil.which(t.path))
            t.present = ok
            result[t.name] = ok
        self._integrity_cache_data = result
        self._integrity_cache_ts = now
        self.integrity_checked.emit(result)
        log.info(
            "Integrity check : %d/%d tools present",
            sum(1 for v in result.values() if v),
            len(result),
        )
        return result

    def check_integrity_async(self, force: bool = False) -> None:
        """Version non bloquante pour l'UI."""
        now = time.time()
        if (
            not force
            and self._integrity_cache_data
            and (now - self._integrity_cache_ts) < self._integrity_cache_ttl
        ):
            self.integrity_checked.emit(self._integrity_cache_data)
            return
        if self._integrity_worker is not None and self._integrity_worker.isRunning():
            return
        items = [(t.name, t.path) for t in self._tools.values()]
        worker = _IntegrityWorker(items, self)
        worker.checked.connect(self._on_integrity_checked_async)
        worker.finished.connect(lambda: setattr(self, "_integrity_worker", None))
        worker.finished.connect(worker.deleteLater)
        self._integrity_worker = worker
        worker.start()

    def _on_integrity_checked_async(self, result: Dict[str, bool]) -> None:
        for name, ok in result.items():
            t = self._tools.get(name)
            if t is not None:
                t.present = ok if t.path else None
        self._integrity_cache_data = result
        self._integrity_cache_ts = time.time()
        self.integrity_checked.emit(result)
        log.info(
            "Integrity check : %d/%d tools present",
            sum(1 for v in result.values() if v),
            len(result),
        )

    def invalidate_integrity_cache(self) -> None:
        """A appeler apres add/remove/update d'un outil."""
        self._integrity_cache_ts = 0.0
        self._integrity_cache_data = {}

    # ---------- templates ----------

    def render_template(
        self,
        template: str,
        values: Dict[str, str],
    ) -> str:
        """Remplace {{KEY}} et {{KEY:sub}} par les valeurs fournies.

        `values` accepte soit "KEY" soit "KEY:sub" comme clé.
        Les placeholders non fournis sont laissés tels quels (l'UI
        doit idéalement les avoir tous demandés).
        """
        def repl(m: re.Match) -> str:
            key = m.group(1)
            sub = m.group(2)
            full_key = f"{key}:{sub}" if sub else key
            if full_key in values:
                return values[full_key]
            if key in values:
                return values[key]
            return m.group(0)

        return _PLACEHOLDER_RE.sub(repl, template)
