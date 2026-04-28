"""AutoGrep — parsing de texte collé manuellement.

Pas de lancement de scans. Juste : "l'utilisateur colle l'output nmap,
on extrait les ports/services" ou "il colle linpeas, on liste les SUIDs".

Chaque parser est isolé : si un crash, les autres continuent. Les
résultats sont structurés et peuvent alimenter le Vault (credentials),
le Hash Identifier (hashes), et les notes (structuration).

Exposé : `run_all(text)` qui renvoie un dict {parser_name: [...items]}.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from .logger import get_logger

log = get_logger(__name__)


@dataclass
class Finding:
    kind: str
    value: str
    context: str = ""
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------
# Parsers
# --------------------------------------------------------------

_IP_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Hashes : on fait simple par longueur + charset (les validations fines
# sont dans hash_identifier.py)
_HASH_CANDIDATES = [
    ("MD5", re.compile(r"\b[a-fA-F0-9]{32}\b")),
    ("SHA1", re.compile(r"\b[a-fA-F0-9]{40}\b")),
    ("SHA256", re.compile(r"\b[a-fA-F0-9]{64}\b")),
    ("SHA512", re.compile(r"\b[a-fA-F0-9]{128}\b")),
    ("bcrypt", re.compile(r"\$2[ayb]\$[0-9]{2}\$[./A-Za-z0-9]{53}")),
    ("NetNTLMv2", re.compile(r"[^:\s]+::[^:\s]*:[A-Fa-f0-9]{16}:[A-Fa-f0-9]{32}:[A-Fa-f0-9]+")),
    ("NetNTLMv1", re.compile(r"[^:\s]+::[^:\s]*:[A-Fa-f0-9]{48}:[A-Fa-f0-9]{48}:[A-Fa-f0-9]{16}")),
    ("Kerberos-krb5tgs", re.compile(r"\$krb5tgs\$[^\s]+")),
    ("Kerberos-krb5asrep", re.compile(r"\$krb5asrep\$[^\s]+")),
    ("DCC2", re.compile(r"\$DCC2\$[^\s]+")),
]

# NTLM format "user:rid:LM:NTLM:::" (impacket secretsdump)
_NTLM_DUMP_RE = re.compile(
    r"(?P<user>[^\s:]+):(?P<rid>\d+):(?P<lm>[a-fA-F0-9]{32}):(?P<nt>[a-fA-F0-9]{32}):::"
)

# Creds génériques "user:pass" dans un contexte de creds
_CRED_LINE_RE = re.compile(
    r"(?:^|[\s,])(?P<user>[A-Za-z][A-Za-z0-9._\-@\\]{1,40}):(?P<pass>[^\s]{3,120})"
)

# John/hashcat output : "password:hash"
_JOHN_CRACKED_RE = re.compile(
    r"^(?P<hash>[^:]+):(?P<plain>.+?)(?:\s*\(.*\))?$"
)


def parse_ips(text: str) -> List[Finding]:
    seen = set()
    out = []
    for m in _IP_RE.finditer(text):
        ip = m.group(0)
        if ip in seen:
            continue
        # Skippe les trucs trop clairement non-IP
        parts = ip.split(".")
        if any(int(p) > 255 for p in parts):
            continue
        seen.add(ip)
        out.append(Finding(kind="ip", value=ip))
    return out


def parse_urls(text: str) -> List[Finding]:
    seen = set()
    out = []
    for m in _URL_RE.finditer(text):
        u = m.group(0).rstrip(".,;")
        if u in seen:
            continue
        seen.add(u)
        out.append(Finding(kind="url", value=u))
    return out


def parse_emails(text: str) -> List[Finding]:
    seen = set()
    out = []
    for m in _EMAIL_RE.finditer(text):
        e = m.group(0)
        if e in seen:
            continue
        seen.add(e)
        out.append(Finding(kind="email", value=e))
    return out


def parse_hashes(text: str) -> List[Finding]:
    """Extrait tous les candidats hashes avec leur type probable."""
    seen = set()
    out = []
    for kind, regex in _HASH_CANDIDATES:
        for m in regex.finditer(text):
            value = m.group(0)
            if value in seen:
                continue
            seen.add(value)
            out.append(Finding(kind=f"hash/{kind}", value=value))
    # NTLM dumps
    for m in _NTLM_DUMP_RE.finditer(text):
        value = f"{m.group('user')}:{m.group('nt')}"
        if value in seen:
            continue
        seen.add(value)
        out.append(Finding(
            kind="hash/NTLM",
            value=m.group("nt"),
            extra={"user": m.group("user"), "rid": m.group("rid")},
        ))
    return out


def parse_credentials(text: str) -> List[Finding]:
    """Détecte des patterns user:password. Heuristique, pas infaillible."""
    seen = set()
    out = []
    for m in _CRED_LINE_RE.finditer(text):
        user = m.group("user")
        pwd = m.group("pass")
        # filtre quelques false positives trop évidents
        if user.lower() in {"http", "https", "file", "ftp"}:
            continue
        if ":" in pwd:  # plausiblement une URL ou un hash structuré
            continue
        if len(pwd) > 60 and all(c in "0123456789abcdefABCDEF" for c in pwd):
            continue                                   # c'est un hash
        key = f"{user}:{pwd}"
        if key in seen:
            continue
        seen.add(key)
        out.append(Finding(
            kind="credential",
            value=key,
            extra={"user": user, "password": pwd},
        ))
    return out


def parse_john_cracked(text: str) -> List[Finding]:
    """Lignes typiques : `john --show` ou `hashcat --show`."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        # On veut des lignes au moins partiellement en hex pour la première part
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        left, right = parts
        if len(left) not in (16, 32, 40, 64) or not all(
            c in "0123456789abcdefABCDEF" for c in left
        ):
            continue
        out.append(Finding(
            kind="cracked",
            value=right,
            extra={"hash": left, "plain": right},
        ))
    return out


