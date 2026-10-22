from datetime import datetime, timezone
from dataclasses import replace
import base64
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from backend.config import ROOT, Settings
from backend.main import create_app
from backend.store import RunStore


DEMO_PASSWORD = "unit-test-demo-access-code-123456789"


def demo_auth_headers():
    encoded = base64.b64encode(("judge:" + DEMO_PASSWORD).encode()).decode()
    return {"Authorization": "Basic " + encoded}


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


def test_hosted_auth_blocks_private_routes_before_any_provider_call(tmp_path, monkeypatch):
    import backend.model
    import backend.runner

    calls = []

    def forbidden_planner(*_args, **_kwargs):
        calls.append("planner")
        raise AssertionError("Unauthorized callers must not construct a model client")

    async def forbidden_runner(**_kwargs):
        calls.append("browser")
        raise AssertionError("Unauthorized callers must not start a browser")

    monkeypatch.setattr(backend.model, "LivePlanner", forbidden_planner)
    monkeypatch.setattr(backend.runner, "run_browser", forbidden_runner)
    config = replace(settings(tmp_path, "test-private-provider-key"), demo_password=DEMO_PASSWORD)
    with TestClient(create_app(config)) as client:
        for path in (
            "/", "/api/config", "/api/runs", "/api/runs/" + "a" * 32,
            "/api/runs/" + "a" * 32 + "/report", "/api/runs/" + "a" * 32 + "/reproducer",
            "/api/runs/" + "a" * 32 + "/trace", "/artifacts/" + "a" * 32 + "/000.png",
            "/docs", "/openapi.json", "/static/index.html", "/static/app.js",
        ):
            response = client.get(path)
            assert response.status_code == 401, path
            assert response.headers["www-authenticate"].startswith("Basic ")
            assert DEMO_PASSWORD not in response.text
            assert config.api_key not in response.text
        assert client.head("/api/runs").status_code == 401
        assert client.options("/api/runs").status_code == 401
        response = client.post("/api/runs", json={"scenario": "working", "goal": "Book a tutoring appointment", "mode": "live"})
        assert response.status_code == 401
        assert not calls
        assert client.app.state.store.list() == []
        assert not client.app.state.jobs


def test_public_worker_resources_and_health_need_no_credentials(tmp_path):
    config = replace(settings(tmp_path), demo_password=DEMO_PASSWORD)
    with TestClient(create_app(config)) as client:
        for path in ("/health", "/demo/working", "/demo/unreachable", "/demo/trap", "/demo/variant", "/static/demo.css", "/static/demo.js"):
            assert client.get(path).status_code == 200, path
            assert client.head(path).status_code == 200, path
        assert client.get("/demo/unknown").status_code == 401
        assert client.post("/demo/working").status_code == 401


@pytest.mark.parametrize("authorization", [
    "", "Bearer wrong-token", "Basic not-base64!", "Basic anVkZ2U=", "Basic /w==", "Basic " + "A" * 2050,
])
def test_malformed_demo_auth_is_rejected_safely(tmp_path, authorization):
    config = replace(settings(tmp_path), demo_password=DEMO_PASSWORD)
    with TestClient(create_app(config)) as client:
        assert client.get("/api/config", headers={"Authorization": authorization}).status_code == 401
        assert client.get("/api/config", auth=("wrong-user", DEMO_PASSWORD)).status_code == 401
        assert client.get("/api/config", auth=("judge", "wrong-password")).status_code == 401
        assert client.get("/api/config", auth=("judge", DEMO_PASSWORD)).status_code == 200


def test_authenticated_hosted_run_uses_configured_origin_and_excludes_secrets(tmp_path, monkeypatch):
    import backend.model
    import backend.runner

    calls = []

    class FakePlanner:
        def __init__(self, **_kwargs):
            self.calls_made = 0
            self.total_usage = {}

        async def decide(self, _observation):
            self.calls_made += 1
            return {"action": "press", "key": "Tab", "reason": "Test provider call"}

        async def aclose(self):
            pass

    async def fake_runner(**kwargs):
        calls.append({"url": kwargs["url"], "allowed_origin": kwargs["allowed_origin"]})
        await kwargs["decide"]({})
        return {"status": "passed", "report": {"summary": "Test-only confirmation", "steps_count": 0}}

    monkeypatch.setattr(backend.model, "LivePlanner", FakePlanner)
    monkeypatch.setattr(backend.runner, "run_browser", fake_runner)
    config = replace(
        settings(tmp_path, "synthetic-private-provider-key"),
        demo_password=DEMO_PASSWORD, require_demo_auth=True,
        public_origin="https://accessproof.example:443/",
    )
    with TestClient(create_app(config), base_url="http://127.0.0.1", headers=demo_auth_headers()) as client:
        headers = {
            "Origin": "https://accessproof.example",
            "Host": "127.0.0.1:8000",
            "X-Forwarded-Host": "attacker.example",
            "X-Forwarded-Proto": "http",
        }
        created = client.post("/api/runs", json={"scenario": "working", "goal": "Book a tutoring appointment", "mode": "live"}, headers=headers)
        assert created.status_code == 201
        result = terminal_result(client, created.json()["id"])
        assert result["status"] == "passed"
        assert result["model_calls"] == 1
        assert calls == [{"url": "https://accessproof.example/demo/working", "allowed_origin": "https://accessproof.example"}]
        for path in ("/api/config", "/health", "/api/runs", f"/api/runs/{result['id']}/report"):
            response = client.get(path)
            assert response.status_code == 200
            assert DEMO_PASSWORD not in response.text
            assert config.api_key not in response.text
        assert client.get("/", headers={"Host": "accessproof.example"}).status_code == 200
        assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400


