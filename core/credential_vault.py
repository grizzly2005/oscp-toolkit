"""Credential Vault — table centrale des credentials découverts.

Persistence : config/credentials.json (via ConfigManager pour atomic).

Un credential :
{
  "id": "cred_1234567890",
  "username": "admin",
  "password": "Password1",
  "hash": "",
  "hash_type": "",
  "domain": "CORP",
  "type": "password",        # password / ntlm / sha1 / kerberos_ticket / key / other
  "source": "WEB01",         # machine/outil d'où ça vient
  "target": "*",             # machine où c'est testable, * = partout
  "notes": "",
  "created_at": 1690000000,
  "verified_on": []          # liste de machines où ça marche
}
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .config_manager import ConfigManager
from .logger import get_logger

log = get_logger(__name__)


CRED_TYPES = [
    "password",
    "ntlm",
    "sha1",
    "kerberos_ticket",
    "key",
    "other",
]


@dataclass
class Credential:
    id: str
    username: str = ""
    password: str = ""
    hash: str = ""
    hash_type: str = ""
    domain: str = ""
    type: str = "password"
    source: str = ""
    target: str = "*"
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    verified_on: List[str] = field(default_factory=list)

    def display_secret(self) -> str:
        if self.password:
            return self.password
        if self.hash:
            return self.hash
        return ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def new(cls, **kwargs) -> "Credential":
        cid = kwargs.pop("id", None) or f"cred_{uuid.uuid4().hex[:10]}"
        return cls(id=cid, **kwargs)


class CredentialVault(QObject):
    credential_added = pyqtSignal(object)
    credential_removed = pyqtSignal(str)
    credential_updated = pyqtSignal(object)
    vault_changed = pyqtSignal()

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self._cm = config_manager
        self._creds: Dict[str, Credential] = {}
        self._load()

    # ----------------------------------------------------------

    def _load(self) -> None:
        data = self._cm.load("credentials")
        for item in data.get("credentials", []):
            try:
                c = Credential(**item)
            except TypeError as exc:
                log.warning("Skip bad credential %s: %s", item, exc)
                continue
            if c.id in self._creds:
                log.warning("Duplicate credential id '%s' in JSON, last wins", c.id)
            self._creds[c.id] = c
        log.info("Loaded %d credentials", len(self._creds))

    def _save(self) -> None:
        self._cm.save(
            "credentials",
            {"credentials": [c.to_dict() for c in self._creds.values()]},
        )

    # ---------- lecture ----------

    def all(self) -> List[Credential]:
        return sorted(self._creds.values(), key=lambda c: c.created_at, reverse=True)

    def get(self, cid: str) -> Optional[Credential]:
        return self._creds.get(cid)

    def filter(
        self,
        source: Optional[str] = None,
        target: Optional[str] = None,
        type_: Optional[str] = None,
    ) -> List[Credential]:
        out = []
        for c in self._creds.values():
            if source and c.source != source:
                continue
            if target and c.target != target and c.target != "*":
                continue
            if type_ and c.type != type_:
                continue
            out.append(c)
        return out

    def usernames(self) -> List[str]:
        seen = set()
        for c in self._creds.values():
            if c.username:
                seen.add(c.username)
        return sorted(seen)

    def passwords(self) -> List[str]:
        seen = set()
        for c in self._creds.values():
            if c.password:
                seen.add(c.password)
        return sorted(seen)

    def hashes(self, hash_type: Optional[str] = None) -> List[Credential]:
        out = []
        for c in self._creds.values():
            if not c.hash:
                continue
            if hash_type and c.hash_type != hash_type:
                continue
            out.append(c)
        return out

    # ---------- écriture ----------

    def add(self, cred: Credential) -> Credential:
        if cred.id in self._creds:
            raise ValueError(f"Credential '{cred.id}' already exists")
        self._creds[cred.id] = cred
        self._save()
        self.credential_added.emit(cred)
        self.vault_changed.emit()
        return cred

    def add_simple(
        self,
        username: str = "",
        password: str = "",
        hash_: str = "",
        hash_type: str = "",
        source: str = "",
        target: str = "*",
        domain: str = "",
        notes: str = "",
        type_: Optional[str] = None,
    ) -> Credential:
        """API pratique pour créer rapidement."""
        t = type_ or ("ntlm" if hash_type.upper() in {"NTLM", "NT"} else
                      "password" if password else "other")
        cred = Credential.new(
            username=username,
            password=password,
            hash=hash_,
            hash_type=hash_type,
            domain=domain,
            source=source,
            target=target,
            notes=notes,
            type=t,
        )
        return self.add(cred)

    def remove(self, cid: str) -> None:
        if cid not in self._creds:
            return
        del self._creds[cid]
        self._save()
        self.credential_removed.emit(cid)
        self.vault_changed.emit()

    def update(self, cred: Credential) -> None:
        self._creds[cred.id] = cred
        self._save()
        self.credential_updated.emit(cred)
        self.vault_changed.emit()

    def mark_verified(self, cid: str, machine: str) -> None:
        c = self._creds.get(cid)
        if c is None:
            return
        if machine not in c.verified_on:
            c.verified_on.append(machine)
            self._save()
            self.credential_updated.emit(c)

    # ---------- placeholders ----------

    def resolve_placeholder(self, sub: str, cred: Optional[Credential] = None) -> Optional[str]:
        """Résout {{CRED:sub}} — si `cred` fourni, utilise celui-ci,
        sinon prend le premier match plausible."""
        if cred is None:
            if not self._creds:
                return None
            cred = self.all()[0]
        mapping = {
            "user": cred.username,
            "username": cred.username,
            "pass": cred.password,
            "password": cred.password,
            "hash": cred.hash,
            "ntlm": cred.hash if cred.hash_type.upper() == "NTLM" else "",
            "domain": cred.domain,
        }
        return mapping.get(sub.lower())

    # ---------- export / spray ----------

    def export_users_file(self, path) -> int:
        with open(path, "w", encoding="utf-8") as f:
            users = self.usernames()
            f.write("\n".join(users))
        return len(users)

    def export_passwords_file(self, path) -> int:
        with open(path, "w", encoding="utf-8") as f:
            passwords = self.passwords()
            f.write("\n".join(passwords))
        return len(passwords)

    def export_hashes_file(self, path, hash_type: Optional[str] = None) -> int:
        creds = self.hashes(hash_type)
        with open(path, "w", encoding="utf-8") as f:
            for c in creds:
                prefix = f"{c.username}:" if c.username else ""
                f.write(f"{prefix}{c.hash}\n")
            # Pas besoin d'un newline final supplementaire, chaque ligne en
            # a deja un. Mais on garantit qu'il y a au moins une ligne vide
            # de fin pour les outils qui s'attendent a EOF apres newline.
        return len(creds)

    def build_spray_command(
        self,
        target_ip: str,
        protocol: str = "smb",
        domain: Optional[str] = None,
    ) -> str:
        """Génère une commande nxc de password spray."""
        users = "\n".join(self.usernames()) or "USERS_FILE"
        pwds = "\n".join(self.passwords()) or "PASSWORDS_FILE"
        dom = f" -d {domain}" if domain else ""
        return (
            f"# Sauver users.txt:\n"
            f"# ({users})\n"
            f"# Sauver passwords.txt:\n"
            f"# ({pwds})\n"
            f"nxc {protocol} {target_ip} -u users.txt -p passwords.txt "
            f"--continue-on-success{dom}"
        )
