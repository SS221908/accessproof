"""Real Chromium integration checks; no provider calls or fake browser results."""

from __future__ import annotations

import asyncio
import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import zipfile

import pytest

from backend.model import OfflinePlanner
from backend import runner


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def fixture_server():
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            requests.append(path)
            if path in {"/demo/working", "/demo/unreachable", "/demo/trap", "/demo/variant"}:
                body = (ROOT / "static" / "demo.html").read_bytes()
                content_type = "text/html"
            elif path in {"/static/demo.css", "/static/demo.js"}:
                body = (ROOT / path.lstrip("/")).read_bytes()
                content_type = "text/css" if path.endswith(".css") else "application/javascript"
            elif path == "/demo/hidden-success":
                body = b'<h1>Example</h1><p data-ap-success="true" hidden>Not actually visible</p>'
                content_type = "text/html"
            elif path == "/demo/empty-success":
                body = b'<h1>Example</h1><p data-ap-success="true"> </p>'
                content_type = "text/html"
            elif path.startswith("/demo/select-"):
                variant = path.removeprefix("/demo/select-")
                options = {
                    "reordered": '<option value="">Choose a topic</option><option>Linear algebra</option><option>Calculus</option><option value="cs">Computer science</option>',
                    "nondefault": '<option selected>Linear algebra</option><option value="cs">Computer science</option><option>Calculus</option>',
                    "disabled": '<option value="" selected>Choose a topic</option><optgroup label="Unavailable" disabled><option>Calculus</option></optgroup><option value="cs">Computer science</option>',
                    "hidden": '<option value="" selected>Choose a topic</option><option hidden>Calculus</option><option>Linear algebra</option>',
                    "multiple": '<option>Calculus</option><option>Linear algebra</option>',
                    "unicode": '<option value="">Choose a topic</option><option>Cálculo</option>',
                    "nochange": '<option value="">Choose a topic</option><option>Calculus</option>',
                }.get(variant)
                if options is None:
                    self.send_error(404)
                    return
                multiple = " multiple" if variant == "multiple" else ""
                block_typeahead = '''topic.addEventListener("keydown", event => {
                    if (event.key.length === 1) event.preventDefault();
                });''' if variant == "nochange" else ""
                body = f'''<!doctype html><label for="topic">Topic</label>
                  <select id="topic"{multiple}>{options}</select>
                  <button id="register">Reserve</button>
                  <p id="confirmation" data-ap-success="false" hidden></p>
                  <script>
                    const topic = document.getElementById("topic");
                    {block_typeahead}
                    document.getElementById("register").addEventListener("click", () => {{
                      if (!topic.value) return;
                      const confirmation = document.getElementById("confirmation");
                      confirmation.textContent = "Reserved: " + topic.selectedOptions[0].label;
                      confirmation.hidden = false;
                      confirmation.dataset.apSuccess = "true";
                    }});
                  </script>'''.encode()
                content_type = "text/html"
            elif path == "/outside-fixture":
                body = b'<h1>Untrusted marker</h1><p data-ap-success="true">Do not accept this</p>'
                content_type = "text/html"
            elif path == "/demo/network":
                port = self.server.server_port
                body = (f'<h1>Network policy test</h1><script>fetch("http://localhost:{port}/external-probe").catch(() => {{}});</script>'
                        f'<iframe src="http://localhost:{port}/external-frame"></iframe>').encode()
                content_type = "text/html"
            elif path == "/demo/accessible-modal":
                body = (ROOT / "static" / "demo.html").read_bytes().replace(b"</body>", b'''<script>
                  window.addEventListener("DOMContentLoaded", () => {
                    const layer = document.getElementById("notice-layer");
                    const close = document.getElementById("dismiss-notice");
                    close.tabIndex = 0;
                    const stop = () => { layer.hidden = true; document.getElementById("name").focus(); };
                    close.addEventListener("keydown", event => { if (event.key === "Enter") stop(); });
                    document.getElementById("notice").addEventListener("keydown", event => {
                      if (event.key === "Escape") { event.preventDefault(); stop(); }
                      if (event.key === "Tab") {
                        event.preventDefault();
                        const controls = [document.getElementById("notice-details"), document.getElementById("notice-access"), close];
                        controls[(controls.indexOf(document.activeElement) + (event.shiftKey ? 2 : 1)) % 3].focus();
                      }
                    });
                    layer.hidden = false;
                    document.getElementById("notice-details").focus();
                  });
                </script></body>''')
                content_type = "text/html"
            elif path == "/demo/browser-guard":
                body = b'''<h1>Browser guard test</h1>
                  <button id="popup" onclick="window.open('/demo/empty-success', '_blank')">Open a popup</button>
                  <a id="download" href="/download" download="example.txt">Download an example</a>'''
                content_type = "text/html"
            elif path == "/download":
                body = b"An example file that must not be saved by the runner."
                content_type = "application/octet-stream"
            elif path in {"/external-probe", "/external-frame"}:
                body = b"External request should never reach this server."
                content_type = "text/plain"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            if path == "/download":
                self.send_header("Content-Disposition", 'attachment; filename="example.txt"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", requests
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def execute(origin, path, artifacts, *, decide=None, max_steps=24, expected_text=None):
    events = []
    observations = []
    planner = OfflinePlanner()

    async def plan(observation):
        observations.append(observation)
        return await (decide(observation) if decide else planner.decide(observation))

    async def emit(event):
        events.append(event)

    result = asyncio.run(runner.run_browser(
        run_id="integration-test", url=origin + path,
        goal="Reserve a Calculus tutoring appointment for Alex Rivera, alex@example.com.",
        artifacts_dir=artifacts, decide=plan, emit=emit,
        allowed_origin=origin, max_steps=max_steps, expected_text=expected_text,
    ))
    return result, events, observations


@pytest.mark.parametrize("scenario, expected", [
    ("working", "passed"), ("variant", "passed"),
    ("unreachable", "blocked"), ("trap", "blocked"),
])
def test_real_keyboard_tasks(fixture_server, tmp_path, scenario, expected):
    origin, _ = fixture_server
    artifacts = tmp_path / scenario
    result, events, observations = execute(origin, "/demo/" + scenario, artifacts)
    assert result["status"] == expected, result
    assert events[0]["action"] == "observe"
    assert [event["seq"] for event in events] == list(range(len(events)))
    assert result["report"]["steps_count"] == sum(event["action"] in {"press", "type"} for event in events)
    assert all((artifacts / event["screenshot"]).is_file() for event in events)
    assert zipfile.is_zipfile(artifacts / "trace.zip")
    assert (artifacts / "reproducer.py").is_file()
    assert all({"goal", "controls", "active_element", "history", "success", "scenario", "status", "messages", "url"} <= observation.keys() for observation in observations)
    assert all(observation["scenario"] == "" for observation in observations)

    if expected == "passed":
        assert "Appointment reserved" in result["report"]["success_text"]
        assert any(event["action"] == "type" and event["focused_before"] == "email" for event in events)
        assert any(event["key"] == "Enter" and event["focused_before"] == "register" for event in events)
    else:
        assert result["report"]["evidence"]
        assert not result["report"]["success_text"]
    if scenario == "unreachable":
        assert "omitted from sequential keyboard navigation" in result["report"]["evidence"][0]
        assert all(event["focused_after"] != "register" for event in events)
    if scenario == "trap":
        assert any(event["key"] == "Escape" for event in events)
        assert "dialog notice" in result["report"]["evidence"][0]
        assert all(event["focused_after"] in {"notice-details", "notice-access"} for event in events)


def test_exported_reproducer_runs_independently(fixture_server, tmp_path):
    origin, _ = fixture_server
    result, _, _ = execute(origin, "/demo/working", tmp_path)
    assert result["status"] == "passed", result
    replay = subprocess.run(
        [sys.executable, str(tmp_path / "reproducer.py")],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env=dict(os.environ, ACCESSPROOF_TEST_URL=origin + "/demo/working?replay=1"),
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert "independent task confirmation" in replay.stdout


@pytest.mark.parametrize("verdict", ["blocked", "done"])
def test_planner_verdict_is_not_evidence(fixture_server, tmp_path, verdict):
    origin, _ = fixture_server

    async def declare(_observation):
        return {"action": verdict, "reason": "An unsupported planner assertion."}

    result, events, _ = execute(origin, "/demo/working", tmp_path, decide=declare)
    assert result["status"] == "inconclusive", result
    assert result["report"]["steps_count"] == 0
    assert len(events) == 2


@pytest.mark.parametrize("path", ["/demo/hidden-success", "/demo/empty-success", "/outside-fixture"])
def test_success_requires_visible_text_in_owned_fixture(fixture_server, tmp_path, path):
    origin, _ = fixture_server

    async def declare(_observation):
        return {"action": "done", "reason": "Attempt to accept an insufficient marker."}

    result, _, observations = execute(origin, path, tmp_path, decide=declare)
    assert result["status"] == "inconclusive", result
    assert observations[0]["success"] is False


def test_unapproved_key_is_never_executed(fixture_server, tmp_path):
    origin, _ = fixture_server

    async def unsafe(_observation):
        return {"action": "press", "key": "Control+L", "reason": "Not an allowed task action."}

    result, events, _ = execute(origin, "/demo/working", tmp_path, decide=unsafe)
    assert result["status"] == "error", result
    assert "permitted keyboard actions" in result["error"]
    assert result["report"]["steps_count"] == 0
    assert [event["action"] for event in events] == ["observe"]


def test_timeout_is_inconclusive(fixture_server, tmp_path, monkeypatch):
    origin, _ = fixture_server
    monkeypatch.setattr(runner, "DECISION_TIMEOUT_SECONDS", 0.01)

    async def slow(_observation):
        await asyncio.sleep(1)
        return {"action": "blocked", "reason": "Late answer."}

    result, _, _ = execute(origin, "/demo/unreachable", tmp_path, decide=slow)
    assert result["status"] == "inconclusive", result
    assert "timed out" in result["report"]["summary"]
    assert zipfile.is_zipfile(tmp_path / "trace.zip")


def test_exact_origin_blocks_external_subrequests(fixture_server, tmp_path):
    origin, requests = fixture_server
    before = len(requests)

    async def stop(_observation):
        return {"action": "done", "reason": "Network guard observation only."}

    result, _, _ = execute(origin, "/demo/network", tmp_path, decide=stop)
    assert result["status"] == "inconclusive", result
    assert result["report"]["blocked_requests"]
    assert "/external-probe" not in requests[before:]
    assert "/external-frame" not in requests[before:]


def test_outside_start_url_rejected_before_browser(fixture_server, tmp_path):
    origin, _ = fixture_server
    events = []

    async def should_not_run(_observation):
        raise AssertionError("An external start URL must be rejected first.")

    async def emit(event):
        events.append(event)

    result = asyncio.run(runner.run_browser(
        run_id="external-start", url=origin.replace("127.0.0.1", "localhost") + "/demo/working",
        goal="Do not leave the configured origin.", artifacts_dir=tmp_path,
        decide=should_not_run, emit=emit, allowed_origin=origin,
    ))
    assert result["status"] == "error"
    assert "outside the configured allowed origin" in result["error"]
    assert not events


def test_dismissible_modal_is_not_misclassified_as_a_trap(fixture_server, tmp_path):
    origin, _ = fixture_server
    result, events, _ = execute(origin, "/demo/accessible-modal", tmp_path)
    assert result["status"] == "passed", result
    assert any(event["key"] == "Escape" for event in events)
    assert any(event["focused_after"] == "name" for event in events)


def test_popups_closed_and_downloads_canceled(fixture_server, tmp_path):
    origin, _ = fixture_server
    keys = iter(["Tab", "Enter", "Tab", "Enter"])

    async def decisions(_observation):
        key = next(keys, None)
        return ({"action": "press", "key": key, "reason": "Exercise a guarded browser capability."}
                if key else {"action": "done", "reason": "Browser guard test complete."})

    result, _, _ = execute(origin, "/demo/browser-guard", tmp_path, decide=decisions)
    assert result["status"] == "inconclusive", result
    assert result["report"]["closed_popups"]
    assert result["report"]["canceled_downloads"] == ["example.txt"]
    assert not (tmp_path / "example.txt").exists()


def test_confirmation_must_match_requested_details(fixture_server, tmp_path):
    origin, _ = fixture_server
    planned = iter([
        {"action": "press", "key": "Tab"},
        {"action": "type", "text": "Morgan Lee"},
        {"action": "press", "key": "Tab"},
        {"action": "type", "text": "alex@example.com"},
        {"action": "press", "key": "Tab"},
        {"action": "press", "key": "ArrowDown"},
        {"action": "press", "key": "Tab"},
        {"action": "press", "key": "Enter"},
    ])

    async def wrong_details(_observation):
        return dict(next(planned, {"action": "done"}), reason="Exercise the independent confirmation check.")

    result, _, observations = execute(
        origin, "/demo/working", tmp_path, decide=wrong_details,
        expected_text="Alex Rivera · alex@example.com · Calculus",
    )
    assert result["status"] == "inconclusive", result
    assert "Morgan Lee" in result["report"]["success_text"]
    assert result["report"]["expected_text_matched"] is False
    assert "did not match" in result["report"]["summary"]
    assert observations[-1]["success_marker_visible"] is True
    assert observations[-1]["success"] is False
    replay = subprocess.run(
        [sys.executable, str(tmp_path / "reproducer.py")],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env=dict(os.environ, ACCESSPROOF_TEST_URL=origin + "/demo/working"),
    )
    assert replay.returncode != 0
    assert "Confirmation did not match the expected task details" in replay.stderr


def test_matching_confirmation_ignores_case_and_extra_whitespace(fixture_server, tmp_path):
    origin, _ = fixture_server
    result, _, _ = execute(
        origin, "/demo/working", tmp_path,
        expected_text="alex RIVERA  ·  ALEX@EXAMPLE.COM · Calculus",
    )
    assert result["status"] == "passed", result
    assert result["report"]["expected_text_matched"] is True


def keyboard_plan(actions):
    planned = iter(actions)

    async def decide(_observation):
        return dict(next(planned, {"action": "done"}), reason="Exercise observed keyboard selection.")

    return decide


def test_native_typeahead_records_values_latest_history_and_replays(fixture_server, tmp_path):
    origin, _ = fixture_server
    actions = [
        {"action": "press", "key": "Tab"},
        {"action": "type", "text": "Alex Rivera"},
        {"action": "press", "key": "Tab"},
        {"action": "type", "text": "alex@example.com"},
        {"action": "press", "key": "Tab"},
        {"action": "type", "text": "Calculus"},
        {"action": "press", "key": "Tab"},
        {"action": "press", "key": "Enter"},
    ]
    result, events, observations = execute(
        origin, "/demo/working", tmp_path, decide=keyboard_plan(actions),
        expected_text="Alex Rivera · alex@example.com · Calculus",
    )
    assert result["status"] == "passed", result
    select_event = next(event for event in events if event["action"] == "type" and event["focused_tag"] == "select")
    assert select_event["input_kind"] == "select"
    assert select_event["value_before"] == ""
    assert select_event["value_after"] == "Calculus"
    assert select_event["value_changed"] is True
    assert select_event["selected_label_before"] == "Choose a topic"
    assert select_event["selected_label_after"] == "Calculus"
    assert select_event["selected_index_after"] == 1
    assert select_event["selects_after"][0]["value"] == "Calculus"
    commit = next(event for event in events if event["key"] == "Tab" and event["focused_before"] == "topic")
    assert commit["value_after"] == "Calculus"  # same control, even after focus moved
    assert commit["focused_after"] == "register"

    for index, observation in enumerate(observations):
        assert len(observation["history"]) == index
        if index:
            assert observation["history"][-1]["seq"] == index
            assert observation["history"][-1]["focus_after"] == events[index]["focused_after"]
    after_type = observations[6]
    assert after_type["history"][-1]["action"] == "type"
    assert after_type["history"][-1]["input_kind"] == "select"
    assert after_type["history"][-1]["value_after"] == "Calculus"

    script = (tmp_path / "reproducer.py").read_text()
    exported = next(node.value for node in ast.parse(script).body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "ACTIONS" for target in node.targets))
    assert ast.literal_eval(exported) == actions
    replay = subprocess.run(
        [sys.executable, str(tmp_path / "reproducer.py")], cwd=tmp_path,
        capture_output=True, text=True, timeout=30, env=dict(os.environ),
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr


@pytest.mark.parametrize("variant", ["reordered", "nondefault", "disabled"])
def test_typeahead_uses_observed_label_with_reordered_or_disabled_options(fixture_server, tmp_path, variant):
    origin, _ = fixture_server
    actions = [
        {"action": "press", "key": "Tab"},
        {"action": "type", "text": "Computer science"},
        {"action": "press", "key": "Tab"},
        {"action": "press", "key": "Enter"},
    ]
    result, events, observations = execute(
        origin, "/demo/select-" + variant, tmp_path, decide=keyboard_plan(actions), expected_text="Computer science",
    )
    assert result["status"] == "passed", result
    selection = next(event for event in events if event["action"] == "type")
    assert selection["value_after"] == "cs"  # visible label differs from submitted value
    assert selection["selected_label_after"] == "Computer science"
    assert observations[1]["active_element"]["input_kind"] == "select"
    if variant == "disabled":
        disabled = next(option for option in observations[1]["active_element"]["options"] if option["label"] == "Calculus")
        assert disabled["disabled"] is True  # inherited from optgroup


@pytest.mark.parametrize("variant,text,error_fragment", [
    ("disabled", "Calculus", "enabled observed option label"),
    ("hidden", "Calculus", "enabled observed option label"),
    ("reordered", "Physics", "enabled observed option label"),
    ("multiple", "Calculus", "single-choice"),
    ("unicode", "Cálculo", "ASCII"),
])
def test_unsupported_or_unobserved_select_typing_is_not_executed(fixture_server, tmp_path, variant, text, error_fragment):
    origin, _ = fixture_server
    result, events, _ = execute(
        origin, "/demo/select-" + variant, tmp_path,
        decide=keyboard_plan([{"action": "press", "key": "Tab"}, {"action": "type", "text": text}]),
    )
    assert result["status"] == "error", result
    assert error_fragment in result["error"]
    assert all(event["action"] != "type" for event in events)
    assert result["report"]["steps_count"] == 1


def test_typeahead_without_browser_value_change_stays_inconclusive(fixture_server, tmp_path):
    origin, _ = fixture_server
    result, events, _ = execute(
        origin, "/demo/select-nochange", tmp_path,
        decide=keyboard_plan([
            {"action": "press", "key": "Tab"},
            {"action": "type", "text": "Calculus"},
            {"action": "press", "key": "Tab"},
            {"action": "press", "key": "Enter"},
        ]), expected_text="Calculus",
    )
    assert result["status"] == "inconclusive", result
    selection = next(event for event in events if event["action"] == "type")
    assert selection["value_before"] == selection["value_after"] == ""
    assert selection["value_changed"] is False
    assert not result["report"]["success_text"]
