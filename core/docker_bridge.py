"""Docker Bridge — BloodHound CE via docker-compose.

On ne GERE PAS BloodHound lui-même (UI, Neo4j, etc.) — on pilote un
stack docker-compose déjà fourni par l'utilisateur (ou on écrit un
docker-compose par défaut). Status via `docker compose ps` ou
`docker ps`. Ingestion : upload des JSON SharpHound dans le dossier
`ingest` partagé (ou affichage du chemin pour que l'user drag-drop
dans BH UI).

Tout est optionnel : si Docker absent ou stack introuvable, le panneau
BH est désactivé. On retourne des erreurs claires pour l'UI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger

log = get_logger(__name__)


_DEFAULT_COMPOSE_DIR = Path("data/bloodhound")
_DEFAULT_COMPOSE_FILE = _DEFAULT_COMPOSE_DIR / "docker-compose.yml"

# Template compose minimal — l'utilisateur peut l'adapter
_DEFAULT_COMPOSE_CONTENT = """\
# Minimal BloodHound CE stack.
# Documentation officielle : https://bloodhound.specterops.io/
services:
  bh-postgres:
    image: docker.io/library/postgres:13.2
    environment:
      POSTGRES_USER: bloodhound
      POSTGRES_PASSWORD: bloodhoundcommunityedition
      POSTGRES_DB: bloodhound
    volumes:
      - bh-pg:/var/lib/postgresql/data
  bh-neo4j:
    image: docker.io/library/neo4j:4.4
    environment:
      NEO4J_AUTH: neo4j/bloodhoundcommunityedition
    ports:
      - "127.0.0.1:7474:7474"
      - "127.0.0.1:7687:7687"
    volumes:
      - bh-neo4j:/data
  bloodhound:
    image: docker.io/specterops/bloodhound:latest
    depends_on:
      - bh-postgres
      - bh-neo4j
    environment:
      bhe_database_connection: "user=bloodhound password=bloodhoundcommunityedition dbname=bloodhound host=bh-postgres"
      bhe_neo4j_connection: "neo4j://neo4j:bloodhoundcommunityedition@bh-neo4j:7687"
    ports:
      - "127.0.0.1:8080:8080"
volumes:
  bh-pg:
  bh-neo4j:
"""


@dataclass
class DockerStatus:
    docker_installed: bool
    daemon_running: bool
    compose_available: bool
    stack_up: bool
    services: List[str]
    error: Optional[str] = None


class DockerBridge(QObject):
    status_changed = pyqtSignal(object)       # DockerStatus

    def __init__(
        self,
        compose_dir: Path | str = _DEFAULT_COMPOSE_DIR,
        parent=None,
    ):
        super().__init__(parent)
        self.compose_dir = Path(compose_dir)
        self.compose_file = self.compose_dir / "docker-compose.yml"

    # ----------------------------------------------------------

    def ensure_compose_file(self) -> Path:
        """Crée un docker-compose.yml par défaut si absent."""
        self.compose_dir.mkdir(parents=True, exist_ok=True)
        if not self.compose_file.exists():
            self.compose_file.write_text(_DEFAULT_COMPOSE_CONTENT, encoding="utf-8")
            log.info("Created default BloodHound compose file at %s", self.compose_file)
        return self.compose_file

    def status(self) -> DockerStatus:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            st = DockerStatus(
                docker_installed=False, daemon_running=False,
                compose_available=False, stack_up=False, services=[],
                error="docker CLI absent du PATH",
            )
            self.status_changed.emit(st)
            return st

        try:
            info = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            st = DockerStatus(
                docker_installed=True, daemon_running=False,
                compose_available=False, stack_up=False, services=[],
                error=str(exc),
            )
            self.status_changed.emit(st)
            return st
        daemon = info.returncode == 0

        # Compose v2 (docker compose) ou v1 (docker-compose)
        compose_ok = self._compose_cmd() is not None

        services: List[str] = []
        stack_up = False
        if daemon and compose_ok and self.compose_file.exists():
            ps = self._run_compose(["ps", "--format", "json"], check=False)
            if ps is not None and ps.returncode == 0:
                # `docker compose ps --format json` retourne une ligne par service.
                # On compte ceux qui sont "running".
                for line in ps.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # Parsing tolérant sans json
                    if '"Service":' in line or '"Name":' in line:
                        import json as _j
                        try:
                            obj = _j.loads(line)
                        except Exception:
                            continue
                        name = obj.get("Service") or obj.get("Name", "?")
                        state = obj.get("State", "").lower()
                        services.append(f"{name}:{state}")
                        if state == "running":
                            stack_up = True

        st = DockerStatus(
            docker_installed=True,
            daemon_running=daemon,
            compose_available=compose_ok,
            stack_up=stack_up,
            services=services,
        )
        self.status_changed.emit(st)
        return st

    def start_stack(self) -> bool:
        self.ensure_compose_file()
        res = self._run_compose(["up", "-d"])
        ok = res is not None and res.returncode == 0
        log.info("BloodHound stack up: %s", ok)
        self.status()
        return ok

    def stop_stack(self) -> bool:
        res = self._run_compose(["down"])
        ok = res is not None and res.returncode == 0
        log.info("BloodHound stack down: %s", ok)
        self.status()
        return ok

    def ingest_dir(self) -> Path:
        """Dossier où déposer les JSON SharpHound.

        L'utilisateur peut ensuite drag-drop dans BH UI (http://localhost:8080).
        """
        d = self.compose_dir / "ingest"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def copy_ingest(self, sources: List[Path]) -> List[Path]:
        """Copie des JSON dans le dossier ingest."""
        dest = self.ingest_dir()
        copied = []
        for src in sources:
            src = Path(src)
            if not src.exists():
                continue
            try:
                target = dest / src.name
                shutil.copy2(src, target)
                copied.append(target)
            except OSError as exc:
                log.warning("Copy %s failed: %s", src, exc)
        return copied

    # ----------------------------------------------------------

    def _compose_cmd(self) -> Optional[List[str]]:
        # Docker Compose v2 = `docker compose ...`
        if shutil.which("docker"):
            try:
                r = subprocess.run(
                    ["docker", "compose", "version"],
                    capture_output=True, text=True, timeout=3,
                )
                if r.returncode == 0:
                    return ["docker", "compose"]
            except (OSError, subprocess.TimeoutExpired):
                pass
        # Compose v1
        if shutil.which("docker-compose"):
            return ["docker-compose"]
        return None

    def _run_compose(self, args: List[str], check: bool = True) -> Optional[subprocess.CompletedProcess]:
        base = self._compose_cmd()
        if base is None:
            return None
        if not self.compose_file.exists():
            log.warning("Compose file not found: %s", self.compose_file)
            return None
        cmd = list(base) + ["-f", str(self.compose_file)] + list(args)
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
            )
            if check and res.returncode != 0:
                log.warning("Compose cmd failed: %s\n%s", cmd, res.stderr.strip())
            return res
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("Compose cmd error: %s", exc)
            return None
