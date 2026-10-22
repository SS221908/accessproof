"""Small durable run store. Credentials never enter the run document."""
import json
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Callable


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL)")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def put(self, document: dict) -> dict:
        with self.lock, self._connect() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?)", (document["id"], document["created_at"], json.dumps(document)))
        return document

    def get(self, run_id: str) -> dict | None:
        with self.lock, self._connect() as db:
            row = db.execute("SELECT document FROM runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, run_id: str, change: Callable[[dict], None]) -> dict:
        with self.lock:
            document = self.get(run_id)
            if document is None:
                raise KeyError(run_id)
            change(document)
            document["updated_at"] = now()
            return self.put(document)

    def list(self, limit: int = 30) -> list[dict]:
        with self.lock, self._connect() as db:
            rows = db.execute("SELECT document FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def recover(self) -> None:
        for document in self.list(1000):
            if document["status"] in {"queued", "running"}:
                document.update(status="error", error="The server stopped before this run finished.", updated_at=now())
                self.put(document)
