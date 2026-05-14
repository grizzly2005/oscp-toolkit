"""Hash Identifier — analyse longueur, pattern, préfixes et formats complets.

Retourne une liste de candidats avec un score de confiance
(haute / moyenne / faible) et les commandes john/hashcat suggérées
avec le bon format/mode.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence


CONFIDENCE_ORDER = {"haute": 0, "moyenne": 1, "faible": 2}
DISABLED_LM_HASH = "aad3b435b51404eeaad3b435b51404ee"


@dataclass(frozen=True)
class HashSignature:
    name: str
    pattern: re.Pattern[str]
    hashcat_mode: str
    john_format: str
    confidence: str
    priority: int = 50
    hashcat_options: Sequence[str] = ()
    john_options: Sequence[str] = ()
    notes: Sequence[str] = ()

    def matches(self, value: str) -> bool:
        return self.pattern.fullmatch(value) is not None


def _sig(
    name: str,
    pattern: str,
    hashcat_mode: str = "",
    john_format: str = "",
    confidence: str = "moyenne",
    *,
    priority: int = 50,
    flags: int = re.IGNORECASE,
    hashcat_options: Sequence[str] = (),
    john_options: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> HashSignature:
    return HashSignature(
        name=name,
        pattern=re.compile(pattern, flags),
        hashcat_mode=hashcat_mode,
        john_format=john_format,
        confidence=confidence,
        priority=priority,
        hashcat_options=tuple(hashcat_options),
        john_options=tuple(john_options),
        notes=tuple(notes),
    )


HASH_TYPES = [
    # Formats réseau / Windows à structure forte.
    _sig("NetNTLMv2", r"[^:\s]+::[^:\s]*:[A-Fa-f0-9]{16}:[A-Fa-f0-9]{32}:[A-Fa-f0-9]+", "5600", "netntlmv2", "haute", priority=1),
    _sig("NetNTLMv1", r"[^:\s]+::[^:\s]*:[A-Fa-f0-9]{48}:[A-Fa-f0-9]{48}:[A-Fa-f0-9]{16}", "5500", "netntlm", "haute", priority=2),
    _sig("DCC2 (MS Cache v2)", r"\$DCC2\$.+", "2100", "mscash2", "haute", priority=3),
    _sig("MS Cache v1", r"M\$[^#]+#[a-fA-F0-9]{32}", "1100", "mscash", "haute", priority=4),

    # Kerberos : hashcat change de mode selon l'etype TGS.
    _sig("Kerberos 5 TGS-REP etype 23", r"\$krb5tgs\$23\$.+", "13100", "krb5tgs", "haute", priority=5),
    _sig("Kerberos 5 TGS-REP etype 17", r"\$krb5tgs\$17\$.+", "19600", "krb5tgs", "haute", priority=5),
    _sig("Kerberos 5 TGS-REP etype 18", r"\$krb5tgs\$18\$.+", "19700", "krb5tgs", "haute", priority=5),
    _sig("Kerberos 5 TGS-REP", r"\$krb5tgs\$(?!17\$|18\$|23\$).+", "", "krb5tgs", "moyenne", priority=25),
    _sig("Kerberos 5 AS-REP etype 23", r"\$krb5asrep\$23\$.+", "18200", "krb5asrep", "haute", priority=6),
    _sig("Kerberos 5 AS-REP", r"\$krb5asrep\$(?!23\$).+", "", "krb5asrep", "moyenne", priority=25),

    # Unix / Linux / applications web.
    _sig("bcrypt", r"\$2[abxy]\$\d{2}\$[./A-Za-z0-9]{53}", "3200", "bcrypt", "haute", priority=10),
    _sig("Linux SHA-512 crypt", r"\$6\$(?:rounds=\d+\$)?[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}", "1800", "sha512crypt", "haute", priority=11),
    _sig("Linux SHA-256 crypt", r"\$5\$(?:rounds=\d+\$)?[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{43}", "7400", "sha256crypt", "haute", priority=12),
    _sig("Linux MD5 crypt", r"\$1\$[./A-Za-z0-9]{1,8}\$[./A-Za-z0-9]{22}", "500", "md5crypt", "haute", priority=13),
    _sig("Apache MD5 apr1", r"\$apr1\$[./A-Za-z0-9]{1,8}\$[./A-Za-z0-9]{22}", "1600", "md5crypt", "haute", priority=14),
    _sig("yescrypt / libxcrypt", r"\$y\$[./A-Za-z0-9]+\$[./A-Za-z0-9]+\$[./A-Za-z0-9./]+", "", "crypt", "haute", priority=15),
    _sig("Argon2", r"\$argon2(?:id|i|d)\$.+", "", "argon2", "haute", priority=16),
    _sig("WordPress / phpBB phpass", r"\$[PH]\$[./A-Za-z0-9]{31}", "400", "phpass", "haute", priority=17),
    _sig("Drupal 7", r"\$S\$[./A-Za-z0-9]{52}", "7900", "Drupal7", "haute", priority=18),
    _sig("Django PBKDF2-SHA256", r"pbkdf2_sha256\$\d+\$[^$]+\$[^$]+", "10000", "django", "haute", priority=19),
    _sig("PostgreSQL MD5", r"md5[a-fA-F0-9]{32}", "12", "postgres", "haute", priority=20),
    _sig("Cisco IOS $8$ (PBKDF2-SHA256)", r"\$8\$[./A-Za-z0-9]{14}\$[./A-Za-z0-9]{43}", "9200", "cisco8", "haute", priority=21),
    _sig("Cisco IOS $9$ (scrypt)", r"\$9\$[./A-Za-z0-9]{14}\$[./A-Za-z0-9]{43}", "9300", "cisco9", "haute", priority=22),
    _sig("WPA/WPA2 PMKID/EAPOL", r"WPA\*\d+\*.+", "22000", "", "haute", priority=23),
    _sig("JWT HMAC", r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+", "16500", "", "moyenne", priority=24),

    # Hashes bruts ou ambigus.
    _sig("MySQL 4.1+/5", r"\*[A-Fa-f0-9]{40}", "300", "mysql-sha1", "haute", priority=30),
    _sig("MySQL pre-4.1", r"[A-Fa-f0-9]{16}", "200", "mysql", "faible", priority=70),
    _sig("SHA1", r"[a-fA-F0-9]{40}", "100", "raw-sha1", "moyenne", priority=50),
    _sig("SHA224", r"[a-fA-F0-9]{56}", "1300", "raw-sha224", "faible", priority=60),
    _sig("SHA256", r"[a-fA-F0-9]{64}", "1400", "raw-sha256", "moyenne", priority=50),
    _sig("SHA384", r"[a-fA-F0-9]{96}", "10800", "raw-sha384", "faible", priority=60),
    _sig("SHA512", r"[a-fA-F0-9]{128}", "1700", "raw-sha512", "moyenne", priority=50),
    _sig("NTLM", r"[a-fA-F0-9]{32}", "1000", "nt", "moyenne", priority=51),
    _sig("MD5", r"[a-fA-F0-9]{32}", "0", "raw-md5", "moyenne", priority=52),
    _sig("LM", r"[a-fA-F0-9]{32}", "3000", "lm", "faible", priority=61),
    _sig("MD4", r"[a-fA-F0-9]{32}", "900", "raw-md4", "faible", priority=62),
]


@dataclass
class HashCandidate:
    name: str
    hashcat_mode: str
    john_format: str
    confidence: str                 # "haute" / "moyenne" / "faible"
    matched_value: str = ""          # valeur extraite si l'entrée contenait une ligne complète
    source: str = "input"
    hashcat_options: Sequence[str] = field(default_factory=tuple)
    john_options: Sequence[str] = field(default_factory=tuple)
    notes: List[str] = field(default_factory=list)
    priority: int = 50

    def hashcat_command(self, hash_file: str = "hash.txt", wordlist: str = "/usr/share/wordlists/rockyou.txt") -> str:
        if not self.hashcat_mode:
            return f"# Pas de mode hashcat standard pour {self.name}"
        parts = ["hashcat", "-m", self.hashcat_mode, *self.hashcat_options, hash_file, wordlist]
        return " ".join(shlex.quote(part) for part in parts)

    def john_command(self, hash_file: str = "hash.txt", wordlist: str = "/usr/share/wordlists/rockyou.txt") -> str:
        if not self.john_format:
            return f"# Pas de format john standard pour {self.name}"
        parts = ["john", f"--format={self.john_format}", *self.john_options, f"--wordlist={wordlist}", hash_file]
        return " ".join(shlex.quote(part) for part in parts)


@dataclass
class IdentificationResult:
    input_hash: str
    candidates: List[HashCandidate] = field(default_factory=list)

    def best(self) -> Optional[HashCandidate]:
        if not self.candidates:
            return None
        return self.candidates[0]


@dataclass(frozen=True)
class _InputVariant:
    value: str
    source: str
    notes: Sequence[str] = ()
    priority_offset: int = 0


def _shell_save_command(value: str, hash_file: str = "hash.txt") -> str:
    return f"printf '%s\\n' {shlex.quote(value)} > {shlex.quote(hash_file)}"


def _clean_input(hash_str: str) -> str:
    s = hash_str.strip().lstrip("\ufeff")
    if len(s) >= 2 and s[0] == s[-1] and s[0] in {"'", '"'}:
        return s[1:-1].strip()
    return s


def _looks_like_hash_field(value: str) -> bool:
    if not value or value in {"x", "*", "!", "!!"}:
        return False
    return (
        value.startswith("$")
        or value.startswith("*")
        or value.startswith("md5")
        or value.startswith("pbkdf2_")
        or re.fullmatch(r"[A-Fa-f0-9]{16,128}", value) is not None
    )


def _input_variants(value: str) -> List[_InputVariant]:
    variants = [_InputVariant(value=value, source="input")]
    parts = value.split(":")
    if len(parts) >= 2 and _looks_like_hash_field(parts[1]):
        variants.append(_InputVariant(
            value=parts[1],
            source="colon-field",
            notes=("Hash extrait du 2e champ d'une ligne avec séparateurs ':'.",),
            priority_offset=-5,
        ))
    return variants


def _pwdump_candidates(value: str) -> List[HashCandidate]:
    parts = value.split(":")
    if len(parts) < 4 or not re.fullmatch(r"\d+", parts[1] or ""):
        return []
    lm_hash = parts[2].lower()
    ntlm_hash = parts[3].lower()
    if not re.fullmatch(r"[a-f0-9]{32}", lm_hash) or not re.fullmatch(r"[a-f0-9]{32}", ntlm_hash):
        return []

    notes = ["Hash NTLM extrait du 4e champ pwdump/NTDS."]
    if lm_hash == DISABLED_LM_HASH:
        notes.append("Le champ LM est le placeholder désactivé classique.")

    candidates = [
        HashCandidate(
            name="NTLM (pwdump/NTDS extrait)",
            hashcat_mode="1000",
            john_format="nt",
            confidence="haute",
            matched_value=ntlm_hash,
            source="pwdump",
            notes=notes,
            priority=0,
        )
    ]

    if lm_hash != DISABLED_LM_HASH:
        candidates.append(HashCandidate(
            name="LM (pwdump/NTDS extrait)",
            hashcat_mode="3000",
            john_format="lm",
            confidence="haute",
            matched_value=lm_hash,
            source="pwdump",
            notes=["Hash LM extrait du 3e champ pwdump/NTDS."],
            priority=1,
        ))

    return candidates


def _candidate_key(candidate: HashCandidate) -> tuple:
    return (
        candidate.name,
        candidate.hashcat_mode,
        candidate.john_format,
        candidate.matched_value,
        tuple(candidate.hashcat_options),
        tuple(candidate.john_options),
    )


def _sort_candidates(candidates: Iterable[HashCandidate]) -> List[HashCandidate]:
    unique = {}
    for candidate in candidates:
        key = _candidate_key(candidate)
        if key not in unique:
            unique[key] = candidate
    return sorted(
        unique.values(),
        key=lambda c: (CONFIDENCE_ORDER.get(c.confidence, 99), c.priority, c.name),
    )


def identify(hash_str: str) -> IdentificationResult:
    s = _clean_input(hash_str)
    result = IdentificationResult(input_hash=s)

    if not s:
        return result

    candidates: List[HashCandidate] = []
    candidates.extend(_pwdump_candidates(s))

    for variant in _input_variants(s):
        for signature in HASH_TYPES:
            if not signature.matches(variant.value):
                continue
            candidates.append(HashCandidate(
                name=signature.name,
                hashcat_mode=signature.hashcat_mode,
                john_format=signature.john_format,
                confidence=signature.confidence,
                matched_value=variant.value if variant.value != s else "",
                source=variant.source,
                hashcat_options=tuple(signature.hashcat_options),
                john_options=tuple(signature.john_options),
                notes=[*signature.notes, *variant.notes],
                priority=signature.priority + variant.priority_offset,
            ))

    result.candidates = _sort_candidates(candidates)
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


def save_hash_command(hash_value: str, hash_file: str = "hash.txt") -> str:
    """Commande shell POSIX sûre pour écrire le hash dans un fichier."""
    return _shell_save_command(hash_value, hash_file)
