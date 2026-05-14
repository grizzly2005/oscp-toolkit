"""SearchSploit helpers for service/version checks."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Iterable, List, Optional


_VERSION_TOKEN_RE = re.compile(r"^v?(\d+(?:[._-]\d+)*(?:[a-zA-Z]\d*)?(?:[_-]\d+)*)$")
_VERSION_IN_TOKEN_RE = re.compile(r"v?(\d+(?:[._-]\d+)*(?:[a-zA-Z]\d*)?(?:[_-]\d+)*)")
_NMAP_PREFIX_RE = re.compile(r"^\s*\d+/(?:tcp|udp)\s+\S+\s+\S+\s+", re.IGNORECASE)
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_GENERIC_PRODUCT_WORDS = {
    "daemon", "server", "service", "smtpd", "smtp", "httpd", "http",
    "ftp", "ssh", "ssl", "tls",
}


@dataclass
class ServiceVersion:
    source: str
    product: str
    version: str
    product_candidates: List[str] = field(default_factory=list)
    version_candidates: List[str] = field(default_factory=list)


@dataclass
class SearchSploitResult:
    source: str
    query: str
    command: str
    output: str
    has_results: bool
    returncode: int = 0
    error: str = ""


def parse_service_line(line: str) -> Optional[ServiceVersion]:
    """Parse a line such as 'OpenSSH 7.6p1' or an nmap service row."""
    source = line.strip()
    if not source:
        return None

    clean = _NMAP_PREFIX_RE.sub("", source)
    clean = clean.replace("|", " ")
    tokens = [t.strip("()[]{};,") for t in clean.split() if t.strip("()[]{};,")]
    if not tokens:
        return None

    version_index = -1
    version = ""
    for idx, token in enumerate(tokens):
        match = _VERSION_TOKEN_RE.match(token) or _VERSION_IN_TOKEN_RE.search(token)
        if match:
            version_index = idx
            version = match.group(1).lstrip("vV")
            break

    if version_index <= 0:
        return None

    product = _normalize_product(" ".join(tokens[:version_index]))
    if not product:
        return None

    return ServiceVersion(
        source=source,
        product=product,
        version=version,
        product_candidates=_product_candidates(product),
        version_candidates=_version_candidates(version),
    )


def build_queries(service: ServiceVersion, include_broad: bool = False) -> List[str]:
    """Build ordered, version-scoped SearchSploit queries."""
    queries: List[str] = []
    products = service.product_candidates or [service.product]
    versions = service.version_candidates or [service.version]

    for version in versions[:3]:
        for product in products[:3]:
            _append_unique(queries, f"{product} {version}")

    if include_broad:
        for product in products[:2]:
            _append_unique(queries, product)

    return queries


def build_commands(lines: Iterable[str], include_broad: bool = False) -> List[str]:
    commands: List[str] = []
    for line in lines:
        service = parse_service_line(line)
        if service is None:
            continue
        for query in build_queries(service, include_broad=include_broad):
            commands.append(command_line_for_query(query))
    return commands


def command_line_for_query(query: str) -> str:
    return "searchsploit " + " ".join(shlex.quote(part) for part in query.split())


def run_searchsploit(query: str, timeout_sec: int = 20) -> SearchSploitResult:
    command = command_line_for_query(query)
    exe = shutil.which("searchsploit")
    if not exe:
        return SearchSploitResult(
            source="",
            query=query,
            command=command,
            output="",
            has_results=False,
            returncode=127,
            error="searchsploit introuvable dans le PATH.",
        )

    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")
    proc = subprocess.run(
        [exe, *query.split()],
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        env=env,
        check=False,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    output = clean_searchsploit_output(output)
    return SearchSploitResult(
        source="",
        query=query,
        command=command,
        output=output.strip(),
        has_results=has_searchsploit_results(output),
        returncode=proc.returncode,
    )


def clean_searchsploit_output(output: str) -> str:
    return _ANSI_RE.sub("", output).replace("\r\n", "\n").replace("\r", "\n")


def has_searchsploit_results(output: str) -> bool:
    cleaned = clean_searchsploit_output(output)
    if not cleaned.strip():
        return False
    in_result_table = False
    for line in cleaned.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if not stripped:
            continue
        if "exploit title" in lower and "path" in lower:
            in_result_table = True
            continue
        if not in_result_table:
            continue
        if "|" not in stripped:
            continue
        if _is_table_separator(stripped):
            continue
        return True
    return False


def _is_table_separator(line: str) -> bool:
    return not line.replace("|", "").replace("-", "").strip()


def _normalize_product(product: str) -> str:
    product = re.sub(r"\s+", " ", product).strip(" -_/").lower()
    product = product.replace("open ssh", "openssh")
    product = product.replace("microsoft-iis", "microsoft iis")
    return product


def _product_candidates(product: str) -> List[str]:
    tokens = product.split()
    candidates: List[str] = []
    _append_unique(candidates, product)

    meaningful = [t for t in tokens if t.lower() not in _GENERIC_PRODUCT_WORDS]
    if meaningful:
        _append_unique(candidates, " ".join(meaningful))
        _append_unique(candidates, meaningful[0])

    if len(tokens) > 1:
        _append_unique(candidates, tokens[0])

    if "iis" in tokens:
        _append_unique(candidates, "iis")
    if "apache" in tokens or product == "httpd":
        _append_unique(candidates, "apache")
    if "exim" in tokens:
        _append_unique(candidates, "exim")
    if product == "smtpd":
        _append_unique(candidates, "exim")

    return candidates


def _version_candidates(version: str) -> List[str]:
    candidates: List[str] = []
    cleaned = version.strip("vV")
    _append_unique(candidates, cleaned)

    normalized = cleaned.replace("_", ".")
    _append_unique(candidates, normalized)

    numeric_prefix = re.match(r"(\d+(?:[._-]\d+)*)", cleaned)
    if numeric_prefix:
        numeric = numeric_prefix.group(1).replace("_", ".")
        _append_unique(candidates, numeric)
        parts = re.split(r"[._-]", numeric)
        if len(parts) >= 2:
            _append_unique(candidates, ".".join(parts[:2]))

    return candidates


def _append_unique(items: List[str], value: str) -> None:
    value = value.strip()
    if value and value not in items:
        items.append(value)
