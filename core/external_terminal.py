"""External Terminal Launcher — lance un vrai terminal OS avec env OSCP.

Priorite :
  1. Windows Terminal (wt.exe) via /mnt/c/... -> rendu parfait, WSL natif
  2. xterm (si X11/Wayland dispo et wt introuvable)
  3. Fallback : message d'erreur (jamais d'echec silencieux)

Le terminal est lance DETACHE du process toolkit : si le toolkit plante,
les terminaux continuent. Si l'utilisateur ferme un terminal, le toolkit
n'est pas impacte.

Integrations futures prevues (placeholders deja la) :
  - Push de commande depuis le toolkit vers un terminal actif (via tmux)
  - Recuperation de l'output (via tmux capture-pane)
  - Clipboard sync (deja gere nativement par WSLg/xterm via X11)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .env_manager import EnvManager
from .logger import get_logger

log = get_logger(__name__)


# Localise wt.exe (Windows Terminal) en parcourant les chemins standards
# WSL -> Windows. On ne hardcode JAMAIS un username : on construit a partir
# de l'environnement (USERPROFILE -> WSL path, ou /mnt/c/Users/<user>)
# avec plusieurs fallbacks si l'un des paths ne marche pas.
_WT_PATTERNS_RELATIVE = [
    "AppData/Local/Microsoft/WindowsApps/wt.exe",
]

# Pour debugger / tester, on peut aussi forcer un path via OSCP_WT_PATH=
# dans l'env (utile si wt.exe est installe ailleurs).


class LaunchError(Exception):
    """Raise quand aucun terminal n'a pu etre lance."""
    pass


