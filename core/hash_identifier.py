"""Hash Identifier — analyse longueur + pattern + préfixes.

Retourne une liste de candidats avec un score de confiance
(haute / moyenne / faible) et les commandes john/hashcat suggérées
avec le bon format/mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# Table : (nom, longueur_min, longueur_max, charset_regex, prefix, hashcat_mode, john_format)
HASH_TYPES = [
    # (nom, regex fullmatch, prefix optionnel, hashcat, john, confiance_base)
    ("MD5",              r"^[a-fA-F0-9]{32}$",          None,       "0",     "raw-md5",          "moyenne"),
    ("NTLM",             r"^[a-fA-F0-9]{32}$",          None,       "1000",  "nt",               "haute-si-contexte"),
    ("LM",               r"^[a-fA-F0-9]{32}$",          None,       "3000",  "lm",               "faible"),
    ("MD4",              r"^[a-fA-F0-9]{32}$",          None,       "900",   "raw-md4",          "faible"),
    ("SHA1",             r"^[a-fA-F0-9]{40}$",          None,       "100",   "raw-sha1",         "moyenne"),
    ("MySQL4.1+",        r"^[a-fA-F0-9]{40}$",          None,       "300",   "mysql-sha1",       "faible"),
    ("SHA224",           r"^[a-fA-F0-9]{56}$",          None,       "1300",  "raw-sha224",       "faible"),
    ("SHA256",           r"^[a-fA-F0-9]{64}$",          None,       "1400",  "raw-sha256",       "moyenne"),
    ("SHA384",           r"^[a-fA-F0-9]{96}$",          None,       "10800", "raw-sha384",       "faible"),
    ("SHA512",           r"^[a-fA-F0-9]{128}$",         None,       "1700",  "raw-sha512",       "moyenne"),
    ("bcrypt",           r"^\$2[ayb]\$\d{2}\$[./A-Za-z0-9]{53}$", "$2", "3200", "bcrypt",        "haute"),
    ("Linux SHA-512 crypt", r"^\$6\$[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}$", "$6$", "1800", "sha512crypt", "haute"),
    ("Linux SHA-256 crypt", r"^\$5\$[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{43}$", "$5$", "7400", "sha256crypt", "haute"),
    ("Linux MD5 crypt",  r"^\$1\$[./A-Za-z0-9]{1,8}\$[./A-Za-z0-9]{22}$", "$1$", "500", "md5crypt",      "haute"),
    ("Cisco $9$ (scrypt)", r"^\$9\$[./A-Za-z0-9]+\$[./A-Za-z0-9]+$", "$9$", "9300", "scrypt",        "haute"),
    ("NetNTLMv2",        r"^[^:\s]+::[^:\s]*:[A-Fa-f0-9]{16}:[A-Fa-f0-9]{32}:[A-Fa-f0-9]+$", None, "5600", "netntlmv2", "haute"),
    ("NetNTLMv1",        r"^[^:\s]+::[^:\s]*:[A-Fa-f0-9]{48}:[A-Fa-f0-9]{48}:[A-Fa-f0-9]{16}$", None, "5500", "netntlm",   "haute"),
    ("Kerberos 5 TGS-REP", r"^\$krb5tgs\$.+$", "$krb5tgs$", "13100", "krb5tgs",           "haute"),
    ("Kerberos 5 AS-REP",  r"^\$krb5asrep\$.+$", "$krb5asrep$", "18200", "krb5asrep",      "haute"),
    ("DCC2 (MS Cache v2)", r"^\$DCC2\$.+$",        "$DCC2$",   "2100",  "mscash2",         "haute"),
    ("MS Cache v1",        r"^M\$.+#[a-fA-F0-9]{32}$", "M$",      "1100",  "mscash",          "haute"),
    ("Django PBKDF2-SHA256", r"^pbkdf2_sha256\$\d+\$.+\$.+$", "pbkdf2_sha256$", "10000", "django", "haute"),
    ("Argon2",           r"^\$argon2[idx]\$.+$",       "$argon2",  "",      "argon2",           "haute"),
    ("WPA/WPA2 PMKID/EAPOL (hashcat -m 22000)", r"^WPA\*\d+\*.+$", "WPA*", "22000", "",       "haute"),
]


@dataclass
class HashCandidate:
    name: str
    hashcat_mode: str
    john_format: str
    confidence: str                 # "haute" / "moyenne" / "faible"

    def hashcat_command(self, hash_file: str = "hash.txt", wordlist: str = "/usr/share/wordlists/rockyou.txt") -> str:
        if not self.hashcat_mode:
            return f"# Pas de mode hashcat standard pour {self.name}"
        return f"hashcat -m {self.hashcat_mode} {hash_file} {wordlist}"

    def john_command(self, hash_file: str = "hash.txt", wordlist: str = "/usr/share/wordlists/rockyou.txt") -> str:
        if not self.john_format:
            return f"# Pas de format john standard pour {self.name}"
        return f"john --format={self.john_format} --wordlist={wordlist} {hash_file}"


@dataclass
class IdentificationResult:
    input_hash: str
    candidates: List[HashCandidate] = field(default_factory=list)

    def best(self) -> Optional[HashCandidate]:
        ordering = {"haute": 0, "haute-si-contexte": 1, "moyenne": 2, "faible": 3}
        if not self.candidates:
            return None
        return sorted(self.candidates, key=lambda c: ordering.get(c.confidence, 99))[0]


def identify(hash_str: str) -> IdentificationResult:
    s = hash_str.strip()
    result = IdentificationResult(input_hash=s)

    if not s:
        return result

    for name, pat, prefix, hashcat, john, base_conf in HASH_TYPES:
        try:
            if not re.fullmatch(pat, s, re.IGNORECASE):
                continue
        except re.error:
            continue

        # On ajuste la confiance selon le contexte (ex: 32 hex chars = MD5 ou NTLM)
        conf = base_conf
        if base_conf == "haute-si-contexte":
            conf = "moyenne"       # sans contexte on le laisse moyen
        result.candidates.append(HashCandidate(
            name=name,
            hashcat_mode=hashcat,
            john_format=john,
            confidence=conf,
        ))
    return result


def detect_many(text: str) -> List[IdentificationResult]:
    """Découpe text par lignes et identifie chaque ligne comme un hash."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        res = identify(line)
        if res.candidates:
            out.append(res)
    return out
