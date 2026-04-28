"""Scope Manager — subnets + machines + pivots.

Persistence : config/scope.json (via ConfigManager).

Structures :

subnet = {cidr, label, pivot_via (machine_id), machines (ids)}
machine = {
  id, ip, hostname, os, status (todo/in_progress/rooted/skipped),
  difficulty, notes_path, points, ports, services, tags,
  proof: {user_flag, proof_flag, screenshots, checklist}
}
pivot = {from_machine_id, to_cidr, tool (ligolo/chisel/ssh), port, active}

Le Target Board consomme les machines filtrées par status.
"""

from __future__ import annotations

import ipaddress
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .config_manager import ConfigManager
from .logger import get_logger

log = get_logger(__name__)


STATUSES = ["todo", "in_progress", "rooted", "skipped"]


@dataclass
class ProofState:
    user_flag: str = ""
    proof_flag: str = ""
    screenshots: List[str] = field(default_factory=list)
    checklist: Dict[str, bool] = field(default_factory=lambda: {
        "screenshot_proof_txt": False,
        "ifconfig_visible": False,
        "whoami_visible": False,
    })

    def is_complete(self) -> bool:
        return bool(self.proof_flag) and all(self.checklist.values())


@dataclass
class Machine:
    id: str
    ip: str = ""
    hostname: str = ""
    os: str = ""
    status: str = "todo"
    difficulty: str = ""
    notes_path: str = ""
    points: int = 0
    ports: List[int] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    proof: ProofState = field(default_factory=ProofState)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Machine":
        # On copie pour ne PAS muter le dict de l'appelant
        d = dict(d)
        proof = d.pop("proof", None)
        m = cls(**d)
        if proof:
            m.proof = ProofState(**proof)
        return m


@dataclass
class Subnet:
    cidr: str
    label: str = ""
    pivot_via: Optional[str] = None      # machine id
    machines: List[str] = field(default_factory=list)  # machine ids

    def contains_ip(self, ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip) in ipaddress.ip_network(self.cidr, strict=False)
        except ValueError:
            return False


@dataclass
class Pivot:
    from_machine: str
    to_cidr: str
    tool: str = "ligolo"
    port: int = 0
    active: bool = False


