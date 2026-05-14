"""Env Manager — variables d'environnement pilotees manuellement.

Centralise les variables injectees dans les terminaux externes :
  LHOST, LPORT, TARGET, DOMAIN, USER, PASS, HASH, PENTEST_DIR, etc.

Philosophie :
  - Aucune automatisation intrusive : l'utilisateur pilote tout
  - Un bouton "Pull from scope" propose la valeur courante, mais n'ecrit rien
    sans validation
  - Persistence : config/env_vars.json via ConfigManager
"""
from __future__ import annotations

import re
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .config_manager import ConfigManager
from .logger import get_logger

log = get_logger(__name__)


DEFAULT_VALUES: Dict[str, str] = {
    "LHOST": "",
    "LPORT": "4444",
    "TARGET": "",
    "DOMAIN": "",
    "USER": "",
    "PASS": "",
    "HASH": "",
    "IFACE": "tun0",
    "LIGOLO_IFACE": "ligolol2",
    "LIGOLO_PORT": "11601",
    "WEB_WORDLIST": "/opt/SecLists/Discovery/Web-Content/common.txt",
    "VHOST_WORDLIST": "/opt/SecLists/Discovery/DNS/subdomains-top1million-5000.txt",
    "DNS_WORDLIST": "/opt/SecLists/Discovery/DNS/subdomains-top1million-5000.txt",
}

_LEGACY_DEFAULT_VALUES: Dict[str, str] = {
    "WEB_WORDLIST": "/usr/share/seclists/Discovery/Web-Content/directory-list-2.3-medium.txt",
    "VHOST_WORDLIST": "/usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt",
    "DNS_WORDLIST": "/usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt",
}

DEFAULT_KEYS: List[str] = list(DEFAULT_VALUES)

# Variables auto-injectees dans le shell des terminaux externes.
#
# Les paths sont resolus dynamiquement par rapport au pentest_root
# (parent du toolkit). Structure attendue :
#   <pentest_root>/
#     toolkit/
#     wordlists/
#     binaries/{windows,linux}/
#     scripts/
#
# Si l'utilisateur peut override via config/env_vars.json (priorite sur
# les valeurs auto).
from core.paths import PATHS as _PATHS

_PENTEST_ROOT = str(_PATHS.project_root.parent)

_AUTO_VARS = {
    "PENTEST_DIR": _PENTEST_ROOT,
    "WORDLISTS":   f"{_PENTEST_ROOT}/wordlists",
    "BIN_WIN":     f"{_PENTEST_ROOT}/binaries/windows",
    "BIN_LIN":     f"{_PENTEST_ROOT}/binaries/linux",
    "SCRIPTS":     f"{_PENTEST_ROOT}/scripts",
}

_ALIASES = [
    ("serve",    "python3 -m http.server 8000"),
    ("servewin", "python3 -m http.server 8000 --directory $BIN_WIN"),
    ("servelin", "python3 -m http.server 8000 --directory $BIN_LIN"),
    ("listener", "rlwrap nc -lvnp ${LPORT:-4444}"),
    ("cdpen",    "cd $PENTEST_DIR"),
    ("cdtk",     "cd $PENTEST_DIR/toolkit"),
]

_ENV_TOKEN_RE = re.compile(r"\$(\w+)|\$\{(\w+)\}|%(\w+)%")


