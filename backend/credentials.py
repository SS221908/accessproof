"""Validate API-key formatting and compare values without exposing credentials."""
from hashlib import sha256


def api_key_format_valid(value: str) -> bool:
    key = value.strip()
    return bool(key) and key.isascii() and all(33 <= ord(character) <= 126 for character in key)


def api_key_summary(value: str) -> dict:
    key = value.strip()
    return {
        "configured": bool(key),
        "format_valid": api_key_format_valid(key),
        "fingerprint": sha256(key.encode("utf-8")).hexdigest()[:12] if key else None,
        "invalid_characters": {
            "whitespace": sum(character.isspace() for character in key),
            "controls": sum(ord(character) < 32 or ord(character) == 127 for character in key),
            "non_ascii": sum(ord(character) > 127 for character in key),
        },
    }
