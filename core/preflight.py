"""Pre-flight checks.

Exécuté avant d'afficher la fenêtre principale. Deux classes de checks :

- Bloquants : si ça échoue, on n'ouvre pas l'app.
  (Python, PyQt5, display, dossiers writables, configs chargeables)

- Non-bloquants : on continue, mais on warn l'utilisateur.
  (outils absents, Docker absent, VPN déconnecté, orphelins, session)

Le dialog de pre-flight (voir ui/preflight_dialog.py) consomme la liste
de résultats retournée par `run_preflight()`.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config_manager import ConfigManager, ConfigError
from .logger import get_logger
from .process_tracker import ProcessTracker, TrackedProcess

log = get_logger(__name__)


@dataclass
class CheckResult:
    name: str
    passed: bool
    blocking: bool
    message: str = ""
    details: str = ""
    # Pour affichage : suggestion d'action pour l'utilisateur
    suggestion: str = ""
    # Données structurées pour traitement dans la dialog (orphelins, etc.)
    payload: dict = field(default_factory=dict)


@dataclass
class PreflightReport:
    results: List[CheckResult] = field(default_factory=list)

    @property
    def has_blocking_failure(self) -> bool:
        return any(not r.passed and r.blocking for r in self.results)

    @property
    def warnings(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed and not r.blocking]

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)


# --------------------------------------------------------------
# Checks individuels
# --------------------------------------------------------------

def _check_python_version() -> CheckResult:
    ok = sys.version_info >= (3, 8)
    return CheckResult(
        name="Python 3.8+",
        passed=ok,
        blocking=True,
        message=(
            f"Python {sys.version_info.major}.{sys.version_info.minor} détecté"
            if ok
            else f"Python trop ancien (actuel : {sys.version.split()[0]})"
        ),
        suggestion="" if ok else "Installez Python 3.8 ou plus récent.",
    )


def _check_pyqt5() -> CheckResult:
    try:
        importlib.import_module("PyQt5.QtWidgets")
        from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR  # type: ignore
        return CheckResult(
            name="PyQt5",
            passed=True,
            blocking=True,
            message=f"PyQt5 {PYQT_VERSION_STR} / Qt {QT_VERSION_STR}",
        )
    except ImportError as exc:
        return CheckResult(
            name="PyQt5",
            passed=False,
            blocking=True,
            message="PyQt5 non installé",
            details=str(exc),
            suggestion="pip install PyQt5",
        )


def _check_display() -> CheckResult:
    # On cherche X11 ou Wayland. WSLg fournit $DISPLAY automatiquement.
    display = os.environ.get("DISPLAY")
    wayland = os.environ.get("WAYLAND_DISPLAY")
    if display or wayland:
        label = f"DISPLAY={display}" if display else f"WAYLAND_DISPLAY={wayland}"
        return CheckResult(
            name="Display (X11/Wayland)",
            passed=True,
            blocking=True,
            message=label,
        )
    # WSL : certains setups n'exportent pas DISPLAY mais ont quand même Qt OK.
    # On laisse quand même bloquant, mais avec message explicite.
    return CheckResult(
        name="Display (X11/Wayland)",
        passed=False,
        blocking=True,
        message="Ni $DISPLAY ni $WAYLAND_DISPLAY",
        suggestion=(
            "Sur WSL : installer WSLg ou exporter DISPLAY=:0 "
            "avec un X server (VcXsrv, X410, wslg). "
            "Sur Linux natif : vérifier que la session graphique est active."
        ),
    )


def _check_writable(path: Path, label: str) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult(
            name=f"Dossier {label}",
            passed=False,
            blocking=True,
            message=f"Impossible de créer {path}: {exc}",
            suggestion=f"Vérifier les permissions sur {path.parent}",
        )
    probe = path / ".write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return CheckResult(
            name=f"Dossier {label}",
            passed=False,
            blocking=True,
            message=f"{path} non-writable: {exc}",
            suggestion=f"chmod u+w {path}",
        )
    return CheckResult(
        name=f"Dossier {label}",
        passed=True,
        blocking=True,
        message=f"{path} accessible en écriture",
    )


def _check_config_loadable(cm: ConfigManager) -> CheckResult:
    """Tente de charger toutes les configs critiques."""
    critical = [
        "tools", "links", "workspaces", "shortcuts",
        "layout", "scope", "credentials", "clipboard_pins",
        "wordlists", "revshells",
    ]
    failed = []
    recovered = []
    for name in critical:
        try:
            path = cm.config_dir / f"{name}.json"
            was_missing = not path.exists()
            cm.load(name)
            if was_missing:
                recovered.append(name)
        except ConfigError as exc:
            failed.append((name, str(exc)))
    if failed:
        return CheckResult(
            name="Configs JSON",
            passed=False,
            blocking=True,
            message=f"{len(failed)} config(s) non chargeable(s)",
            details="\n".join(f"- {n}: {e}" for n, e in failed),
            suggestion="Vérifier le dossier config/defaults/",
        )
    msg = "Toutes les configs chargées"
    if recovered:
        msg += f" ({len(recovered)} restaurée(s) depuis defaults)"
    return CheckResult(
        name="Configs JSON",
        passed=True,
        blocking=True,
        message=msg,
        details=(
            "Restaurées: " + ", ".join(recovered) if recovered else ""
        ),
    )


def _check_tools_presence(cm: ConfigManager) -> CheckResult:
    try:
        data = cm.load("tools")
    except ConfigError:
        return CheckResult(
            name="Outils disponibles",
            passed=False,
            blocking=False,
            message="Impossible de charger la liste des outils",
        )
    missing = []
    present = 0
    tools = data.get("tools", [])
    for t in tools:
        path = t.get("path", "")
        name = t.get("name", "?")
        if not path:
            # path vide = outil à transférer sur cible (linpeas, winpeas...)
            continue
        if Path(path).exists() or shutil.which(path):
            present += 1
        else:
            missing.append(name)
    if missing:
        return CheckResult(
            name="Outils disponibles",
            passed=False,
            blocking=False,
            message=f"{present}/{len(tools) - sum(1 for t in tools if not t.get('path'))} outils présents",
            details="Manquants : " + ", ".join(missing[:20])
                    + (" ..." if len(missing) > 20 else ""),
            suggestion="Marqués [KO] dans le panneau. Installer si besoin.",
            payload={"missing": missing, "present": present},
        )
    return CheckResult(
        name="Outils disponibles",
        passed=True,
        blocking=False,
        message=f"{present} outils détectés",
    )


def _check_docker() -> CheckResult:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return CheckResult(
            name="Docker",
            passed=False,
            blocking=False,
            message="docker CLI absent",
            suggestion="BloodHound Bridge sera désactivé. Installer Docker si besoin.",
        )
    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return CheckResult(
                name="Docker",
                passed=True,
                blocking=False,
                message="Docker daemon actif",
            )
        return CheckResult(
            name="Docker",
            passed=False,
            blocking=False,
            message="Docker installé mais daemon non démarré",
            suggestion="Lancer Docker Desktop ou `sudo systemctl start docker`.",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="Docker",
            passed=False,
            blocking=False,
            message="Docker timeout (daemon probablement KO)",
            suggestion="Vérifier l'état du daemon Docker.",
        )
    except OSError as exc:
        return CheckResult(
            name="Docker",
            passed=False,
            blocking=False,
            message=f"Erreur Docker: {exc}",
        )


def _check_vpn() -> CheckResult:
    """Simple détection d'une interface tun*."""
    try:
        res = subprocess.run(
            ["ip", "-o", "link", "show"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CheckResult(
            name="VPN / tun0",
            passed=False,
            blocking=False,
            message="Commande `ip` indisponible",
            suggestion="Éditer l'IP manuellement dans la status bar.",
        )
    found = []
    for line in res.stdout.splitlines():
        # ex: "5: tun0: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> ..."
        parts = line.split(":", 2)
        if len(parts) >= 2:
            iface = parts[1].strip().split("@")[0]
            if iface.startswith("tun") or iface.startswith("wg"):
                found.append(iface)
    if found:
        return CheckResult(
            name="VPN / tun0",
            passed=True,
            blocking=False,
            message=f"Interface(s) VPN détectée(s) : {', '.join(found)}",
        )
    return CheckResult(
        name="VPN / tun0",
        passed=False,
        blocking=False,
        message="Aucune interface tun*/wg*",
        suggestion="Connecter le VPN OSCP avant de commencer.",
    )


def _check_orphans(pt: ProcessTracker) -> CheckResult:
    orphans: List[TrackedProcess] = pt.check_orphans()
    if not orphans:
        return CheckResult(
            name="Process orphelins",
            passed=True,
            blocking=False,
            message="Aucun orphelin détecté",
        )
    return CheckResult(
        name="Process orphelins",
        passed=False,
        blocking=False,
        message=f"{len(orphans)} process orphelin(s) de la session précédente",
        details="\n".join(
            f"- PID {o.pid} ({o.category} / {o.name})"
            for o in orphans[:10]
        ),
        suggestion="Proposition de kill au démarrage.",
        payload={"orphans": [o.pid for o in orphans]},
    )


def _check_previous_session() -> CheckResult:
    session_file = Path("data/sessions/last_session.json")
    if session_file.exists() and session_file.stat().st_size > 0:
        return CheckResult(
            name="Session précédente",
            passed=True,
            blocking=False,
            message="Session précédente trouvée (proposition de restore)",
            payload={"session_file": str(session_file)},
        )
    return CheckResult(
        name="Session précédente",
        passed=True,
        blocking=False,
        message="Pas de session précédente",
    )


# --------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------

def run_preflight(
    config_manager: ConfigManager,
    process_tracker: ProcessTracker,
    skip_optional: bool = False,
) -> PreflightReport:
    """Exécute tous les checks et retourne un rapport."""
    report = PreflightReport()
    # Bloquants
    report.results.append(_check_python_version())
    report.results.append(_check_pyqt5())
    report.results.append(_check_display())
    report.results.append(_check_writable(config_manager.config_dir, "config/"))
    report.results.append(_check_writable(Path("data"), "data/"))
    report.results.append(_check_writable(Path("logs"), "logs/"))
    report.results.append(_check_config_loadable(config_manager))

    if not skip_optional:
        # Non-bloquants
        report.results.append(_check_tools_presence(config_manager))
        report.results.append(_check_docker())
        report.results.append(_check_vpn())
        report.results.append(_check_orphans(process_tracker))
        report.results.append(_check_previous_session())

    for r in report.results:
        log.info(
            "[preflight] %-25s : %s%s",
            r.name,
            "OK" if r.passed else ("FAIL*" if r.blocking else "WARN "),
" - " + r.message if r.message else "",
        )

    return report
