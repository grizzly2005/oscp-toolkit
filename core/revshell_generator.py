"""Reverse Shell Generator — offline, 100% local.

Consomme config/revshells.json, substitue les placeholders
{{LHOST}} / {{LPORT}}, propose encoding (base64, URL, PowerShell -Enc)
et commandes msfvenom associées. Aucune API web.
"""

from __future__ import annotations

import base64
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config_manager import ConfigManager
from .encoder import encode_base64, encode_url, encode_powershell_base64
from .logger import get_logger

log = get_logger(__name__)


@dataclass
class GeneratedShell:
    key: str
    lang: str
    os: str
    description: str
    payload: str
    encoded: Dict[str, str]


class RevshellGenerator:
    def __init__(self, config_manager: ConfigManager):
        self._cm = config_manager
        self._data = self._cm.load("revshells")

    def reload(self) -> None:
        self._data = self._cm.load("revshells")

    # ----------------------------------------------------------

    def available_shells(self, os_filter: Optional[str] = None) -> List[str]:
        """Clés des shells dispo. os_filter: 'linux' / 'windows' / 'multi'."""
        shells = self._data.get("shells", {})
        if os_filter is None:
            return list(shells.keys())
        return [
            k for k, v in shells.items()
            if v.get("os") in (os_filter, "multi")
        ]

    def listener_keys(self) -> List[str]:
        return list(self._data.get("listeners", {}).keys())

    def msfvenom_keys(self) -> List[str]:
        return list(self._data.get("msfvenom_templates", {}).keys())

    # ----------------------------------------------------------

    def generate(
        self,
        shell_key: str,
        lhost: str,
        lport: int,
        encodings: Optional[List[str]] = None,
    ) -> GeneratedShell:
        shells = self._data.get("shells", {})
        cfg = shells.get(shell_key)
        if cfg is None:
            raise KeyError(f"Unknown shell '{shell_key}'")
        payload = cfg["payload"].replace("{{LHOST}}", lhost).replace(
            "{{LPORT}}", str(lport))

        encoded: Dict[str, str] = {}
        for enc in (encodings or []):
            enc_l = enc.lower()
            try:
                if enc_l == "base64":
                    encoded["base64"] = encode_base64(payload)
                elif enc_l == "url":
                    encoded["url"] = encode_url(payload)
                elif enc_l in ("powershell_b64", "ps_encoded", "ps_base64"):
                    encoded["powershell_b64"] = encode_powershell_base64(payload)
            except Exception as exc:
                log.warning("Encoding %s failed: %s", enc, exc)
                encoded[enc_l] = f"ERR: {exc}"

        return GeneratedShell(
            key=shell_key,
            lang=cfg.get("lang", ""),
            os=cfg.get("os", "multi"),
            description=cfg.get("description", ""),
            payload=payload,
            encoded=encoded,
        )

    def generate_variants(
        self,
        lhost: str,
        lport: int,
        os_filter: Optional[str] = None,
        encodings: Optional[List[str]] = None,
    ) -> List[GeneratedShell]:
        out = []
        for key in self.available_shells(os_filter):
            out.append(self.generate(key, lhost, lport, encodings))
        return out

    def listener_command(self, key: str, lport: int) -> str:
        listeners = self._data.get("listeners", {})
        tpl = listeners.get(key)
        if not tpl:
            raise KeyError(f"Unknown listener '{key}'")
        return tpl.replace("{{LPORT}}", str(lport))

    def msfvenom_command(self, key: str, lhost: str, lport: int) -> str:
        templates = self._data.get("msfvenom_templates", {})
        tpl = templates.get(key)
        if not tpl:
            raise KeyError(f"Unknown msfvenom template '{key}'")
        return tpl.replace("{{LHOST}}", lhost).replace("{{LPORT}}", str(lport))
