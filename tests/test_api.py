from datetime import datetime, timezone
from pathlib import Path
import time

from fastapi.testclient import TestClient

from backend.config import ROOT, Settings
from backend.main import create_app
from backend.store import RunStore


def settings(tmp_path, key=""):
    return Settings(ROOT, tmp_path / "data", tmp_path / "artifacts", key, "nvidia/test-model", "https://api.tokenfactory.nebius.com/v1/", 12)


def terminal_result(client, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        document = client.get(f"/api/runs/{run_id}").json()
        if document["status"] not in {"queued", "running"}:
            return document
        time.sleep(0.01)
    raise AssertionError("Run failed to reach a terminal status")


def test_missing_live_key_and_invalid_input(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get("/health").json()["live_ready"] is False
        response = client.post("/api/runs", json={"scenario": "working", "goal": "Book a tutoring appointment", "mode": "live"})
        assert response.status_code == 503
        assert client.post("/api/runs", json={"scenario": "external", "goal": "Book a tutoring appointment", "mode": "offline"}).status_code == 422
        assert client.get("/api/runs/not-a-run").status_code == 404
        assert client.get("/demo/unknown").status_code == 404


def test_run_persistence_exports_and_no_key_disclosure(tmp_path, monkeypatch):
    import backend.runner

    async def fake_runner(**kwargs):
        directory: Path = kwargs["artifacts_dir"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "reproducer.py").write_text("# test-only browser artifact\n")
        (directory / "trace.zip").write_bytes(b"test-only artifact")
        await kwargs["emit"]({"seq": 0, "action": "observe", "reason": "Initial page", "focused_before": {}, "focused_after": {}, "screenshot": "000.png", "timestamp": "2026-10-21T00:00:00Z"})
        return {"status": "passed", "report": {"summary": "Observed booking confirmation", "evidence": ["Confirmation was visible"], "steps_count": 1, "success_text": "Appointment reserved"}}

    monkeypatch.setattr(backend.runner, "run_browser", fake_runner)
    private_key = "synthetic-private-api-key-for-unit-test"
    with TestClient(create_app(settings(tmp_path, private_key))) as client:
        assert private_key not in client.get("/api/config").text
        assert private_key not in client.get("/health").text
        created = client.post("/api/runs", json={"scenario": "working", "goal": "Book a tutoring appointment", "mode": "offline"})
        assert created.status_code == 201
        run_id = created.json()["id"]
        document = terminal_result(client, run_id)
        assert document["status"] == "passed"
        assert document["mode"] == "offline"
        assert "no AI calls" in document["model"]
        assert len(document["steps"]) == 1
        report = client.get(f"/api/runs/{run_id}/report")
        assert private_key not in report.text
        assert report.json()["report"]["success_text"] == "Appointment reserved"
        assert client.get(f"/api/runs/{run_id}/reproducer").status_code == 200
        assert client.get(f"/api/runs/{run_id}/trace").status_code == 200
        history = client.get("/api/runs").json()
        assert history[0]["id"] == run_id
        assert history[0]["steps_count"] == 1
        assert "steps" not in history[0]
    store = RunStore(tmp_path / "data" / "accessproof.sqlite3")
    assert store.get(run_id)["status"] == "passed"


def test_reject_cross_origin_run_submission(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/api/runs", json={"scenario": "working", "goal": "Book a tutoring appointment", "mode": "offline"}, headers={"Origin": "https://another-site.example"})
        assert response.status_code == 403


def test_interrupted_run_recovery(tmp_path):
    store = RunStore(tmp_path / "data" / "accessproof.sqlite3")
    timestamp = datetime.now(timezone.utc).isoformat()
    store.put({"id": "a" * 32, "created_at": timestamp, "updated_at": timestamp, "status": "running"})
    with TestClient(create_app(settings(tmp_path))) as client:
        document = client.get("/api/runs/" + "a" * 32).json()
        assert document["status"] == "error"
        assert "server stopped" in document["error"]
