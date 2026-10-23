# AccessProof

**Can someone finish this website task using only a keyboard?**

AccessProof attempts a booking task in a real browser, records each keyboard action,
and produces screenshots, a browser trace, a JSON report, and a runnable reproducer.
A visible booking confirmation containing the tester's expected text determines
success independently of the model. The default expectation checks the fictional
name, email, and tutoring topic together.

This is a working prototype for the **Nebius x NVIDIA Global AI Hackathon**.
The intended submission track is **Coding and Agentic Engineering**.

**Hosted demo:** <https://accessproof-demo.onrender.com> — username `judge`, with
the demo password provided separately to judges. Recorded live fixture results
and downloadable evidence are in [EVALUATION.md](EVALUATION.md).

## Start on your Mac

For a fresh checkout:

```bash
git clone https://github.com/SS221908/accessproof.git
cd accessproof
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On macOS, the runner automatically uses Google Chrome if it is installed in
`/Applications`. It creates a fresh, isolated browser context. If Chrome is not
installed, or on another operating system, install Playwright's Chromium:

```bash
python -m playwright install chromium
```

Create a Token Factory API key and enter its full secret in a hidden prompt:

```bash
python scripts/copy_saved_key.py --new
```

When the hidden prompt appears, copy the full new secret from Nebius, return to
Terminal, paste, and press Enter. The helper verifies the key with the model-list
API before saving it in an ignored `.env` file with owner-only permissions. It
prints a fingerprint instead of the key. This verification makes no inference
request. On other operating systems, use `python scripts/configure_key.py` for
hidden key entry instead of the macOS clipboard helper.

Then start the application:

```bash
python scripts/run.py
```

Open **http://127.0.0.1:8000**. Keep that Terminal running. Press Ctrl+C to stop.

## First complete workflow

1. Select **Unreachable booking button**.
2. Keep the sample goal, which supplies fictional booking details.
   The expected confirmation text must match the details you want verified.
3. Choose **Live NVIDIA** to run Nemotron through Nebius Token Factory, or explicitly
   select **Offline demo** to exercise the browser without any AI requests.
4. Start the test. Review the action timeline, screenshot evidence, and report.
5. Use **Test fixed form** to attempt the same goal on the repaired example.
6. Download the report, reproducer, or browser trace.

The bundled examples are owned test fixtures; no real appointment is created.
They cover a working form, an unreachable booking control, a modal focus trap, and
a working form with a different field order. This starter tests these examples;
it does not yet accept arbitrary external websites or authenticated campus portals.

## NVIDIA and Nebius integration

Live mode uses `AsyncOpenAI` with Nebius Token Factory's inference API:

- Endpoint: `https://api.tokenfactory.nebius.com/v1/`
- Default model: `nvidia/Nemotron-3.5-Super-VL`
- The model receives the user's task, visible controls and values, active keyboard
  focus, status messages, and a bounded action history.
- Requests use structured text observations. Screenshots are captured as evidence
  for developers to inspect.
- It chooses one validated keyboard action at a time: press a permitted key, type
  text into the currently focused field, or report a stop condition.
- Playwright executes the action. Browser observations determine the final result.
- No mouse clicks, arbitrary code execution, or model-controlled navigation tools
  are available to the planner.

Use the exact NVIDIA model ID and API base URL available in your account. You can
change `NEBIUS_MODEL` and `NEBIUS_BASE_URL` in your ignored `.env` file. A run makes
at most 24 keyboard planning steps by default, with at most one correction request
for an invalid model response. Provider authentication or credit errors stop the
run; they never silently switch to offline mode.

**Offline mode is a deterministic fixture demonstration with no AI calls.** It is
labeled in the dashboard, history, and exported run metadata. It is useful for
testing installation and the UI; it is not evidence of NVIDIA/Nebius integration.

References:

