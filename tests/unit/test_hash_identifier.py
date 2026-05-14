"""Tests for the hash identifier heuristics."""
from __future__ import annotations

from core.hash_identifier import identify, save_hash_command


def _names(value: str) -> list[str]:
    return [candidate.name for candidate in identify(value).candidates]


def test_identifies_ambiguous_32_hex_hashes() -> None:
    names = _names("8846f7eaee8fb117ad06bdd830b7586c")

    assert "NTLM" in names
    assert "MD5" in names
    assert "LM" in names


def test_identifies_bcrypt_with_high_confidence() -> None:
    bcrypt_hash = "$2y$12$" + ("A" * 53)
    result = identify(bcrypt_hash)

    assert result.best() is not None
    assert result.best().name == "bcrypt"
    assert result.best().confidence == "haute"
    assert result.best().hashcat_command() == "hashcat -m 3200 hash.txt /usr/share/wordlists/rockyou.txt"


def test_extracts_shadow_hash_before_identifying() -> None:
    crypt_hash = "$6$rounds=5000$saltstring$" + ("A" * 86)
    shadow_line = f"root:{crypt_hash}:19000:0:99999:7:::"
    result = identify(shadow_line)

    assert result.best() is not None
    assert result.best().name == "Linux SHA-512 crypt"
    assert result.best().matched_value == crypt_hash
    assert result.best().source == "colon-field"
    assert result.best().hashcat_command("hashes with spaces.txt", "/tmp/word lists/rockyou.txt") == (
        "hashcat -m 1800 'hashes with spaces.txt' '/tmp/word lists/rockyou.txt'"
    )


def test_extracts_ntlm_from_pwdump_line() -> None:
    ntlm_hash = "8846f7eaee8fb117ad06bdd830b7586c"
    pwdump_line = f"Administrator:500:aad3b435b51404eeaad3b435b51404ee:{ntlm_hash}:::"
    result = identify(pwdump_line)

    assert result.best() is not None
    assert result.best().name == "NTLM (pwdump/NTDS extrait)"
    assert result.best().matched_value == ntlm_hash
    assert result.best().confidence == "haute"
    assert "Le champ LM est le placeholder" in " ".join(result.best().notes)


def test_kerberos_tgs_etype_selects_hashcat_mode() -> None:
    result = identify("$krb5tgs$18$dummy")

    assert result.best() is not None
    assert result.best().name == "Kerberos 5 TGS-REP etype 18"
    assert result.best().hashcat_mode == "19700"


def test_save_hash_command_quotes_shell_values() -> None:
    assert save_hash_command("$6$salt$hash", "hash file.txt") == "printf '%s\\n' '$6$salt$hash' > 'hash file.txt'"
