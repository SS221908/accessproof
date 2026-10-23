"""Verify and privately transfer a Nebius key to a hosting secret on macOS."""
from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

from dotenv import dotenv_values, set_key
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.credentials import api_key_format_valid, api_key_summary


BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
NEW_KEY_HINT = "Run python scripts/copy_saved_key.py --new to enter a fresh full key privately."


class KeyTransferError(Exception):
    """Contains only messages written here, never provider or credential text."""


def _error_type(error: Exception) -> str:
    name = type(error).__name__
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) else "Error"


def prepare_key(value: str | None) -> tuple[str, bool]:
    """Remove whitespace/Unicode formatting only; provider verification follows."""
    if not isinstance(value, str) or not value.strip():
        raise KeyTransferError("No key was entered or saved. " + NEW_KEY_HINT)
    original = value.strip()
    candidate = "".join(
        character for character in original
        if not character.isspace() and unicodedata.category(character) != "Cf"
    )
    if not api_key_format_valid(candidate):
        raise KeyTransferError("The key still contains unsupported characters. Nothing was saved or copied. " + NEW_KEY_HINT)
    return candidate, candidate != original


def verify_key(key: str) -> None:
    """Use the non-inference models endpoint; never display provider responses."""
    client = None
    try:
        client = OpenAI(api_key=key, base_url=BASE_URL, timeout=20.0, max_retries=0)
        client.models.list()
    except Exception as error:
        status = getattr(error, "status_code", None)
        detail = f"HTTP {status}" if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599 else _error_type(error)
        guidance = NEW_KEY_HINT if status in {401, 403} else "Check the connection or Nebius account, then retry this helper."
        raise KeyTransferError("Nebius key verification failed (" + detail + "). Nothing was saved or copied. " + guidance) from None
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def save_and_copy(path: Path, key: str) -> None:
    try:
        # Protect a newly created file before writing, as well as after dotenv's
        # atomic replacement. Existing model/hosting settings are preserved.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        saved, _, _ = set_key(path, "NEBIUS_API_KEY", key, quote_mode="always")
        if not saved:
            raise OSError("Unable to update the key setting")
        os.chmod(path, 0o600)
    except Exception as error:
        raise KeyTransferError("Could not finish saving the verified key (" + _error_type(error) + "). The clipboard was not changed.") from None
    try:
        subprocess.run(["pbcopy"], input=key, text=True, capture_output=True, check=True)
        copied = subprocess.run(["pbpaste"], text=True, capture_output=True, check=True).stdout
    except Exception as error:
        raise KeyTransferError("Your verified key was saved, but clipboard transfer failed (" + _error_type(error) + "). Do not paste into Render yet.") from None
    if copied != key:
        raise KeyTransferError("Your verified key was saved, but clipboard verification did not match. Do not paste into Render. Run this helper again.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", action="store_true", help="Enter a fresh full key in a hidden prompt instead of using .env.")
    arguments = parser.parse_args(argv)
    if sys.platform != "darwin":
        print("This private clipboard helper is for macOS.", file=sys.stderr)
        return 1
    path = ROOT / ".env"
    try:
        if arguments.new:
            value = getpass("Paste your FULL Nebius key now (hidden), then press Enter: ")
        else:
            try:
                value = dotenv_values(path, interpolate=False).get("NEBIUS_API_KEY")
            except Exception as error:
                raise KeyTransferError("Could not read the saved key (" + _error_type(error) + "). " + NEW_KEY_HINT) from None
        key, cleaned = prepare_key(value)
        verify_key(key)
        save_and_copy(path, key)
    except KeyTransferError as error:
        print(error, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Key entry cancelled. Nothing was copied.", file=sys.stderr)
        return 1
    if cleaned:
        print("Removed whitespace or invisible formatting before verification.")
    print("Nebius accepted the key. Saved privately and verified the clipboard copy.")
    print("Fingerprint: " + api_key_summary(key)["fingerprint"])
    print("Paste into Render's NEBIUS_API_KEY value without copying anything else first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