def parse_nmap(text: str) -> List[Finding]:
    """Extrait les ports/services. Format 'PORT     STATE SERVICE VERSION'."""
    out = []
    # Ex : "22/tcp   open  ssh     OpenSSH 8.2p1 Ubuntu 4ubuntu0.5"
    line_re = re.compile(
        r"^\s*(?P<port>\d+)/(?P<proto>tcp|udp)\s+(?P<state>open|filtered|closed|open\|filtered)"
        r"\s+(?P<service>[A-Za-z0-9_\-]+)(?:\s+(?P<version>.+))?$"
    )
    os_re = re.compile(r"^OS details?:\s+(.+)$", re.IGNORECASE)
    host_re = re.compile(r"^Nmap scan report for\s+(?P<host>.+)$")
    current_host = None
    for raw in text.splitlines():
        line = raw.rstrip()
        mh = host_re.match(line)
        if mh:
            current_host = mh.group("host")
            continue
        mo = os_re.match(line)
        if mo:
            out.append(Finding(
                kind="nmap/os",
                value=mo.group(1).strip(),
                extra={"host": current_host},
            ))
            continue
        mp = line_re.match(line)
        if mp:
            value = f"{mp.group('port')}/{mp.group('proto')} {mp.group('service')}"
            out.append(Finding(
                kind="nmap/port",
                value=value,
                extra={
                    "host": current_host,
                    "port": int(mp.group("port")),
                    "proto": mp.group("proto"),
                    "state": mp.group("state"),
                    "service": mp.group("service"),
                    "version": (mp.group("version") or "").strip(),
                },
            ))
    return out


def parse_linpeas(text: str) -> List[Finding]:
    """Extrait SUIDs, cron jobs, writable paths, passwords détectés."""
    out = []
    # Section markers dans linpeas (sans couleurs ANSI idéalement)
    # On cherche des patterns fréquents :
    suid_re = re.compile(r"-[rwx-]{9}.*?\b\d+\b.*?\b(/[\w./\-]+)")
    cron_re = re.compile(r"^\s*(\*|\d|\*/\d).*?(/[\w./\-]+)", re.MULTILINE)
    # Les "Possible sensitive files" montrent souvent des chemins
    for line in text.splitlines():
        low = line.lower()
        if "suid" in low and "/" in line:
            m = re.search(r"(/[\w./\-]+)", line)
            if m:
                out.append(Finding(kind="linpeas/suid", value=m.group(1)))
        if "cron" in low and "/" in line and ("*" in line or re.search(r"\b\d+\s+\d+\s+\*", line)):
            m = re.search(r"(/[\w./\-]+)", line)
            if m:
                out.append(Finding(kind="linpeas/cron", value=m.group(1), context=line.strip()))
        if "writable" in low:
            m = re.search(r"(/[\w./\-]+)", line)
            if m:
                out.append(Finding(kind="linpeas/writable", value=m.group(1)))
        if "capability" in low or "cap_" in low:
            m = re.search(r"(/[\w./\-]+)", line)
            if m:
                out.append(Finding(kind="linpeas/capability", value=m.group(1), context=line.strip()))
    return out


def parse_winpeas(text: str) -> List[Finding]:
    """Extrait services modifiables, tokens, credentials."""
    out = []
    for line in text.splitlines():
        low = line.lower()
        if "unquoted" in low and "service" in low:
            out.append(Finding(kind="winpeas/unquoted_service", value=line.strip()))
        if "writable" in low and (".exe" in low or "service" in low):
            out.append(Finding(kind="winpeas/writable_service", value=line.strip()))
        if "seimpersonate" in low or "seassignprimarytoken" in low:
            out.append(Finding(kind="winpeas/potato_token", value=line.strip()))
        if "password" in low and "=" in low:
            out.append(Finding(kind="winpeas/cred", value=line.strip()))
        if "autologon" in low:
            out.append(Finding(kind="winpeas/autologon", value=line.strip()))
    return out


# --------------------------------------------------------------
# Runner
# --------------------------------------------------------------

PARSERS: Dict[str, Callable[[str], List[Finding]]] = {
    "ips": parse_ips,
    "urls": parse_urls,
    "emails": parse_emails,
    "hashes": parse_hashes,
    "credentials": parse_credentials,
    "cracked": parse_john_cracked,
    "nmap": parse_nmap,
    "linpeas": parse_linpeas,
    "winpeas": parse_winpeas,
}


def run_all(text: str) -> Dict[str, List[Finding]]:
    """Applique tous les parsers. Un parser qui crash est isolé."""
    results: Dict[str, List[Finding]] = {}
    for name, fn in PARSERS.items():
        try:
            results[name] = fn(text)
        except Exception as exc:  # parseur foireux -> on continue
            log.exception("Parser %s crashed", name)
            results[name] = []
    total = sum(len(v) for v in results.values())
    log.info("AutoGrep: %d findings across %d parsers", total, len(PARSERS))
    return results


def run(name: str, text: str) -> List[Finding]:
    fn = PARSERS.get(name)
    if not fn:
        return []
    try:
        return fn(text)
    except Exception:
        log.exception("Parser %s crashed", name)
        return []
