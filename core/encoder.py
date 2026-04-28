"""Encoder / Decoder.

Opérations :
- Base64 encode/decode
- URL encode/decode
- Hex encode/decode
- PowerShell -EncodedCommand (UTF-16LE + Base64)
- ROT13 (bonus, souvent utile en CTF/OSCP prep)

API pure : fonctions stateless, faciles à tester.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import urllib.parse


def encode_base64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def decode_base64(text: str) -> str:
    # Pad si nécessaire
    padding = (-len(text)) % 4
    padded = text + ("=" * padding)
    try:
        # validate=True -> raise binascii.Error si caracteres non-base64
        # (sinon Python decode silencieusement en ignorant les caracteres
        # invalides, ce qui peut donner du contenu binaire bizarre).
        return base64.b64decode(padded, validate=True).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Invalid base64: {exc}")


def encode_url(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def encode_url_full(text: str) -> str:
    """URL-encode y compris les caractères habituellement safe (/, -, _, .)."""
    return "".join(f"%{ord(c):02X}" for c in text)


def decode_url(text: str) -> str:
    return urllib.parse.unquote(text)


def encode_hex(text: str) -> str:
    return text.encode("utf-8").hex()


def decode_hex(text: str) -> str:
    clean = text.replace(" ", "").replace("\n", "")
    try:
        return bytes.fromhex(clean).decode("utf-8", errors="replace")
    except ValueError as exc:
        raise ValueError(f"Invalid hex: {exc}")


def encode_powershell_base64(command: str) -> str:
    """Produit le Base64 attendu par `powershell -EncodedCommand`.

    PowerShell attend de l'UTF-16 LE base64-encodé.
    """
    return base64.b64encode(command.encode("utf-16-le")).decode("ascii")


def decode_powershell_base64(text: str) -> str:
    padding = (-len(text)) % 4
    padded = text + ("=" * padding)
    raw = base64.b64decode(padded)
    return raw.decode("utf-16-le", errors="replace")


def encode_rot13(text: str) -> str:
    return codecs.encode(text, "rot_13")


def decode_rot13(text: str) -> str:
    return codecs.decode(text, "rot_13")


# --------------------------------------------------------------
# Registre (pour driver la UI)
# --------------------------------------------------------------

ENCODERS = {
    "base64": (encode_base64, decode_base64),
    "url": (encode_url, decode_url),
    "url_full": (encode_url_full, decode_url),
    "hex": (encode_hex, decode_hex),
    "powershell_b64": (encode_powershell_base64, decode_powershell_base64),
    "rot13": (encode_rot13, decode_rot13),
}


def apply(mode: str, text: str, decode: bool = False) -> str:
    pair = ENCODERS.get(mode)
    if pair is None:
        raise ValueError(f"Unknown mode '{mode}'")
    return pair[1 if decode else 0](text)
