"""Check the local browser's sample keyboard workflow without any AI requests."""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.model import OfflinePlanner
from backend.runner import run_browser


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        routes = {
            "/demo/working": ("static/demo.html", "text/html"),
            "/static/demo.css": ("static/demo.css", "text/css"),
            "/static/demo.js": ("static/demo.js", "text/javascript"),
        }
        resource = routes.get(urlsplit(self.path).path)
        if resource is None:
            self.send_error(404)
            return
        relative, content_type = resource
        body = (ROOT / relative).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


async def check(origin: str, artifacts: Path):
    planner = OfflinePlanner()

    async def emit(_event):
        pass

    return await run_browser(
        run_id="keyboard-check", url=origin + "/demo/working",
        goal="Book a tutoring appointment for Alex Rivera, alex@example.com, topic Calculus.",
        expected_text="Alex Rivera · alex@example.com · Calculus",
        artifacts_dir=artifacts, decide=planner.decide, emit=emit,
        allowed_origin=origin, max_steps=24,
    )


def main() -> int:
    print("Checking the sample form with a real browser. No AI requests are made.", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="accessproof-keyboard-check-") as directory:
            result = asyncio.run(check(f"http://127.0.0.1:{server.server_port}", Path(directory)))
            if result["status"] == "passed":
                print("PASS: the keyboard completed the sample booking with the expected details.")
                print("Browser:", result["report"]["browser_version"])
                return 0
            print("Keyboard check did not complete:", result["status"])
            print(result.get("error") or result["report"]["summary"])
            events = json.loads((Path(directory) / "events.json").read_text())
            for event in events[-5:]:
                print(json.dumps({key: event.get(key) for key in (
                    "action", "key", "focused_before", "focused_after",
                    "value_before", "value_after", "selected_label_after",
                )}, ensure_ascii=False))
            return 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
