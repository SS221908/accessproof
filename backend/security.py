"""Small access controls for a shared, hosted demonstration."""
import base64
import binascii
import secrets
from urllib.parse import urlsplit, urlunsplit


def canonical_origin(value: str) -> str:
    """Accept an origin only, never credentials, a path, or URL parameters."""
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or any(character.isspace() for character in value)
        ):
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        hostname = parsed.hostname.lower()
        host = f"[{hostname}]" if ":" in hostname else hostname
        if port is not None and port != (443 if parsed.scheme == "https" else 80):
            host += f":{port}"
        return urlunsplit((parsed.scheme, host, "", "", ""))
    except ValueError:
        raise ValueError("The public origin must be an HTTP(S) origin without credentials, a path, query, or fragment.") from None


def public_origin(value: str) -> str:
    if not value.strip():
        return ""
    origin = canonical_origin(value)
    parsed = urlsplit(origin)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("A remote public origin must use HTTPS. HTTP is supported only for strict loopback testing.")
    return origin


def valid_demo_credentials(header: str | None, password: str) -> bool:
    if not header or len(header) > 2048:
        return False
    scheme, separator, encoded = header.partition(" ")
    if not separator or scheme.lower() != "basic":
        return False
    try:
        raw = base64.b64decode(encoded, validate=True)
        username, separator, supplied = raw.partition(b":")
    except (binascii.Error, ValueError, UnicodeError):
        return False
    if not separator:
        return False
    # Compare both fields, using bytes to support UTF-8 secrets safely.
    correct_username = secrets.compare_digest(username, b"judge")
    correct_password = secrets.compare_digest(supplied, password.encode("utf-8"))
    return correct_username and correct_password