class EnvManager(QObject):
    """Gere les variables d'env injectees dans les terminaux externes."""

    changed = pyqtSignal()

    def __init__(self, config: ConfigManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cm = config
        self._vars: Dict[str, str] = {}
        self._load()

    # -- Persistence ---------------------------------------------------------

    def _load(self) -> None:
        data = self._cm.load("env_vars")
        self._vars = dict(data.get("vars", {}))
        for k, v in DEFAULT_VALUES.items():
            self._vars.setdefault(k, v)
        if self._migrate_legacy_defaults():
            self._save()
        log.info("EnvManager loaded: %d vars", len(self._vars))

    def _save(self) -> None:
        self._cm.save("env_vars", {"vars": dict(self._vars)})

    def _migrate_legacy_defaults(self) -> bool:
        changed = False
        for key, old_value in _LEGACY_DEFAULT_VALUES.items():
            if self._vars.get(key) == old_value:
                self._vars[key] = DEFAULT_VALUES[key]
                changed = True
        return changed

    # -- API -----------------------------------------------------------------

    def all(self) -> Dict[str, str]:
        return dict(self._vars)

    def resolved_vars(self) -> Dict[str, str]:
        merged = dict(_AUTO_VARS)
        merged.update({k: v for k, v in self._vars.items() if v})
        return merged

    def expand_value(self, value: str) -> str:
        """Expand toolkit variables such as $BIN_LIN and ${LHOST}."""
        vars_ = self.resolved_vars()

        def repl(match: re.Match) -> str:
            key = match.group(1) or match.group(2) or match.group(3) or ""
            return vars_.get(key, match.group(0))

        return _ENV_TOKEN_RE.sub(repl, value)

    def get(self, key: str, default: str = "") -> str:
        return self._vars.get(key, default)

    def set(self, key: str, value: str) -> None:
        key = key.strip().upper()
        if not key or not key.replace("_", "").isalnum():
            raise ValueError(f"Cle invalide : '{key}'")
        self._vars[key] = value.strip()
        self._save()
        self.changed.emit()

    def remove(self, key: str) -> None:
        if key in self._vars and key not in DEFAULT_KEYS:
            del self._vars[key]
            self._save()
            self.changed.emit()

    def clear_value(self, key: str) -> None:
        if key in self._vars:
            self._vars[key] = ""
            self._save()
            self.changed.emit()

    def reset_to_defaults(self) -> None:
        data = self._cm.reset("env_vars")
        self._vars = dict(data.get("vars", {}))
        for k, v in DEFAULT_VALUES.items():
            self._vars.setdefault(k, v)
        self.changed.emit()

    def import_from_scope(self, target_ip: str = "", domain: str = "") -> None:
        changed = False
        if target_ip:
            self._vars["TARGET"] = target_ip
            changed = True
        if domain:
            self._vars["DOMAIN"] = domain
            changed = True
        if changed:
            self._save()
            self.changed.emit()

    def import_from_network(self, lhost: str = "") -> None:
        if lhost and self._vars.get("LHOST") != lhost:
            self._vars["LHOST"] = lhost
            self._save()
            self.changed.emit()

    # -- Script shell --------------------------------------------------------

    def write_session_script(self, extra_exports: Optional[Dict[str, str]] = None) -> Path:
        """Ecrit /tmp/oscp_session_<uuid>.sh et retourne le chemin."""
        merged = self.resolved_vars()
        if extra_exports:
            merged.update(extra_exports)

        lines: List[str] = [
            "#!/bin/bash",
            "# OSCP Toolkit -- session init",
            "# Auto-genere -- ne pas editer directement",
            "",
            "# Heriter du setup user",
            "[ -f ~/.bashrc ] && source ~/.bashrc",
            "",
            "# -- Variables OSCP -----------------------------",
        ]
        for k, v in merged.items():
            escaped = v.replace("'", "'\"'\"'")
            lines.append(f"export {k}='{escaped}'")

        lines += [
            "",
            "# PATH avec les binaires locaux",
            'export PATH="$PATH:$BIN_LIN/ad:$BIN_LIN/privesc:$BIN_LIN/network:$SCRIPTS"',
            "",
            "# -- Aliases ------------------------------------",
        ]
        for name, cmd in _ALIASES:
            lines.append(f"alias {name}='{cmd}'")

        lines += [
            "",
            "# -- Prompt OSCP --------------------------------",
            r"""export PS1='\[\033[38;5;208m\][OSCP]\[\033[0m\] \[\033[36m\]\u@\h\[\033[0m\]:\[\033[33m\]\w\[\033[0m\]\$ '""",
            "",
            "# -- Banniere -----------------------------------",
            'echo ""',
            'echo -e "\\033[38;5;208m=== OSCP Toolkit -- Session active ===\\033[0m"',
            'echo -e "LHOST=\\033[33m$LHOST\\033[0m  LPORT=\\033[33m$LPORT\\033[0m"',
            'echo -e "TARGET=\\033[33m$TARGET\\033[0m  DOMAIN=\\033[33m$DOMAIN\\033[0m"',
            'echo -e "Aliases: serve, servewin, servelin, listener, cdpen, cdtk"',
            'echo ""',
            "",
        ]

        script_path = Path(tempfile.gettempdir()) / f"oscp_session_{uuid.uuid4().hex[:8]}.sh"
        script_path.write_text("\n".join(lines), encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR | stat.S_IWUSR)

        log.info("Session script written: %s", script_path)
        return script_path

    def cleanup_old_scripts(self, keep_recent: int = 5) -> int:
        tmp = Path(tempfile.gettempdir())
        # Race-safe : si un fichier disparait entre glob et stat (cleanup
        # parallele, autre process), on l'ignore. Si on ne peut pas stat
        # (permissions), on le met en bas de la liste pour ne pas le toucher.
        scripts: List[Path] = []
        for p in tmp.glob("oscp_session_*.sh"):
            try:
                _ = p.stat().st_mtime
                scripts.append(p)
            except OSError:
                continue
        scripts.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0)
        removed = 0
        if len(scripts) > keep_recent:
            for old in scripts[:-keep_recent]:
                try:
                    old.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed
