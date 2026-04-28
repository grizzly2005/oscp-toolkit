"""Network info — détection IP attaquante + VPN status.

Parse `ip addr` (preferé sur Linux) avec fallback `ifconfig` puis
fallback `socket` pour deviner l'IP. Expose un signal `refreshed` pour
la status bar. Refresh automatique toutes les 30 secondes.
"""

from __future__ import annotations

import re
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from .logger import get_logger

log = get_logger(__name__)


@dataclass
class Interface:
    name: str
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None
    up: bool = False
    kind: str = "other"   # tun / eth / wlan / lo / other


@dataclass
class NetworkSnapshot:
    interfaces: Dict[str, Interface] = field(default_factory=dict)
    detected_at: float = field(default_factory=time.time)
    vpn_connected: bool = False

    def attacker_ip(self) -> Optional[str]:
        """Meilleure IP attaquante : priorité tun* > eth* > wlan*."""
        for priority in ("tun", "eth", "enp", "wlp", "wlan"):
            for iface in self.interfaces.values():
                if iface.up and iface.ipv4 and iface.kind == priority:
                    return iface.ipv4
                # Fallback : la kind peut ne pas être parfaitement catégorisée
                if iface.up and iface.ipv4 and iface.name.startswith(priority):
                    return iface.ipv4
        # Sinon la première non-loopback
        for iface in self.interfaces.values():
            if iface.up and iface.ipv4 and iface.kind != "lo":
                return iface.ipv4
        return None

    def iface_by_name(self, name: str) -> Optional[Interface]:
        return self.interfaces.get(name)


class NetworkInfo(QObject):
    """Service d'information réseau avec auto-refresh."""

    refreshed = pyqtSignal(object)  # NetworkSnapshot
    vpn_state_changed = pyqtSignal(bool)

    def __init__(self, interval_ms: int = 30_000, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._snapshot = NetworkSnapshot()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.refresh)
        self._manual_override_ip: Optional[str] = None

    def start(self) -> None:
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def snapshot(self) -> NetworkSnapshot:
        return self._snapshot

    def set_manual_ip(self, ip: Optional[str]) -> None:
        """Force une IP attaquante (fallback si rien détecté)."""
        self._manual_override_ip = ip or None
        log.info("Manual attacker IP set to %s", ip)
        self.refreshed.emit(self._snapshot)

    def attacker_ip(self) -> Optional[str]:
        if self._manual_override_ip:
            return self._manual_override_ip
        return self._snapshot.attacker_ip()

    def refresh(self) -> NetworkSnapshot:
        prev_vpn = self._snapshot.vpn_connected
        ifaces = self._parse_ip_addr()
        if not ifaces:
            ifaces = self._parse_ifconfig()
        if not ifaces:
            ifaces = self._fallback_socket()

        snap = NetworkSnapshot(interfaces=ifaces)
        snap.vpn_connected = any(
            i.up and (i.name.startswith("tun") or i.name.startswith("wg"))
            for i in ifaces.values()
        )
        self._snapshot = snap

        if snap.vpn_connected != prev_vpn:
            self.vpn_state_changed.emit(snap.vpn_connected)

        self.refreshed.emit(snap)
        return snap

    # ----------------------------------------------------------

    def _parse_ip_addr(self) -> Dict[str, Interface]:
        try:
            res = subprocess.run(
                ["ip", "-o", "addr", "show"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {}
        if res.returncode != 0:
            return {}

        ifaces: Dict[str, Interface] = {}
        # format :
        #   2: eth0    inet 192.168.1.50/24 brd ... scope global dynamic eth0 ...
        #   3: tun0    inet 10.10.14.5/24 scope global tun0 ...
        pattern = re.compile(
            r"^\d+:\s+(?P<name>\S+)\s+(?P<fam>inet6?)\s+(?P<addr>[0-9a-fA-F:.]+)/\d+"
        )
        # Et pour le flag UP on doit relire `ip -o link show`
        link_state = self._get_link_state()

        for line in res.stdout.splitlines():
            m = pattern.match(line)
            if not m:
                continue
            name = m.group(1)
            fam = m.group(2)
            addr = m.group(3)
            if name == "lo":
                # on trace mais on skippe pour l'attacker_ip
                kind = "lo"
            elif name.startswith("tun"):
                kind = "tun"
            elif name.startswith("wg"):
                kind = "tun"
            elif name.startswith(("eth", "enp")):
                kind = "eth"
            elif name.startswith(("wlan", "wlp")):
                kind = "wlan"
            elif name.startswith("docker") or name.startswith("br-"):
                kind = "docker"
            else:
                kind = "other"

            iface = ifaces.get(name)
            if iface is None:
                iface = Interface(name=name, kind=kind, up=link_state.get(name, False))
                ifaces[name] = iface
            if fam == "inet":
                iface.ipv4 = addr
            else:
                iface.ipv6 = addr
        return ifaces

    def _get_link_state(self) -> Dict[str, bool]:
        try:
            res = subprocess.run(
                ["ip", "-o", "link", "show"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {}
        state: Dict[str, bool] = {}
        for line in res.stdout.splitlines():
            # "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> ..."
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            name = parts[1].strip().split("@")[0]
            rest = parts[2]
            state[name] = "UP" in rest and "LOWER_UP" in rest
        return state

    def _parse_ifconfig(self) -> Dict[str, Interface]:
        try:
            res = subprocess.run(
                ["ifconfig"], capture_output=True, text=True, timeout=3
            )
        except (OSError, subprocess.TimeoutExpired):
            return {}
        if res.returncode != 0:
            return {}
        ifaces: Dict[str, Interface] = {}
        current: Optional[Interface] = None
        for line in res.stdout.splitlines():
            if line and not line.startswith((" ", "\t")):
                # début d'un bloc : "eth0: flags=..."
                header = line.split(":", 1)[0].strip()
                up = "UP" in line
                kind = "other"
                if header.startswith("tun") or header.startswith("wg"):
                    kind = "tun"
                elif header.startswith(("eth", "enp")):
                    kind = "eth"
                elif header == "lo":
                    kind = "lo"
                current = Interface(name=header, up=up, kind=kind)
                ifaces[header] = current
            else:
                if current is None:
                    continue
                m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    current.ipv4 = m.group(1)
                m6 = re.search(r"inet6\s+([0-9a-fA-F:]+)", line)
                if m6:
                    current.ipv6 = m6.group(1)
        return ifaces

    def _fallback_socket(self) -> Dict[str, Interface]:
        """Dernier recours : socket.gethostbyname_ex + connect udp dummy."""
        ifaces: Dict[str, Interface] = {}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # Pas de vrai traffic, juste pour que l'OS choisisse une route
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                ifaces["auto"] = Interface(name="auto", ipv4=ip, up=True, kind="eth")
        except OSError:
            pass
        return ifaces