- [Nebius quickstart](https://docs.tokenfactory.nebius.com/quickstart)
- [Nebius API and authentication](https://docs.tokenfactory.nebius.com/api-reference/introduction)
- [Playwright keyboard API](https://playwright.dev/python/docs/api/class-keyboard)
- [W3C guidance on accessibility evaluation tools](https://www.w3.org/WAI/test-evaluate/tools/)

## Outcomes and evidence

- **Passed:** the browser observed a visible booking confirmation containing the
  configured expected text. A confirmation with incorrect expected details does not pass.
- **Blocked:** browser evidence supports a specific tested keyboard barrier.
- **Inconclusive:** the agent did not finish within its action budget or could not
  establish a specific barrier from the available evidence.
- **Error:** an infrastructure, model, configuration, or browser error stopped the run.

An agent getting stuck is not automatically an accessibility failure. Reports are
limited to the task and behavior observed. They do not certify complete WCAG
conformance or replace accessibility reviews with users and assistive technologies.

Local run records are stored in `.data/`; screenshots, traces, and reproducers are
stored in `.artifacts/`. Both are ignored by Git. Avoid putting private information
into goals: the visible page state is sent to Nebius in live mode and evidence can
contain typed values. The sample fixtures use fictional details.

## Run the checks

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Unit and API tests use mocked provider responses; browser tests use local fixture
pages. They do not need an API key and do not spend inference credits. Browser
tests require the Chromium installation above.

For a custom Chromium executable, set `ACCESSPROOF_BROWSER_EXECUTABLE` to its path.
The runner and exported reproducer both accept this optional override.

To check the sample keyboard workflow on your own browser without making any AI
requests, run:

```bash
python scripts/check_keyboard.py
```

The check serves the owned example on a temporary local port and verifies the
complete booking confirmation. It also exercises keyboard type-ahead on the
native topic dropdown. A pass here verifies the browser workflow; live NVIDIA
planning is a separate test in the dashboard.

Native dropdowns expose committed selections rather than their platform menu's
pending highlight. The planner can type an observed enabled option's label while
the dropdown has focus, then use Tab to commit and continue. New event reports
include selection values before and after each action to help diagnose failures.
The starter's native-select type-ahead currently supports ASCII option labels.

The reproducer is a standalone Python file using Playwright. To try a repaired
version of the same page, set `ACCESSPROOF_TEST_URL` before running it. This replays
the recorded actions; substantial form layout changes may require a new task run.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Application status and whether a key is configured |
| `GET /api/config` | Available fixtures, model name, live readiness |
| `GET /api/key-check` | Protected key-format summary, fingerprint, and deployed revision |
| `POST /api/runs` | Start a bounded live or offline test |
| `GET /api/runs` | Saved run history |
| `GET /api/runs/{id}` | Current status, actions, and report |
| `GET /api/runs/{id}/report` | Download the JSON report |
| `GET /api/runs/{id}/reproducer` | Download the Python reproducer |
| `GET /api/runs/{id}/trace` | Download the Playwright trace |

Example request body:

```json
{
  "scenario": "unreachable",
  "goal": "Book a tutoring appointment for Alex Rivera, alex@example.com, topic Calculus.",
  "expected_text": "Alex Rivera · alex@example.com · Calculus",
  "mode": "live"
}
```

## Before submission

- Evaluate live NVIDIA runs on all bundled cases and additional form variations;
  report measured results, failures, model calls, and latency honestly.
- Get feedback from developers and people who use keyboard navigation.
- Keep the hosted demo and private judging access available. The recorded hosted
  live results cover the broken and repaired fixtures; sustained capacity and
  availability remain unmeasured. The app uses a single in-process browser queue.
- Record a public YouTube demonstration under three minutes.
- Follow [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the screen sequence and narration.
- Describe the exact NVIDIA model and Nebius runtime calls in the submission.
- Add your own specific platform feedback to `HACKATHON.md`.

## Hosted demo

The repository includes a Dockerfile using Playwright's version-matched browser
image, pinned direct hosted dependencies, and a Render Free Blueprint.
See [DEPLOY.md](DEPLOY.md) for the account setup, secret
environment variables, demo sign-in, and offline-then-live validation steps.

Hosted deployments require username `judge` and the configured
`ACCESSPROOF_DEMO_PASSWORD`. The app uses the configured public origin for its
owned browser fixtures and requires an explicit allowed hostname. Render supplies
those values automatically. Local development with `python scripts/run.py` keeps
its loopback defaults.

The supplied evidence records two completed hosted live runs on Render Free:
one observed barrier and one successful booking. This does not measure sustained
capacity or uptime. Runtime history and artifacts are ephemeral and the service
sleeps when idle; download evidence you want to keep. See [DEPLOY.md](DEPLOY.md).

## License

MIT. See `LICENSE`. The existing repository license and attribution are preserved.