class ScopeManager(QObject):
    machines_changed = pyqtSignal()
    subnets_changed = pyqtSignal()
    pivots_changed = pyqtSignal()
    machine_status_changed = pyqtSignal(str, str)   # machine_id, new_status

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self._cm = config_manager
        self._subnets: List[Subnet] = []
        self._machines: Dict[str, Machine] = {}
        self._pivots: List[Pivot] = []
        self._load()

    # ----------------------------------------------------------

    def _load(self) -> None:
        data = self._cm.load("scope")
        # Subnet et Pivot wrappes pour resilience : un champ inconnu ou
        # manquant dans un vieux scope.json ne casse plus l'app entiere.
        self._subnets = []
        for s in data.get("subnets", []):
            try:
                self._subnets.append(Subnet(**s))
            except TypeError as exc:
                log.warning("Skip bad subnet %s: %s", s, exc)
        for item in data.get("machines", []):
            try:
                m = Machine.from_dict(item)
            except TypeError as exc:
                log.warning("Skip bad machine %s: %s", item, exc)
                continue
            self._machines[m.id] = m
        self._pivots = []
        for p in data.get("pivots", []):
            try:
                self._pivots.append(Pivot(**p))
            except TypeError as exc:
                log.warning("Skip bad pivot %s: %s", p, exc)
        log.info(
            "Scope loaded: %d subnets, %d machines, %d pivots",
            len(self._subnets), len(self._machines), len(self._pivots),
        )

    def _save(self) -> None:
        self._cm.save("scope", {
            "subnets": [asdict(s) for s in self._subnets],
            "machines": [m.to_dict() for m in self._machines.values()],
            "pivots": [asdict(p) for p in self._pivots],
        })

    # ---------- subnets ----------

    def subnets(self) -> List[Subnet]:
        return list(self._subnets)

    def add_subnet(self, cidr: str, label: str = "", pivot_via: Optional[str] = None) -> Subnet:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid CIDR '{cidr}': {exc}")
        if any(s.cidr == cidr for s in self._subnets):
            raise ValueError(f"Subnet {cidr} already exists")
        s = Subnet(cidr=cidr, label=label, pivot_via=pivot_via)
        self._subnets.append(s)
        # Attacher les machines dont l'IP tombe dedans
        for m in self._machines.values():
            if m.ip and s.contains_ip(m.ip) and m.id not in s.machines:
                s.machines.append(m.id)
        self._save()
        self.subnets_changed.emit()
        return s

    def remove_subnet(self, cidr: str) -> None:
        self._subnets = [s for s in self._subnets if s.cidr != cidr]
        self._save()
        self.subnets_changed.emit()

    def subnet_for_ip(self, ip: str) -> Optional[Subnet]:
        for s in self._subnets:
            if s.contains_ip(ip):
                return s
        return None

    # ---------- machines ----------

    def machines(self) -> List[Machine]:
        return sorted(self._machines.values(), key=lambda m: (m.status, m.hostname or m.ip))

    def machine(self, mid: str) -> Optional[Machine]:
        return self._machines.get(mid)

    def by_status(self, status: str) -> List[Machine]:
        return [m for m in self._machines.values() if m.status == status]

    def add_machine(
        self,
        ip: str = "",
        hostname: str = "",
        os: str = "",
        status: str = "todo",
        difficulty: str = "",
        points: int = 0,
    ) -> Machine:
        if status not in STATUSES:
            raise ValueError(f"Invalid status '{status}'")
        # Warn si une machine avec la meme IP existe deja : on accepte
        # quand meme (cas legitime : meme IP sur reseaux differents apres
        # pivot) mais on l'enregistre dans les logs car ca peut etre
        # une erreur utilisateur (clic ajouter par accident 2 fois).
        if ip:
            existing = [m for m in self._machines.values() if m.ip == ip]
            if existing:
                log.warning(
                    "Machine with IP %s already exists (%d entries) -- "
                    "creating duplicate. If unintended, remove old entry.",
                    ip, len(existing),
                )
        mid = f"m_{uuid.uuid4().hex[:8]}"
        m = Machine(
            id=mid, ip=ip, hostname=hostname, os=os,
            status=status, difficulty=difficulty, points=points,
        )
        self._machines[mid] = m
        # Rattachement au bon subnet
        if ip:
            sub = self.subnet_for_ip(ip)
            if sub and mid not in sub.machines:
                sub.machines.append(mid)
        self._save()
        self.machines_changed.emit()
        return m

    def remove_machine(self, mid: str) -> None:
        if mid not in self._machines:
            return
        del self._machines[mid]
        for s in self._subnets:
            if mid in s.machines:
                s.machines.remove(mid)
        self._pivots = [p for p in self._pivots if p.from_machine != mid]
        self._save()
        self.machines_changed.emit()

    def update_machine(self, m: Machine) -> None:
        self._machines[m.id] = m
        self._save()
        self.machines_changed.emit()

    def set_status(self, mid: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"Invalid status '{status}'")
        m = self._machines.get(mid)
        if m is None:
            return
        if m.status == status:
            return
        m.status = status
        self._save()
        self.machine_status_changed.emit(mid, status)
        self.machines_changed.emit()

    # ---------- pivots ----------

    def pivots(self) -> List[Pivot]:
        return list(self._pivots)

    def add_pivot(self, from_machine: str, to_cidr: str, tool: str = "ligolo", port: int = 0) -> Pivot:
        p = Pivot(from_machine=from_machine, to_cidr=to_cidr, tool=tool, port=port)
        self._pivots.append(p)
        self._save()
        self.pivots_changed.emit()
        return p

    def remove_pivot(self, from_machine: str, to_cidr: str) -> None:
        self._pivots = [
            p for p in self._pivots
            if not (p.from_machine == from_machine and p.to_cidr == to_cidr)
        ]
        self._save()
        self.pivots_changed.emit()

    def set_pivot_active(self, from_machine: str, to_cidr: str, active: bool) -> None:
        for p in self._pivots:
            if p.from_machine == from_machine and p.to_cidr == to_cidr:
                p.active = active
                self._save()
                self.pivots_changed.emit()
                return

    # ---------- utils ----------

    def tree_text(self) -> str:
        """Représentation texte ASCII du scope (pour affichage simple)."""
        lines = ["Scope:"]
        for s in self._subnets:
            suffix = ""
            if s.label:
                suffix = f" ({s.label})"
            if s.pivot_via:
                pv = self._machines.get(s.pivot_via)
                via = pv.hostname or pv.ip if pv else s.pivot_via
                suffix += f" via {via}"
            lines.append(f"+-- {s.cidr}{suffix}")
            ms = [self._machines[m] for m in s.machines if m in self._machines]
            for m in ms:
                icon = {
                    "rooted": "[OK]",
                    "in_progress": "[?]",
                    "todo": "[ ]",
                    "skipped": "*",
                }.get(m.status, "[ ]")
                host = m.hostname or "?"
                os_ = f" ({m.os})" if m.os else ""
                lines.append(f"|   +-- {m.ip} - {host}{os_} {icon}")
        return "\n".join(lines)
