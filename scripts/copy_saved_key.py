"""Copy the locally saved key for pasting into a hosting secret field on macOS."""
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values

if sys.platform != "darwin":
    raise SystemExit("This clipboard helper is for macOS.")

path = Path(__file__).resolve().parents[1] / ".env"
key = (dotenv_values(path).get("NEBIUS_API_KEY") or "").strip()
if not key or any(character.isspace() for character in key):
    raise SystemExit("No plain key is saved in this project's .env file.")

subprocess.run(["pbcopy"], input=key, text=True, check=True)
print("Copied the saved Nebius key. Paste it into the host's NEBIUS_API_KEY secret field.")
