"""A bounded, keyboard-only Playwright runner for AccessProof's owned demos.

Model decisions propose actions; the browser independently measures the result.
An agent saying ``blocked`` is not sufficient evidence of an accessibility bug.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


ALLOWED_KEYS = frozenset({
    "Tab", "Shift+Tab", "Enter", "Space", "Escape", "ArrowDown", "ArrowUp",
    "ArrowLeft", "ArrowRight", "Home", "End", "ControlOrMeta+A", "Backspace",
})
DECISION_TIMEOUT_SECONDS = 45
RUN_TIMEOUT_SECONDS = 180
TYPING_DELAY_MS = 50


def _browser_executable() -> str | None:
    explicit = os.environ.get("ACCESSPROOF_BROWSER_EXECUTABLE")
    if explicit:
        return explicit
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(chrome) if sys.platform == "darwin" and chrome.is_file() else None

FOCUS_CSS = """
*:focus { outline: 3px solid #c7ff35 !important; outline-offset: 4px !important; }
html { scroll-behavior: auto !important; }
"""

# This reads visible UI and browser state only. WeakMap IDs do not mutate the UI
# or change tab order. Native IDs remain available to the planner and report.
OBSERVE_JS = r"""() => {
  const state = window.__accessProofObservation ||= { ids: new WeakMap(), next: 1 };
  const tidy = (s, limit=180) => String(s || '').replace(/\s+/g, ' ').trim().slice(0, limit);
  const visible = el => {
    if (!el || !el.isConnected || el.getClientRects().length === 0) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.visibility !== 'collapse';
  };
  const id = el => {
    if (!el) return null;
    if (el === document.body) return 'body';
    if (el === document.documentElement) return 'html';
    if (el.id) return el.id;
    if (!state.ids.has(el)) state.ids.set(el, 'ap-' + state.next++);
    return state.ids.get(el);
  };
  const name = el => {
    const labelledBy = (el.getAttribute('aria-labelledby') || '').split(/\s+/)
      .map(x => document.getElementById(x)).filter(Boolean)
      .map(x => x.textContent).join(' ');
    const labels = Array.from(el.labels || []).map(x => x.textContent).join(' ');
    return tidy(el.getAttribute('aria-label') || labelledBy || labels ||
      ((el.tagName === 'INPUT') ? el.getAttribute('placeholder') : el.innerText) ||
      el.getAttribute('title') || el.getAttribute('name'));
  };
  const role = el => {
    if (el.getAttribute('role')) return el.getAttribute('role');
    const tag = el.tagName.toLowerCase();
    if (tag === 'button' || (tag === 'input' && ['submit', 'button', 'reset'].includes(el.type))) return 'button';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea' || (tag === 'input' && !['checkbox','radio','range','hidden'].includes(el.type))) return 'textbox';
    if (tag === 'input') return el.type;
    return tag;
  };
  const describe = el => {
    if (!el) return null;
    const disabled = !!el.disabled || el.getAttribute('aria-disabled') === 'true';
    const dialog = el.closest('dialog[open], [role="dialog"][aria-modal="true"]');
    const description = {
      id: id(el), tag: el.tagName.toLowerCase(), role: role(el),
      type: el.getAttribute('type') || '', label: name(el), name: name(el),
      value: el.type === 'password' ? '[redacted]' : tidy(el.value, 160),
      focusable: el.tabIndex >= 0 && !disabled && !el.closest('[inert]'),
      disabled, tabindex: el.tabIndex, dialog_id: dialog ? id(dialog) : null, in_dialog: !!dialog,
      editable: !!el.isContentEditable || ['INPUT', 'TEXTAREA'].includes(el.tagName),
      input_kind: el.tagName === 'SELECT' ? 'select' :
        (el.isContentEditable || ['INPUT', 'TEXTAREA'].includes(el.tagName) ? 'text' : 'other'),
    };
    if (el.tagName === 'SELECT') {
      description.selected_index = el.selectedIndex;
      description.selected_label = el.selectedIndex >= 0 ? tidy(el.options[el.selectedIndex].label) : '';
      description.multiple = el.multiple;
      description.options = Array.from(el.options).slice(0, 14).map((o, index) => ({
        index, value: o.value, label: tidy(o.label), selected: o.selected,
        disabled: o.disabled || (o.parentElement.tagName === 'OPTGROUP' && o.parentElement.disabled),
        hidden: o.hidden || !!o.closest('optgroup[hidden]'),
      }));
    }
    return description;
  };
  const controls = Array.from(document.querySelectorAll(
    'input:not([type="hidden"]), select, textarea, button, a[href], [role="button"], ' +
    '[role="link"], [role="combobox"], [role="checkbox"], [role="radio"], ' +
    '[tabindex], [onclick], [contenteditable="true"], summary'
  )).filter(visible).slice(0, 70).map(describe);
  const messages = Array.from(document.querySelectorAll(
    '[role="status"], [role="alert"], [aria-live], [data-ap-status], #status, #confirmation, .error'
  )).filter(visible).map(el => tidy(el.innerText, 260)).filter(Boolean);
  const successTexts = Array.from(document.querySelectorAll('[data-ap-success="true"]'))
    .filter(visible).map(el => tidy(el.innerText, 400)).filter(Boolean);
  const dialogs = Array.from(document.querySelectorAll('dialog[open], [role="dialog"][aria-modal="true"]'))
    .filter(visible).map(el => ({ id: id(el), label: name(el), text: tidy(el.innerText, 320) }));
  for (const control of controls) control.background_to_modal = dialogs.length > 0 && !control.in_dialog;
  return {
    title: tidy(document.title), controls, active_element: describe(document.activeElement),
    success: successTexts.length > 0, success_text: successTexts.join(' ').slice(0, 600),
    messages: [...new Set(messages)].slice(0, 8), status: [...new Set(messages)].join(' ').slice(0, 700),
    dialogs, dialog_context: dialogs.length ? 'Visible modal: ' + dialogs.map(d => d.label || d.id).join('; ') +
      '. Background controls are still in the DOM; keyboard navigation may be confined to the modal.' : '',
  };
}"""


def _origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Only an HTTP(S) URL without embedded credentials is supported.")
    port = parts.port
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 80 if parts.scheme == "http" else 443
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parts.scheme}://{host}{suffix}"


def _public_url(url: str) -> str:
    """Do not save URL query strings from a rejected request in a report."""
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))[:240]
    except ValueError:
        return "[invalid URL]"


def _focus_id(observation: dict[str, Any]) -> str | None:
    return (observation.get("active_element") or {}).get("id")


def _barrier_evidence(observation: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    """Conservative evidence, independent of the model's reason or scenario name."""
    tabs = [a for a in actions if a.get("action") == "press" and a.get("key") in {"Tab", "Shift+Tab"}]
    if len(tabs) < 4:
        return []
    visited = {a.get("focused_after") for a in tabs} | {a.get("focused_before") for a in tabs}
    controls = observation.get("controls", [])
    focusable = [c for c in controls if c.get("focusable") and not c.get("disabled")]

    # A visible primary action implemented as a non-tabbable custom button,
    # skipped while the remaining form's tab stops were actually traversed.
    action_words = {"register", "submit", "book", "confirm", "reserve", "save", "send", "continue", "complete"}
    for control in controls:
        words = set(str(control.get("label", "")).lower().replace("-", " ").split())
        if (
            control.get("role") == "button" and not control.get("focusable")
            and not control.get("disabled") and words & action_words
            and control.get("id") not in visited
            and focusable and all(c["id"] in visited for c in focusable)
            and len(tabs) >= max(4, len(focusable) + 1)
        ):
            return [
                f'Visible action "{control.get("label") or control["id"]}" is omitted from sequential keyboard navigation (tabindex={control.get("tabindex")}).',
                f'{len(tabs)} observed Tab/Shift+Tab actions visited the other {len(focusable)} enabled tab stops but never focused {control["id"]}.',
                "This demonstrates a barrier in the tested keyboard task; it does not constitute a complete accessibility audit.",
            ]

    # A normal modal focus loop alone is not a failure. Require attempted exit
    # with Escape and activation of a visible close/dismiss control, plus a
    # repeated cycle while task controls remain outside the dialog.
    active_dialog = (observation.get("active_element") or {}).get("dialog_id")
    if not active_dialog or not any(d.get("id") == active_dialog for d in observation.get("dialogs", [])):
        return []
    inside = [c for c in focusable if c.get("dialog_id") == active_dialog]
    outside = [c for c in focusable if c.get("dialog_id") != active_dialog]
    close_ids = {
        c["id"] for c in inside
        if any(word in str(c.get("label", "")).lower() for word in ("close", "dismiss", "exit", "cancel"))
    }
    unreachable_close = [
        c for c in controls if c.get("dialog_id") == active_dialog and c.get("role") == "button"
        and not c.get("focusable") and not c.get("disabled")
        and any(word in str(c.get("label", "")).lower() for word in ("close", "dismiss", "exit", "cancel"))
    ]
    attempted_escape = any(a.get("key") == "Escape" for a in actions)
    attempted_close = any(a.get("key") in {"Enter", "Space"} and a.get("focused_before") in close_ids for a in actions)
    recent_tabs = tabs[-max(4, len(inside) * 2):]
    inside_ids = {c["id"] for c in inside}
    stayed_inside = len(recent_tabs) >= 4 and all(a.get("focused_after") in inside_ids for a in recent_tabs)
    if outside and inside and attempted_escape and (attempted_close or unreachable_close) and stayed_inside:
        return [
            f"Keyboard focus remained inside dialog {active_dialog} over {len(recent_tabs)} observed Tab/Shift+Tab actions.",
            ("Escape did not dismiss the dialog; its visible close/dismiss control is omitted from sequential tab order."
             if unreachable_close else "Escape and keyboard activation of a visible close/dismiss control did not release focus or dismiss the dialog."),
            f"{len(outside)} visible enabled task controls remained outside the dialog.",
        ]
    return []


def _validate_decision(decision: Any) -> dict[str, str]:
    if not isinstance(decision, dict):
        raise ValueError("The planner must return an action object.")
    action = decision.get("action")
    if action not in {"press", "type", "done", "blocked"}:
        raise ValueError("The planner requested an unsupported action.")
    result = {"action": action, "reason": str(decision.get("reason", ""))[:700]}
    if action == "press":
        key = decision.get("key")
        if key not in ALLOWED_KEYS:
            raise ValueError("The planner requested a key outside the permitted keyboard actions.")
        result["key"] = key
    if action == "type":
        value = decision.get("text")
        if not isinstance(value, str) or not value or len(value) > 500 or any(c in value for c in "\r\n\t"):
            raise ValueError("Typing requires 1–500 characters without keyboard control characters.")
        result["text"] = value
    return result


def _validate_typing_target(observation: dict[str, Any], text: str) -> None:
    """Bound native typeahead to one enabled, observed ASCII option label.

    Selection still happens through keyboard events, never a DOM value write or
    Playwright's select_option helper. Native popup behavior can vary by browser;
    the next observation, rather than this validation, determines its effect.
    """
    active = observation.get("active_element") or {}
    if active.get("tag") != "select":
        if not active.get("editable") or active.get("disabled"):
            raise ValueError("Typing requires a focused editable field or an enabled native select option.")
        return
    if active.get("disabled") or active.get("multiple"):
        raise ValueError("Keyboard typeahead supports only an enabled single-choice native select.")
    if not text.isascii() or any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ValueError("Native select typeahead requires an ASCII option label.")
    options = active.get("options") or []
    if not any(
        isinstance(option, dict) and option.get("label") == text
        and not option.get("disabled") and not option.get("hidden")
        for option in options
    ):
        raise ValueError("Native select typing must exactly match an enabled observed option label.")


def _select_states(observation: dict[str, Any]) -> list[dict[str, Any]]:
    fields = ("id", "value", "selected_index", "selected_label", "multiple")
    return [
        {key: control.get(key) for key in fields}
        for control in observation.get("controls", []) if control.get("tag") == "select"
    ]


def _write_reproducer(path: Path, url: str, actions: list[dict[str, Any]], expected_text: str | None = None) -> None:
    keyboard_actions = [
        {k: a[k] for k in ("action", "key", "text") if k in a and a[k] is not None}
        for a in actions if a.get("action") in {"press", "type"}
    ]
    template = '''"""Reproduce this keyboard task. Run: python reproducer.py

Optional: ACCESSPROOF_TEST_URL=http://127.0.0.1:8000/demo/working python reproducer.py
Install Playwright first: python -m pip install playwright; python -m playwright install chromium
A failed success assertion deliberately preserves an unsuccessful recorded task.
"""
import asyncio
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

DEFAULT_URL = __DEFAULT_URL__
ACTIONS = __ACTIONS__
EXPECTED_TEXT = __EXPECTED_TEXT__

def browser_executable():
    explicit = os.environ.get("ACCESSPROOF_BROWSER_EXECUTABLE")
    if explicit:
        return explicit
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(chrome) if sys.platform == "darwin" and chrome.is_file() else None

async def main():
    url = os.environ.get("ACCESSPROOF_TEST_URL", DEFAULT_URL)
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        raise ValueError("Use an HTTP(S) URL without embedded credentials.")
    def origin(value):
        p = urlsplit(value)
        return (p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80))
    allowed = origin(url)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, executable_path=browser_executable(),
        )
        context = await browser.new_context(service_workers="block", accept_downloads=False)
        async def route_request(route):
            if origin(route.request.url) != allowed:
                await route.abort("blockedbyclient")
            else:
                await route.continue_()
        await context.route("**/*", route_request)
        page = await context.new_page()
        async def close_popup(popup):
            await popup.close()
        page.on("popup", close_popup)
        async def cancel_download(download):
            await download.cancel()
        page.on("download", cancel_download)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            for action in ACTIONS:
                if action["action"] == "press":
                    await page.keyboard.press(action["key"])
                else:
                    await page.keyboard.type(action["text"], delay=__TYPING_DELAY_MS__)
                await page.wait_for_timeout(80)
            if not urlsplit(url).path.startswith("/demo/"):
                raise AssertionError("Success markers are trusted only for AccessProof owned /demo/ fixtures.")
            await page.wait_for_function("""() => [...document.querySelectorAll('[data-ap-success="true"]')].some(el => {
                const s = getComputedStyle(el);
                return el.getClientRects().length > 0 && s.visibility !== 'hidden' && s.display !== 'none' && el.innerText.trim().length > 0;
            })""", timeout=5000)
            observed = await page.evaluate("""() => [...document.querySelectorAll('[data-ap-success="true"]')]
              .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
              .map(el => el.innerText).join(' ')""")
            if EXPECTED_TEXT is not None:
                normalized = lambda value: " ".join(value.casefold().split())
                assert normalized(EXPECTED_TEXT) in normalized(observed), "Confirmation did not match the expected task details."
            print("PASS: independent task confirmation is visible.")
        finally:
            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
'''
    substitutions = {
        "__DEFAULT_URL__": repr(url), "__ACTIONS__": repr(keyboard_actions),
        "__EXPECTED_TEXT__": repr(expected_text),
        "__TYPING_DELAY_MS__": str(TYPING_DELAY_MS),
    }
    # Substitute in one pass: typed text containing a placeholder name remains
    # literal data rather than becoming part of a later template replacement.
    script = re.sub(r"__(?:DEFAULT_URL|ACTIONS|EXPECTED_TEXT|TYPING_DELAY_MS)__", lambda match: substitutions[match.group()], template)
    path.write_text(script, encoding="utf-8")


async def run_browser(
    *,
    run_id: str,
    url: str,
    goal: str,
    artifacts_dir: Path,
    decide: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    max_steps: int = 24,
    allowed_origin: str = "http://127.0.0.1:8000",
    expected_text: str | None = None,
) -> dict[str, Any]:
    """Run a task without click/fill/focus shortcuts; export evidence and replay.

    ``artifacts_dir`` is the directory for this run, not the parent of run IDs.
    An initial ``observe`` event has sequence zero; ``steps_count`` counts only
    executed keyboard actions, not observation or planner-stop events.
    """
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    actions: list[dict[str, Any]] = []
    emitted: list[dict[str, Any]] = []
    blocked_requests: list[str] = []
    canceled_downloads: list[str] = []
    closed_popups: list[str] = []
    policy_violations: list[str] = []
    last_observation: dict[str, Any] = {}
    result: dict[str, Any] = {"status": "inconclusive", "report": {}}
    browser = context = page = None
    browser_version: str | None = None
    trace_started = False
    error: str | None = None
    summary = "The run stopped without independent evidence of task completion."
    evidence: list[str] = []

    try:
        allowed_parts = urlsplit(allowed_origin)
        if allowed_parts.path not in {"", "/"} or allowed_parts.query or allowed_parts.fragment:
            raise ValueError("allowed_origin must contain an origin only, without a path, query, or fragment.")
        expected_origin = _origin(allowed_origin)
        if _origin(url) != expected_origin:
            raise ValueError("The start URL is outside the configured allowed origin.")
        if not 1 <= max_steps <= 100:
            raise ValueError("max_steps must be between 1 and 100.")
        if expected_text is not None and (not isinstance(expected_text, str) or not expected_text.strip()):
            raise ValueError("expected_text must be a nonempty string when provided.")
        trusted_fixture = urlsplit(url).path.startswith("/demo/")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, executable_path=_browser_executable(),
            )
            browser_version = browser.version
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900}, device_scale_factor=1,
                reduced_motion="reduce", service_workers="block", accept_downloads=False,
            )
            context.set_default_timeout(5000)
            context.set_default_navigation_timeout(10000)
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
            trace_started = True

            async def guard_request(route: Any) -> None:
                try:
                    permitted = _origin(route.request.url) == expected_origin
                except ValueError:
                    permitted = False
                if not permitted:
                    blocked_requests.append(_public_url(route.request.url))
                    await route.abort("blockedbyclient")
                else:
                    await route.continue_()

            await context.route("**/*", guard_request)
            # The MVP fixtures do not use WebSockets. Denying them entirely
            # avoids a transport that ordinary HTTP routing does not protect.
            if hasattr(context, "route_web_socket"):
                async def deny_websocket(socket: Any) -> None:
                    blocked_requests.append(_public_url(socket.url))
                    await socket.close()
                await context.route_web_socket("**/*", deny_websocket)

            page = await context.new_page()

            async def close_popup(popup: Any) -> None:
                closed_popups.append(_public_url(popup.url))
                await popup.close()

            async def cancel_download(download: Any) -> None:
                canceled_downloads.append(str(download.suggested_filename)[:160])
                await download.cancel()

            def note_navigation(frame: Any) -> None:
                if frame.url == "about:blank":
                    return
                try:
                    permitted = _origin(frame.url) == expected_origin
                except ValueError:
                    permitted = False
                if not permitted:
                    policy_violations.append(_public_url(frame.url))

            page.on("popup", close_popup)
            page.on("download", cancel_download)
            page.on("framenavigated", note_navigation)

            def action_history() -> list[dict[str, Any]]:
                return [dict(action, focus_before=action.get("focused_before"), focus_after=action.get("focused_after")) for action in actions[-12:]]

            async def observe() -> dict[str, Any]:
                observation = await page.evaluate(OBSERVE_JS)
                observation.update({
                    "goal": goal, "url": page.url, "scenario": "",
                    "history": action_history(),
                })
                observation["success_marker_visible"] = bool(observation["success"] and trusted_fixture and urlsplit(page.url).path.startswith("/demo/"))
                observation["expected_text"] = expected_text
                observation["expected_text_matched"] = (
                    " ".join(expected_text.casefold().split()) in " ".join(observation["success_text"].casefold().split())
                    if expected_text is not None else None
                )
                observation["success"] = bool(
                    observation["success_marker_visible"] and
                    (expected_text is None or observation["expected_text_matched"])
                )
                return observation

            async def record(action: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
                filename = f"{len(emitted):03d}.png"
                await page.screenshot(path=str(artifacts_dir / filename), full_page=True, timeout=5000)
                focused = before.get("active_element") or {}
                target_after = next((control for control in after.get("controls", []) if control.get("id") == focused.get("id")), None)
                if target_after is None and _focus_id(before) == _focus_id(after):
                    target_after = after.get("active_element") or {}
                target_after = target_after or {}
                event = {
                    "seq": len(emitted), "action": action["action"],
                    "key": action.get("key"), "text": action.get("text"),
                    "reason": action.get("reason", ""),
                    "focused_before": _focus_id(before), "focused_after": _focus_id(after),
                    "focused_tag": focused.get("tag"), "input_kind": focused.get("input_kind", "other"),
                    "value_before": focused.get("value"), "value_after": target_after.get("value"),
                    "value_changed": (focused.get("value") != target_after.get("value")) if target_after else None,
                    "selected_label_before": focused.get("selected_label"), "selected_label_after": target_after.get("selected_label"),
                    "selected_index_before": focused.get("selected_index"), "selected_index_after": target_after.get("selected_index"),
                    "selects_before": _select_states(before), "selects_after": _select_states(after),
                    "screenshot": filename, "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                emitted.append(event)
                await emit(event)
                return event

            try:
                await page.goto(url, wait_until="domcontentloaded")
                await page.add_style_tag(content=FOCUS_CSS)
                last_observation = await observe()
                await record({"action": "observe", "reason": "Initial browser state before keyboard interaction."}, last_observation, last_observation)

                for _ in range(max_steps):
                    if policy_violations:
                        summary = "The page navigated outside the permitted origin; the task was stopped."
                        evidence = ["Out-of-origin navigation was observed; no task completion was accepted."]
                        break
                    if last_observation.get("success"):
                        result["status"] = "passed"
                        summary = "The keyboard task reached a visible, independent confirmation."
                        evidence = [f'Owned demo confirmation: {last_observation["success_text"]}']
                        break
                    remaining = RUN_TIMEOUT_SECONDS - (time.monotonic() - started)
                    if remaining <= 0:
                        summary = "The run reached its time limit; task accessibility remains inconclusive."
                        break
                    decision = _validate_decision(await asyncio.wait_for(
                        decide(last_observation), timeout=min(DECISION_TIMEOUT_SECONDS, remaining),
                    ))
                    if decision["action"] in {"done", "blocked"}:
                        await record(decision, last_observation, last_observation)
                        evidence = _barrier_evidence(last_observation, actions)
                        if evidence:
                            result["status"] = "blocked"
                            summary = "The tested keyboard task encountered an observed navigation barrier."
                        else:
                            summary = "The planner stopped, but no independent completion or proven keyboard barrier was observed."
                            evidence = ["The planner verdict alone was not treated as a pass or an accessibility failure."]
                        break
                    before = last_observation
                    if decision["action"] == "press":
                        await page.keyboard.press(decision["key"])
                    else:
                        _validate_typing_target(before, decision["text"])
                        await page.keyboard.type(decision["text"], delay=TYPING_DELAY_MS)
                    await page.wait_for_timeout(80)
                    last_observation = await observe()
                    event = await record(decision, before, last_observation)
                    actions.append(event)
                    # observe() ran before the new event existed. Include the
                    # just-executed action in the very next planner call.
                    last_observation["history"] = action_history()
                else:
                    summary = "The keyboard action budget was exhausted; this does not establish an accessibility failure."

                # The final permitted action can itself complete the task.
                if last_observation.get("success") and not policy_violations:
                    result["status"] = "passed"
                    summary = "The keyboard task reached a visible, independent confirmation."
                    evidence = [f'Owned demo confirmation: {last_observation["success_text"]}']
                    if expected_text is not None:
                        evidence.append("The visible confirmation contains the expected task details.")
                elif last_observation.get("success_marker_visible") and expected_text is not None and not policy_violations:
                    result["status"] = "inconclusive"
                    summary = "A confirmation appeared, but it did not match the expected task details."
                    evidence = [
                        f"Expected confirmation to include: {expected_text}",
                        f'Observed confirmation: {last_observation.get("success_text", "")}',
                        "A visible success marker alone was not accepted as proof of the requested result.",
                    ]
                elif result["status"] == "inconclusive" and not policy_violations:
                    established = _barrier_evidence(last_observation, actions)
                    if established:
                        result["status"] = "blocked"
                        summary = "The tested keyboard task encountered an observed navigation barrier."
                        evidence = established
            finally:
                if trace_started:
                    await context.tracing.stop(path=str(artifacts_dir / "trace.zip"))
                    trace_started = False
                await context.close()
                await browser.close()

    except (asyncio.TimeoutError, PlaywrightTimeoutError):
        result["status"] = "inconclusive"
        summary = "A browser or planner operation timed out; accessibility remains inconclusive."
        evidence = ["A timeout is not evidence that the task is inaccessible."]
    except Exception as exc:
        result["status"] = "error"
        error = f"{type(exc).__name__}: {exc}"[:600]
        summary = "The run could not complete because of an execution or configuration error."
    finally:
        _write_reproducer(artifacts_dir / "reproducer.py", url, actions, expected_text)
        (artifacts_dir / "events.json").write_text(json.dumps(emitted, indent=2, ensure_ascii=False), encoding="utf-8")

    result["report"] = {
        "summary": summary, "evidence": evidence, "steps_count": len(actions),
        "success_text": last_observation.get("success_text", ""),
        "expected_text": expected_text, "expected_text_matched": last_observation.get("expected_text_matched"),
        "run_id": run_id, "goal": goal, "url": _public_url(url),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "browser_version": browser_version,
        "blocked_requests": list(dict.fromkeys(blocked_requests)),
        "canceled_downloads": canceled_downloads, "closed_popups": closed_popups,
        "policy_violations": policy_violations,
        "artifacts": {"trace": "trace.zip", "reproducer": "reproducer.py", "events": "events.json"},
    }
    if error:
        result["error"] = error
    return result
