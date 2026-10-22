"""Start one application worker locally or in the hosted container."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))

if __name__ == "__main__":
    import uvicorn
    raw_port = os.getenv("PORT", "8000")
    if not raw_port.isdecimal() or not 1 <= int(raw_port) <= 65535:
        raise SystemExit("PORT must be a number from 1 to 65535.")
    uvicorn.run(
        "backend.main:app",
        host=os.getenv("ACCESSPROOF_HOST", "127.0.0.1"),
        port=int(raw_port),
        workers=1,
        proxy_headers=False,
    )
