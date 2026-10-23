# AccessProof submission preparation

- **Track:** Coding and Agentic Engineering
- **Demo:** <https://accessproof-demo.onrender.com>
- **Public MIT repository:** <https://github.com/SS221908/accessproof>
- **Public YouTube video:** [add the final video URL; maximum three minutes]

## Inspiration and audience

Campus web teams and small organizations maintain booking and registration forms
that people need to complete. A form can look usable while its keyboard tab order
skips the action needed to finish. Developers need evidence of what happened in a
specific task, with steps they can inspect and reproduce.

## What it does

AccessProof attempts a booking task using only keyboard actions in a real browser.
It records focus, field and selection values, screenshots, and an action timeline.
Developers can download a JSON report, a Playwright browser trace, and a standalone
Python reproducer of the recorded actions. **Test fixed form** starts a fresh
agent attempt on the repaired example.

The browser checks a visible confirmation against the expected booking details.
The model's own verdict cannot make a run pass or establish an accessibility
failure. An unfinished keyboard attempt without a supported barrier remains
inconclusive; configuration and execution errors are reported separately.

## How we built it

- **NVIDIA:** `nvidia/Nemotron-3.5-Super-VL` chooses one bounded keyboard action at
  a time from the goal, visible controls, current focus, committed values, and
  recent action history.
  Requests use structured text observations; screenshots are recorded as evidence
  for developers to inspect.
- **Nebius Token Factory:** hosts the model inference, called through its
  OpenAI-compatible API at `https://api.tokenfactory.nebius.com/v1/`. Hosted
  inference let us integrate Nemotron through a configured client without
  provisioning a local GPU or downloading the model.
- **Application:** Python, FastAPI, Playwright, SQLite, and an HTML/CSS/JavaScript
  dashboard. Playwright executes keyboard events and independently observes the
  result. The reproducer is generated from the actual recorded actions.
- **Render:** hosts the Docker application, dashboard, API, and browser worker.
  NVIDIA inference runs on Nebius Token Factory; Render hosts the application.

## Demonstrated results

Two independent hosted live runs used the same goal, expected details, NVIDIA
model, and Chrome version:

| Example | Observed result | Keyboard actions | Model calls | Reported elapsed time |
| --- | --- | ---: | ---: | ---: |
| Unreachable booking button | Barrier observed | 9 | 11 | 43.79 s |
| Repaired booking form | Task completed; expected details matched | 8 | 8 | 35.12 s |

The broken example's action was omitted from sequential keyboard navigation.
The repaired example reached the booking button and displayed the expected
confirmation. These exports are separate runs with no parent link; the repaired
run occurred first. They are a fixture comparison, not a linked retest or a
reliability benchmark. See [EVALUATION.md](EVALUATION.md) for evidence and limits.

## Challenges and platform feedback draft

Review this wording against your own experience before submitting:

- Token Factory's OpenAI-compatible interface worked for live model planning from
  the hosted application. The successful repaired-form run used eight model calls
  and 14,351 tokens; the broken-form run used eleven calls and 23,291 tokens.
- Native dropdown interaction needed better application guidance. We added
  keyboard type-ahead using an observed option label, Tab to commit, selection
  state in observations, and before/after values in evidence. An earlier local
  attempt exhausted its action budget before this change.
- An early API-key formatting failure came from our own copy/save helper. We added
  validation there before saving and copying the key for deployment.
- A model-specific cookbook example for bounded JSON actions and native keyboard
  controls would have helped this integration. Token counts are recorded in the
  exported reports; no dollar-cost estimate has been measured here.

## Current limits and next work

The prototype tests owned booking fixtures rather than arbitrary external sites
or authenticated portals. It does not certify WCAG conformance or replace testing
with people who use assistive technologies. Additional live fixture tests,
repeated trials, and feedback from developers and keyboard users are still pending.
Hosted history and artifacts are ephemeral; download useful evidence.

## Private judging instructions

Put the following in Devpost's **private testing instructions**, replacing the
placeholder there only:

```text
Demo: https://accessproof-demo.onrender.com
Username: judge
Password: [enter the configured demo access code in this private field]
Open the demo and allow it to wake before starting a test.
Select Unreachable booking button, keep the fictional sample details, choose
Live NVIDIA agent, and start the test. Inspect the result and exports.
Click Test fixed form for a fresh attempt on the repaired example.
```

Keep the access code out of the public repository, video, and video description.

## Submission checklist

- Record and upload a public YouTube demo of three minutes or less; follow
  [DEMO_SCRIPT.md](DEMO_SCRIPT.md). Show the useful result in the first 30 seconds.
- Verify the hosted URL and judge sign-in, and download the final evidence.
- Confirm the public repository contains its MIT license and working setup steps.
- Review and personalize the platform feedback above.
- Review the complete official rules and any updated submission requirements.
- Keep working judge access available free of charge through the end of judging:
  December 15, 2026 at noon PST. The [official rules](https://nebiusglobalaihackathon.devpost.com/rules)
  require testing access and credentials for private demos. The scheduled judging
  period starts December 1, 2026 at 9:00 AM PST.

The [official schedule](https://nebiusglobalaihackathon.devpost.com/details/dates)
lists the submission deadline as **October 30, 2026 at 10:00 AM PDT**. Recheck it
before submitting. The organizer's [demo guidance](https://nebiusglobalaihackathon.devpost.com/updates/47163-recording-will-your-project-ship)
also emphasizes showing the useful result early, publishing limitations, and
getting user feedback.