class ExternalTerminal(QObject):
    """Lance des terminaux externes avec session OSCP pre-configuree."""

    launched = pyqtSignal(str)      # title
    failed   = pyqtSignal(str)      # reason

    def __init__(self, env_manager: EnvManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._env = env_manager

    # -- Detection -----------------------------------------------------------

    @staticmethod
    def _find_wt() -> Optional[str]:
        """Localise wt.exe (Windows Terminal) — None si non trouve.

        Strategie de recherche, dans l'ordre :
          1. OSCP_WT_PATH env var (override manuel)
          2. PATH (shutil.which "wt.exe")
          3. /mnt/c/Users/<user>/AppData/... pour chaque user dans /mnt/c/Users
          4. /mnt/c/Program Files/WindowsApps/Microsoft.WindowsTerminal_*/wt.exe
          5. None
        """
        import glob
        # 1. Override env
        forced = os.environ.get("OSCP_WT_PATH")
        if forced and os.path.exists(forced):
            return forced
        # 2. PATH
        found = shutil.which("wt.exe")
        if found:
            return found
        # 3. Per-user WindowsApps. On parcourt /mnt/c/Users/<*> au lieu de
        # hardcoder un username : marche pour n importe quel utilisateur, pour qui
        # que ce soit qui clone le projet.
        users_root = "/mnt/c/Users"
        if os.path.isdir(users_root):
            for user_dir in os.listdir(users_root):
                # Skip Public, Default, etc. — ces profils n'ont pas de WindowsApps
                if user_dir in ("Public", "Default", "Default User", "All Users"):
                    continue
                for rel in _WT_PATTERNS_RELATIVE:
                    candidate = os.path.join(users_root, user_dir, rel)
                    if os.path.exists(candidate):
                        return candidate
        # 4. WindowsApps system-wide (glob avec wildcard version)
        for pat in [
            "/mnt/c/Program Files/WindowsApps/Microsoft.WindowsTerminal_*/wt.exe",
        ]:
            matches = glob.glob(pat)
            if matches:
                return matches[0]
        return None

    @staticmethod
    def _find_xterm() -> Optional[str]:
        for name in ("xterm", "gnome-terminal", "konsole", "xfce4-terminal"):
            p = shutil.which(name)
            if p:
                return p
        return None

    def available_backends(self) -> List[str]:
        """Liste les backends disponibles sur ce systeme."""
        available: List[str] = []
        if self._find_wt():
            available.append("wt")
        if self._find_xterm():
            available.append("xterm")
        return available

    # -- Launch --------------------------------------------------------------

    def launch(
        self,
        title: str = "OSCP",
        cwd: Optional[str] = None,
        backend: str = "auto",
        initial_command: Optional[str] = None,
    ) -> None:
        """Lance un terminal externe.

        Args:
          title: titre de la fenetre/onglet
          cwd: repertoire initial (defaut : $PENTEST_DIR)
          backend: "wt", "xterm", ou "auto" pour detection
          initial_command: commande a executer apres l'init (ex: "nmap -A $TARGET")
        """
        # Genere le script de session (vars + aliases + PS1)
        extra = {}
        if title:
            extra["OSCP_SESSION"] = title
        script = self._env.write_session_script(extra_exports=extra)

        # Cleanup periodique des vieux scripts
        self._env.cleanup_old_scripts(keep_recent=10)

        if cwd is None:
            cwd = self._env.get("PENTEST_DIR") or os.path.expanduser("~")

        if backend == "auto":
            backend = "wt" if self._find_wt() else "xterm"

        try:
            if backend == "wt":
                self._launch_wt(title, cwd, script, initial_command)
            elif backend == "xterm":
                self._launch_xterm(title, cwd, script, initial_command)
            else:
                raise LaunchError(f"Backend inconnu : {backend}")
            self.launched.emit(title)
        except LaunchError as exc:
            log.error("Terminal launch failed: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:
            log.exception("Unexpected error launching terminal")
            self.failed.emit(f"Erreur inattendue : {exc}")

    # -- Backends ------------------------------------------------------------

    def _launch_wt(
        self,
        title: str,
        cwd: str,
        script: Path,
        initial_command: Optional[str],
    ) -> None:
        """Lance Windows Terminal avec WSL.

        Probleme historique : wt.exe parse les ';' et caracteres speciaux dans
        les arguments, ce qui casse une commande bash inline du genre
        "source X; exec bash" -> wt voit "; exec bash" comme une nouvelle
        commande -> erreur 0x80070002.

        Solution : on AJOUTE l'initial_command au script de session (qui est
        deja un fichier .sh sur disque), puis bash --rcfile=script. Plus de
        bash -c avec quoting fragile.
        """
        wt = self._find_wt()
        if not wt:
            raise LaunchError("wt.exe introuvable")

        # Si initial_command, on l'embed dans le script (avant le exec final)
        if initial_command:
            try:
                with open(script, "a", encoding="utf-8") as fp:
                    fp.write("\n# Commande initiale auto-injectee\n")
                    fp.write(f"{initial_command}\n")
            except OSError as exc:
                log.warning("Cannot append initial_command to %s: %s", script, exc)

        distro = os.environ.get("WSL_DISTRO_NAME", "")

        # bash --rcfile=script va sourcer le script puis lancer un shell
        # interactif. Pas de bash -c, pas de quoting bizarre.
        # --rcfile prend un chemin Linux : on convertit le script Path
        # depuis le mount /tmp en chemin direct utilisable par WSL bash.
        rc_arg = str(script)

        wsl_args = []
        if distro:
            wsl_args = ["wsl.exe", "-d", distro]
        else:
            wsl_args = ["wsl.exe"]

        # --cd accepte un chemin Linux quand on appelle wsl.exe depuis Windows
        if cwd:
            wsl_args += ["--cd", cwd]

        # bash interactif avec --rcfile
        wsl_args += ["--", "bash", "--rcfile", rc_arg, "-i"]

        # Construction de la commande wt.exe
        # Format : wt.exe -w 0 new-tab --title "X" -- <wsl_args>
        # Note : on utilise "new-tab" (pas "nt") en clair, et un "--" pour
        # separer les options de wt des arguments du sous-process.
        cmd = [
            wt,
            "-w", "0",
            "new-tab",
            "--title", title,
            "--",
        ] + wsl_args

        log.info("Launching wt: title=%r script=%s cwd=%r distro=%r",
                 title, rc_arg, cwd, distro)
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise LaunchError(f"wt.exe launch failed: {exc}")

    def _launch_xterm(
        self,
        title: str,
        cwd: str,
        script: Path,
        initial_command: Optional[str],
    ) -> None:
        """Lance xterm (ou autre terminal Linux) avec notre script."""
        term = self._find_xterm()
        if not term:
            raise LaunchError("Aucun terminal Linux trouve (xterm, gnome-terminal...)")

        # Build command selon le terminal
        basename = Path(term).name
        if initial_command:
            bash_cmd = f"source {script} && {initial_command}; exec bash"
        else:
            bash_cmd = f"source {script}; exec bash"

        env = os.environ.copy()
        env["OSCP_SESSION"] = title

        if basename == "xterm":
            cmd = [term, "-T", title, "-e", "bash", "-c", bash_cmd]
        elif basename == "gnome-terminal":
            cmd = [term, "--title", title, "--", "bash", "-c", bash_cmd]
        elif basename == "konsole":
            cmd = [term, "--new-tab", "-p", f"tabtitle={title}", "-e", "bash", "-c", bash_cmd]
        elif basename == "xfce4-terminal":
            cmd = [term, f"--title={title}", "-e", f"bash -c '{bash_cmd}'"]
        else:
            cmd = [term, "-e", "bash", "-c", bash_cmd]

        log.info("Launching %s: title=%r cwd=%r", basename, title, cwd)
        try:
            subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise LaunchError(f"{basename} launch failed: {exc}")