def test_authenticated_hosted_cross_origin_submission_creates_no_run(tmp_path):
    config = replace(settings(tmp_path, "test-key"), demo_password=DEMO_PASSWORD, require_demo_auth=True, public_origin="https://accessproof.example")
    with TestClient(create_app(config), headers=demo_auth_headers()) as client:
        for origin in ("https://attacker.example", "http://accessproof.example", "https://accessproof.example/other", "null"):
            response = client.post("/api/runs", json={"scenario": "working", "goal": "Book a tutoring appointment", "mode": "live"}, headers={"Origin": origin})
            assert response.status_code == 403
        assert client.app.state.store.list() == []
        assert not client.app.state.jobs


@pytest.mark.parametrize("password", ["", "short", " " * 20])
def test_required_demo_auth_rejects_missing_or_short_access_code(tmp_path, password):
    config = replace(settings(tmp_path), demo_password=password, require_demo_auth=True, public_origin="https://accessproof.example")
    with pytest.raises(ValueError, match="ACCESSPROOF_DEMO_PASSWORD"):
        create_app(config)


def test_required_demo_auth_requires_explicit_public_origin(tmp_path):
    config = replace(settings(tmp_path), demo_password=DEMO_PASSWORD, require_demo_auth=True)
    with pytest.raises(ValueError, match="ACCESSPROOF_PUBLIC_ORIGIN"):
        create_app(config)


@pytest.mark.parametrize("origin", [
    "https://user:secret@accessproof.example", "https://accessproof.example/other",
    "https://accessproof.example?key=secret", "https://accessproof.example#fragment",
    "https://accessproof.example:99999", "https://accessproof.example:bad", "https://[broken",
    "http://accessproof.example", "http://localhost.attacker.example", "http://127.0.0.2",
    "https://accessproof.example\n.evil.example", "ftp://accessproof.example", "https://*.example",
])
def test_invalid_or_insecure_public_origin_fails_before_serving(tmp_path, origin):
    config = replace(settings(tmp_path), demo_password=DEMO_PASSWORD, require_demo_auth=True, public_origin=origin)
    with pytest.raises(ValueError):
        create_app(config)


@pytest.mark.parametrize("origin", ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"])
def test_required_auth_allows_http_only_for_strict_loopback_testing(tmp_path, origin):
    config = replace(settings(tmp_path), demo_password=DEMO_PASSWORD, require_demo_auth=True, public_origin=origin)
    with TestClient(create_app(config), base_url=origin) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 401
        assert client.get("/", auth=("judge", DEMO_PASSWORD)).status_code == 200


def test_get_settings_reads_render_defaults_and_explicit_origin(monkeypatch):
    import backend.config as config

    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: False)
    monkeypatch.delenv("ACCESSPROOF_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("ACCESSPROOF_REQUIRE_DEMO_AUTH", "false")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://accessproof.onrender.com")
    monkeypatch.setenv("ACCESSPROOF_DEMO_PASSWORD", DEMO_PASSWORD)
    resolved = config.get_settings()
    assert resolved.require_demo_auth is True
    assert resolved.demo_password == DEMO_PASSWORD
    assert resolved.public_origin == "https://accessproof.onrender.com"
    monkeypatch.setenv("ACCESSPROOF_PUBLIC_ORIGIN", "https://custom.example")
    assert config.get_settings().public_origin == "https://custom.example"


def test_wildcard_host_allowlist_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("ACCESSPROOF_ALLOWED_HOSTS", "*")
    with pytest.raises(ValueError, match="exact hostnames"):
        create_app(settings(tmp_path))
