"""Save a local Nebius key without putting it in source code or shell history."""
from getpass import getpass
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
if sys.platform == "darwin":
    input("Copy your Nebius key using its copy icon NOW. Return here and press Enter; do not paste: ")
    key = subprocess.run(["pbpaste"], text=True, capture_output=True, check=True).stdout.strip()
else:
    key = getpass("Paste your Nebius key (hidden): ").strip()

if not key or any(character.isspace() for character in key) or key.startswith((chr(34), chr(39), "[")):
    raise SystemExit("The copied value is not a plain API key. Use the Nebius copy icon and run again.")

path = root / ".env"
existing = path.read_text().splitlines() if path.exists() else []
lines = [line for line in existing if not line.startswith("NEBIUS_API_KEY=")]
lines.append("NEBIUS_API_KEY=" + key)
if not any(line.startswith("NEBIUS_MODEL=") for line in lines):
    lines.append("NEBIUS_MODEL=nvidia/Nemotron-3.5-Super-VL")
descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w") as output:
    output.write("\n".join(lines) + "\n")
os.chmod(path, 0o600)
print("Saved your key privately in the ignored .env file. Restart AccessProof to use it.")
