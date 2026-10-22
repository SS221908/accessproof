"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const ACTIVE = new Set(["queued", "running"]);
  const STATUS = {
    queued: "Queued",
    running: "Testing the task",
    passed: "Task completed",
    blocked: "Barrier observed",
    inconclusive: "Needs review",
    error: "Run error",
  };
  const FALLBACK_SCENARIOS = [
    { id: "unreachable", label: "Unreachable booking button", description: "A booking form with a control that cannot be reached using Tab." },
    { id: "working", label: "Working appointment form", description: "An appointment form with keyboard-operable controls and a clear confirmation." },
    { id: "trap", label: "Keyboard focus trap", description: "A form with a dialog that can trap keyboard focus." },
    { id: "variant", label: "Different form layout", description: "The same task on a form with a different arrangement of controls." },
  ];
  const state = {
    config: null,
    scenarios: FALLBACK_SCENARIOS,
    run: null,
    history: [],
    selectedStep: null,
    followLatest: true,
    submitting: false,
    pollTimer: null,
    pollFailures: 0,
    lastAnnouncement: "",
    userChoseMode: false,
  };

  function setText(id, text) {
    byId(id).textContent = String(text ?? "");
  }

  function announce(text) {
    if (state.lastAnnouncement === text) return;
    state.lastAnnouncement = text;
    setText("announcer", text);
  }

  function showMessage(id, message) {
    const element = byId(id);
    element.textContent = message || "";
    element.hidden = !message;
  }

  function isBusy() {
    return state.submitting || Boolean(state.run && ACTIVE.has(state.run.status));
  }

  function selectedMode() {
    return document.querySelector('input[name="mode"]:checked')?.value || "offline";
  }

  function modeLabel(mode) {
    return mode === "live" ? "Live NVIDIA · Nebius" : "Offline demo · no AI calls";
  }

  function prettyModel(model) {
    return String(model || "NVIDIA model").replace(/^nvidia\//i, "").replace(/-/g, " ");
  }

  function scenarioFor(id) {
    return state.scenarios.find((item) => item.id === id) || FALLBACK_SCENARIOS.find((item) => item.id === id) || { id, label: "Keyboard test", description: "" };
  }

  function shortRunId(id) {
    return String(id || "").slice(0, 8);
  }

  function formatDate(value) {
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime())) return "Saved run";
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
  }

  function focusedLabel(focused) {
    if (!focused) return "Page";
    if (typeof focused === "string") return focused;
    const item = focused.active || focused;
    return item.label || item.name || item.text || item.placeholder || (item.id ? `#${item.id}` : item.tag || item.tagName || "Page");
  }

  function actionLabel(step) {
    switch (step.action) {
      case "press": return `Press ${step.key || "key"}`;
      case "type": return step.input_kind === "select" ? "Type the dropdown option" : "Type into the focused field";
      case "done": return "Check task completion";
      case "blocked": return "Review a possible barrier";
      case "observe": return "Observe the page";
      default: return step.action ? String(step.action).replace(/_/g, " ") : "Observe the page";
    }
  }

  function safeArtifactUrl(runId, filename) {
    if (typeof filename !== "string" || !filename) return null;
    // Artifact paths are always resolved under this run on the same server.
    const parts = filename.replace(/\\/g, "/").split("/");
    if (parts.some((part) => !part || part === "." || part === "..") || filename.includes(":")) return null;
    return `/artifacts/${encodeURIComponent(runId)}/${parts.map(encodeURIComponent).join("/")}`;
  }

  async function fetchJson(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {
        ...options,
        cache: "no-store",
        headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
        signal: controller.signal,
      });
      let data;
      try {
        data = await response.json();
      } catch {
        throw new Error("The workspace returned an unexpected response. Check that the AccessProof server is running.");
      }
      if (!response.ok) {
        const detail = typeof data.detail === "string" ? data.detail : typeof data.error === "string" ? data.error : null;
        throw new Error(detail || `The request could not be completed (HTTP ${response.status}).`);
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The workspace took too long to respond. Try refreshing the run.");
      if (error instanceof TypeError) throw new Error("Could not reach the workspace. Check that the AccessProof server is running.");
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function updateModeHelp() {
    const live = selectedMode() === "live";
    setText("mode-help", live ? "NVIDIA plans each keyboard action through Nebius Token Factory." : "A deterministic fixture demonstration using sample data. No AI calls.");
    if (!state.run) setText("run-caption", live ? "Uses your configured Nebius account. Each action is recorded." : "Offline demo · no AI calls. Each action is recorded.");
  }

  function updateScenarioDetails() {
    const scenario = scenarioFor(byId("scenario").value);
    setText("scenario-description", scenario.description);
    byId("scenario-preview").href = `/demo/${encodeURIComponent(scenario.id)}`;
    if (!state.run) setText("browser-address", `${window.location.host}/demo/${scenario.id}`);
  }

  function updateControls() {
    const busy = isBusy();
    byId("start-test").disabled = !state.config || busy || (selectedMode() === "live" && !state.config.live_ready);
    setText("start-label", state.submitting ? "Starting test…" : busy ? "Test in progress…" : "Start keyboard test");
    byId("retest-button").disabled = busy || !state.run || (state.run.mode === "live" && !state.config?.live_ready);
    byId("refresh-run").disabled = state.submitting;
    byId("evidence-actions").hidden = !state.run;
    document.querySelectorAll(".history-item").forEach((item) => { item.disabled = busy; });
    byId("test-form").setAttribute("aria-busy", String(state.submitting));
  }

  function renderConfig(config) {
    state.config = config;
    if (Array.isArray(config.scenarios) && config.scenarios.length) state.scenarios = config.scenarios;
    const previousScenario = byId("scenario").value;
    const select = byId("scenario");
    select.replaceChildren();
    for (const scenario of state.scenarios) {
      const option = document.createElement("option");
      option.value = scenario.id;
      option.textContent = scenario.label || scenario.id;
      select.append(option);
    }
    const initialScenario = state.scenarios.some((item) => item.id === previousScenario) ? previousScenario : state.scenarios[0].id;
    select.value = initialScenario;
    const scenarioTag = document.querySelector(".field-tag");
    scenarioTag.textContent = `${state.scenarios.length} scenarios`;
    byId("mode-live").disabled = !config.live_ready;
    byId("live-mode-option").classList.toggle("is-disabled", !config.live_ready);
    byId("setup-hint").hidden = Boolean(config.live_ready);
    if (!state.userChoseMode) byId(config.live_ready ? "mode-live" : "mode-offline").checked = true;
    if (!config.live_ready && selectedMode() === "live") byId("mode-offline").checked = true;
    byId("connection-status").dataset.state = config.live_ready ? "ready" : "offline";
    setText("connection-text", config.live_ready ? "Nebius key configured" : "Offline demo available");
    setText("model-caption", prettyModel(config.model));
    byId("retry-config").hidden = true;
    showMessage("form-error", "");
    updateScenarioDetails();
    updateModeHelp();
    updateControls();
  }

  function renderScreenshot() {
    const run = state.run;
    const steps = Array.isArray(run?.steps) ? run.steps : [];
    let step = state.selectedStep == null ? steps.at(-1) : steps[state.selectedStep];
    let stepIndex = step ? steps.indexOf(step) : null;
    // A state-only event may lack a frame; show the latest recorded frame up to it.
    if (step && !step.screenshot) {
      for (let index = stepIndex; index >= 0; index -= 1) {
        if (steps[index].screenshot) { step = steps[index]; break; }
      }
    }
    const url = step ? safeArtifactUrl(run.id, step.screenshot) : null;
    const image = byId("evidence-image");
    if (url) {
      if (image.dataset.artifactUrl !== url) {
        image.dataset.artifactUrl = url;
        image.src = url;
      }
      image.alt = `Recorded browser view, step ${stepIndex + 1}. Focus: ${focusedLabel(step.focused_after || step.focused_before)}.`;
      image.hidden = false;
      byId("empty-preview").hidden = true;
    } else {
      image.hidden = true;
      byId("empty-preview").hidden = false;
      setText("empty-title", run && ACTIVE.has(run.status) ? "Following the first keystroke…" : run ? "No browser frame was recorded." : "Your next journey starts here.");
      setText("empty-copy", run && ACTIVE.has(run.status) ? "The browser is starting. Its recorded journey will appear here." : run ? "Inspect the run message and evidence below for what happened." : "Run a test to see the browser, keyboard actions, and evidence appear step by step.");
    }
    setText("selected-action", stepIndex == null ? "—" : `Step ${stepIndex + 1} of ${steps.length}`);
  }

  function renderTimeline() {
    const steps = Array.isArray(state.run?.steps) ? state.run.steps : [];
    const focusedIndex = document.activeElement?.dataset?.stepIndex;
    const timeline = byId("timeline");
    timeline.replaceChildren();
    byId("timeline-empty").hidden = steps.length > 0;
    setText("timeline-count", `${steps.length} ${steps.length === 1 ? "step" : "steps"}`);
    const selectedIndex = state.selectedStep == null ? steps.length - 1 : state.selectedStep;
    steps.forEach((step, index) => {
      const item = document.createElement("li");
      item.className = "timeline-item";
      const button = document.createElement("button");
      button.type = "button";
      button.className = `step-button${index === selectedIndex ? " is-selected" : ""}`;
      button.dataset.stepIndex = String(index);
      button.setAttribute("aria-pressed", String(index === selectedIndex));
      button.setAttribute("aria-label", `Inspect step ${index + 1}: ${actionLabel(step)}`);
      const number = document.createElement("span");
      number.className = "step-number";
      number.textContent = String(index + 1).padStart(2, "0");
      const content = document.createElement("span");
      content.className = "step-content";
      const title = document.createElement("strong");
      title.className = "step-action";
      title.textContent = actionLabel(step);
      const reason = document.createElement("span");
      reason.className = "step-reason";
      reason.textContent = step.reason || "Recorded browser action.";
      const focus = document.createElement("span");
      focus.className = "step-focus";
      focus.textContent = `Focus: ${focusedLabel(step.focused_after || step.focused_before)}`;
      content.append(title, reason, focus);
      if (step.input_kind === "select") {
        const selection = document.createElement("span");
        selection.className = "step-focus";
        const before = step.selected_label_before || step.value_before || "No selection";
        const after = step.selected_label_after || step.value_after || "No selection";
        selection.textContent = `Selection: ${before} → ${after}`;
        content.append(selection);
      }
      const kind = document.createElement(step.action === "press" ? "kbd" : "span");
      kind.className = `step-kind ${step.action === "press" ? "step-key" : step.action === "type" ? "step-type" : "step-state"}`;
      kind.textContent = step.action === "press" ? step.key || "Key" : step.action === "type" ? "Text" : "State";
      button.append(number, content, kind);
      button.addEventListener("click", () => {
        state.selectedStep = index;
        state.followLatest = index === steps.length - 1;
        renderTimeline();
        renderScreenshot();
      });
      item.append(button);
      timeline.append(item);
    });
    if (focusedIndex !== undefined) {
      timeline.querySelector(`[data-step-index="${Number(focusedIndex)}"]`)?.focus({ preventScroll: true });
    }
  }

  function setDownloadLink(id, runId, suffix, enabled) {
    const link = byId(id);
    link.href = `/api/runs/${encodeURIComponent(runId)}/${suffix}`;
    link.setAttribute("aria-disabled", String(!enabled));
    link.tabIndex = enabled ? 0 : -1;
  }

  function renderResult() {
    const run = state.run;
    const terminal = run && !ACTIVE.has(run.status);
    const report = run?.report;
    byId("results-card").hidden = !terminal;
    if (!terminal) return;
    const mode = modeLabel(run.mode);
    setText("result-mode-label", mode);
    byId("result-mode-label").dataset.mode = run.mode;
    setText("result-title", STATUS[run.status] || "Journey report");
    byId("result-icon").dataset.status = run.status;
    setText("result-icon", run.status === "passed" ? "✓" : run.status === "blocked" ? "!" : "↳");
    setText("result-summary", report?.summary || run.error || "The run ended before task completion could be confirmed. Review its recorded steps.");
    const expectedText = run.expected_text || report?.expected_text;
    showMessage("result-condition", expectedText ? `Expected confirmation: ${expectedText}` : "");
    const success = report?.success_text;
    byId("success-confirmation").hidden = !(run.status === "passed" && success);
    setText("success-confirmation", success ? `Page confirmation: ${success}` : "");
    const evidenceList = byId("result-evidence");
    evidenceList.replaceChildren();
    if (Array.isArray(report?.evidence)) {
      report.evidence.forEach((entry) => {
        const value = typeof entry === "string" ? entry : entry?.description || entry?.message || entry?.text;
        if (!value) return;
        const item = document.createElement("li");
        item.textContent = value;
        evidenceList.append(item);
      });
    }
    const notices = [];
    if (run.mode !== "live") notices.push("Offline fixture demonstration. This run made no NVIDIA or Nebius AI calls.");
    if (run.status === "inconclusive") notices.push("This outcome needs review. It does not establish that the task is inaccessible.");
    if (run.parent_id) {
      const parent = state.history.find((item) => item.id === run.parent_id);
      notices.push(`Fixed-form retest of run ${shortRunId(run.parent_id)}${parent ? ` (${STATUS[parent.status]?.toLowerCase() || parent.status})` : ""}.`);
    }
    showMessage("result-notice", notices.join(" "));
    const hasSteps = Array.isArray(run.steps) && run.steps.length > 0;
    setDownloadLink("download-report", run.id, "report", true);
    setDownloadLink("download-test", run.id, "reproducer", hasSteps);
    setDownloadLink("download-trace", run.id, "trace", hasSteps);
  }

  function renderRun() {
    const run = state.run;
    if (!run) return;
    const steps = Array.isArray(run.steps) ? run.steps : [];
    const status = byId("run-status");
    status.dataset.status = run.status;
    status.textContent = STATUS[run.status] || "Needs review";
    byId("run-detail-bar").hidden = false;
    setText("run-mode-label", modeLabel(run.mode));
    byId("run-mode-label").dataset.mode = run.mode;
    const calls = typeof run.model_calls === "number" && run.model_calls >= 0 ? ` · ${run.model_calls} model calls` : "";
    setText("run-id-label", `RUN ${shortRunId(run.id)}${calls}`);
    setText("browser-address", `${window.location.host}/demo/${run.scenario}`);
    setText("action-count", steps.length);
    setText("assertion-status", run.status === "passed" ? "Confirmed" : ACTIVE.has(run.status) ? "Checking…" : "Not confirmed");
    byId("assertion-status").dataset.confirmed = String(run.status === "passed");
    const active = ACTIVE.has(run.status);
    byId("run-progress").hidden = !active;
    const maxSteps = state.config?.max_steps || 24;
    byId("progress-fill").style.width = `${Math.min(100, (steps.length / maxSteps) * 100)}%`;
    setText("progress-label", run.status === "queued" ? "Waiting for the browser…" : steps.length ? `${steps.length} steps captured · following the keyboard` : "Starting the browser…");
    byId("browser-frame")?.setAttribute("aria-busy", String(active));
    if (state.followLatest) state.selectedStep = steps.length ? steps.length - 1 : null;
    if (state.selectedStep != null && state.selectedStep >= steps.length) state.selectedStep = steps.length - 1;
    showMessage("run-alert", run.error || "");
    renderScreenshot();
    renderTimeline();
    renderResult();
    updateControls();
    renderHistory();
    announce(`${modeLabel(run.mode)}. ${STATUS[run.status] || run.status}. ${steps.length} recorded steps.`);
  }

  function renderHistory() {
    const history = state.history;
    setText("history-count", history.length);
    setText("history-total", history.length ? `${history.length} saved ${history.length === 1 ? "run" : "runs"}` : "No runs yet");
    byId("history-empty").hidden = history.length > 0;
    const container = byId("history-list");
    container.replaceChildren();
    history.forEach((run) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `history-item${state.run?.id === run.id ? " is-selected" : ""}`;
      button.disabled = isBusy();
      button.setAttribute("aria-label", `Inspect ${scenarioFor(run.scenario).label}, ${modeLabel(run.mode)}, ${STATUS[run.status] || run.status}, ${formatDate(run.created_at)}`);
      const icon = document.createElement("span");
      icon.className = "history-icon";
      icon.textContent = run.status === "passed" ? "✓" : run.status === "blocked" ? "!" : "↳";
      icon.dataset.status = run.status;
      const copy = document.createElement("span");
      copy.className = "history-copy";
      const title = document.createElement("strong");
      title.textContent = scenarioFor(run.scenario).label;
      const subtitle = document.createElement("small");
      subtitle.textContent = run.goal || "Keyboard journey";
      copy.append(title, subtitle);
      const meta = document.createElement("span");
      meta.className = "history-meta";
      const mode = document.createElement("span");
      mode.className = "run-mode-label";
      mode.dataset.mode = run.mode;
      mode.textContent = modeLabel(run.mode);
      const date = document.createElement("small");
      date.textContent = formatDate(run.created_at);
      meta.append(mode, date);
      const badge = document.createElement("span");
      badge.className = "history-status";
      badge.dataset.status = run.status;
      badge.textContent = STATUS[run.status] || "Needs review";
      button.append(icon, copy, meta, badge);
      button.addEventListener("click", () => loadRun(run.id, true));
      container.append(button);
    });
  }

  async function loadHistory() {
    const data = await fetchJson("/api/runs");
    state.history = Array.isArray(data) ? data : Array.isArray(data.runs) ? data.runs : [];
    renderHistory();
  }

  function stopPolling() {
    if (state.pollTimer) window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }

  function schedulePoll() {
    stopPolling();
    if (!state.run || !ACTIVE.has(state.run.status)) return;
    const id = state.run.id;
    state.pollTimer = window.setTimeout(async () => {
      if (state.run?.id !== id) return;
      try {
        const run = await fetchJson(`/api/runs/${encodeURIComponent(id)}`);
        if (state.run?.id !== id) return;
        state.run = run;
        state.pollFailures = 0;
        renderRun();
        if (ACTIVE.has(run.status)) schedulePoll();
        else await loadHistory();
      } catch (error) {
        state.pollFailures += 1;
        showMessage("run-alert", state.pollFailures < 4 ? `${error.message} Retrying…` : `${error.message} Automatic updates are paused; use Refresh to check this run.`);
        if (state.pollFailures < 4) schedulePoll();
      }
    }, 1000);
  }

  async function loadRun(id, syncForm = false) {
    stopPolling();
    showMessage("run-alert", "");
    try {
      const run = await fetchJson(`/api/runs/${encodeURIComponent(id)}`);
      state.run = run;
      state.selectedStep = null;
      state.followLatest = true;
      state.pollFailures = 0;
      if (syncForm) {
        if (state.scenarios.some((item) => item.id === run.scenario)) byId("scenario").value = run.scenario;
        byId("goal").value = run.goal || "";
        if (run.expected_text) byId("expected-text").value = run.expected_text;
        if (run.mode !== "live" || state.config?.live_ready) byId(run.mode === "live" ? "mode-live" : "mode-offline").checked = true;
        updateScenarioDetails();
        updateModeHelp();
      }
      renderRun();
      schedulePoll();
      if (syncForm) byId("evidence-title").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
    } catch (error) {
      showMessage("run-alert", error.message);
      announce(error.message);
    }
  }

  async function startRun(payload) {
    if (isBusy()) return;
    state.submitting = true;
    stopPolling();
    showMessage("form-error", "");
    showMessage("run-alert", "");
    updateControls();
    try {
      const run = await fetchJson("/api/runs", { method: "POST", body: JSON.stringify(payload) });
      state.run = run;
      state.selectedStep = null;
      state.followLatest = true;
      state.pollFailures = 0;
      renderRun();
      try { await loadHistory(); } catch { /* The active run can still be inspected. */ }
      schedulePoll();
    } catch (error) {
      showMessage("form-error", error.message);
      announce(error.message);
    } finally {
      state.submitting = false;
      updateControls();
    }
  }

  async function initialize() {
    byId("retry-config").disabled = true;
    const results = await Promise.allSettled([fetchJson("/api/config"), loadHistory()]);
    if (results[0].status === "fulfilled") {
      renderConfig(results[0].value);
      const latest = state.history.find((run) => ACTIVE.has(run.status)) || state.history[0];
      if (latest && !state.run) await loadRun(latest.id);
    } else {
      state.config = null;
      byId("connection-status").dataset.state = "error";
      setText("connection-text", "Workspace unavailable");
      setText("model-caption", "Waiting for the local server");
      showMessage("form-error", results[0].reason.message);
      byId("retry-config").hidden = false;
      updateControls();
    }
    if (results[1].status === "rejected") {
      setText("history-total", "History unavailable");
      byId("history-empty").querySelector("p").textContent = "Run history could not be loaded. Your active test can still be inspected above.";
    }
    byId("retry-config").disabled = false;
  }

  byId("test-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;
    const goal = byId("goal").value.trim();
    if (goal.length < 10) return showMessage("form-error", "Describe a task in at least ten characters.");
    const expectedText = byId("expected-text").value.trim();
    if (expectedText.length < 3) return showMessage("form-error", "Enter at least three characters of confirmation text that should appear when the task succeeds.");
    startRun({ scenario: byId("scenario").value, goal, expected_text: expectedText, mode: selectedMode() });
  });
  byId("scenario").addEventListener("change", updateScenarioDetails);
  document.querySelectorAll('input[name="mode"]').forEach((radio) => radio.addEventListener("change", () => {
    state.userChoseMode = true;
    updateModeHelp();
    updateControls();
  }));
  byId("retry-config").addEventListener("click", initialize);
  byId("refresh-run").addEventListener("click", () => { if (state.run) loadRun(state.run.id); });
  byId("retest-button").addEventListener("click", () => {
    const run = state.run;
    if (!run || isBusy()) return;
    byId("scenario").value = "working";
    byId("goal").value = run.goal;
    if (run.expected_text) byId("expected-text").value = run.expected_text;
    if (run.mode !== "live" || state.config?.live_ready) byId(run.mode === "live" ? "mode-live" : "mode-offline").checked = true;
    updateScenarioDetails();
    updateModeHelp();
    startRun({ scenario: "working", goal: run.goal, expected_text: run.expected_text || byId("expected-text").value.trim(), mode: run.mode, parent_id: run.id });
  });
  document.querySelectorAll(".export-actions a").forEach((link) => link.addEventListener("click", (event) => {
    if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
  }));
  byId("evidence-image").addEventListener("error", () => {
    byId("evidence-image").hidden = true;
    byId("empty-preview").hidden = false;
    setText("empty-title", "This frame could not be loaded.");
    setText("empty-copy", "The recorded action trail is still available below. Try refreshing the run.");
  });
  window.addEventListener("beforeunload", stopPolling);
  updateScenarioDetails();
  initialize();
})();
