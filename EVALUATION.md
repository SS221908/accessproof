# AccessProof evaluation

## Linked hosted retest — October 25, 2026

The latest exported sequence records a broken-form run followed by **Test fixed
form**. The repaired run's `parent_id` exactly matches the broken run's full ID.
Both ran on Render with live `nvidia/Nemotron-3.5-Super-VL` inference through
Nebius Token Factory and Chromium `153.0.8010.12`.

| Measurement | Broken booking form | Linked repaired-form retest |
| --- | --- | --- |
| Source report | [2baf4f83](evidence/accessproof-2baf4f83.json) | [7ffb869f](evidence/accessproof-7ffb869f.json) |
| Recorded outcome | Blocked | Passed |
| Mode | Live NVIDIA | Live NVIDIA |
| Keyboard actions | 12 | 8 |
| Recorded events | 14 | 9 |
| Model calls | 14 | 8 |
| Reported elapsed time | 54.39 seconds | 39.80 seconds |
| Prompt tokens | 27,577 | 13,303 |
| Completion tokens | 4,999 | 1,135 |
| Total tokens | 32,576 | 14,438 |
| Expected confirmation matched | No | Yes |
| Execution error | None | None |

The broken run started at 5:36 PM Pacific; the retest started at 5:49 PM.
The JSON timestamps use UTC and therefore show October 26. Both used the same
fictional name, email, and topic: Alex Rivera, `alex@example.com`, Calculus.

Nine Tab presses in the broken run visited the other three enabled tab stops
without reaching the **Reserve appointment** control, which had `tabindex=-1`.
In the retest, typing **Calculus** and pressing Tab committed the selection and
focused the repaired booking button. Enter activated it, and the browser observed
a visible confirmation containing all three expected details. Both reports record
no policy violations or blocked requests.

This demonstrates a linked retest on two intentionally prepared, owned fixtures.
The application selected the prebuilt repaired example; it did not automatically
change the page's code. It does not establish performance improvement, a general
success rate, full accessibility conformance, or resolution of an earlier
intermittent model-action error. The two reports above have no execution error.

Only the original JSON reports have been supplied for this linked pair. Their
referenced browser tests and traces have not been supplied or independently
replayed in this review. The earlier trace and reproducer below belong to a
different run. Neither report embeds a source-code revision.

## Earlier hosted live fixture results — October 22, 2026

These two runs were recorded on October 22, 2026, Pacific time. The application
ran on Render; live inference used `nvidia/Nemotron-3.5-Super-VL` through Nebius
Token Factory. Both reports identify Chromium `153.0.8010.12` and the same goal:
book a tutoring appointment for Alex Rivera, `alex@example.com`, topic Calculus.

| Measurement | Broken booking form | Repaired booking form |
| --- | --- | --- |
| Source report | [22e529cf](evidence/accessproof-22e529cf.json) | [640f266e](evidence/accessproof-640f266e.json) |
| Recorded outcome | Blocked | Passed |
| Mode | Live NVIDIA | Live NVIDIA |
| Keyboard actions | 9 | 8 |
| Recorded events | 11 | 9 |
| Model calls | 11 | 8 |
| Reported elapsed time | 43.79 seconds | 35.12 seconds |
| Prompt tokens | 19,756 | 13,256 |
| Completion tokens | 3,535 | 1,095 |
| Total tokens | 23,291 | 14,351 |
| Expected confirmation matched | No | Yes |
| Execution error | None | None |

Event counts include the initial observation. The broken run also records a
`blocked` stop event. Keyboard-action counts include only `press` and `type`.
Model calls count attempts and can differ from keyboard-action counts.

### What the evidence establishes

The broken fixture's visible **Reserve appointment** control had `tabindex=-1`.
Six observed Tab/Shift+Tab actions visited the other three enabled tab stops
without focusing that control. The report therefore identified a specific
sequential-navigation barrier in the tested task.

On the repaired fixture, the agent typed the observed option label **Calculus**,
committed it with Tab, reached the booking control, and pressed Enter. The browser
independently observed a visible confirmation containing the expected name,
email, and topic. Neither report records policy violations or blocked requests.

These are independent runs on two owned fixtures. Both `parent_id` values are
null; the repaired run occurred at about 6:49 PM Pacific and the broken run at
about 6:53 PM. They are not a recorded chronological repair/retest pair. A fresh
**Test fixed form** workflow created the separately recorded linked sequence above.
The exports do not embed a source-code revision.

These observations do not establish a success rate, a timing improvement,
general website reliability, or complete accessibility conformance. Reported
elapsed time is copied from each report; it is not an uptime or cold-start test.
No dollar cost was calculated from token counts.

### Reproduce and inspect

- [Successful exported browser test](evidence/accessproof-640f266e.py)
- [Successful Playwright trace](evidence/accessproof-640f266e-trace.zip)
- [Hosted application](https://accessproof-demo.onrender.com), with judging
  credentials supplied separately

The exported test contains eight keyboard actions and the independent expected
confirmation assertion. With Playwright installed, run:

```bash
python evidence/accessproof-640f266e.py
```

It uses the public owned fixture page and needs no Nebius key or inference call.
The unmodified export passed a review replay against a local copy of the repaired
fixture using its documented `ACCESSPROOF_TEST_URL` override. A direct replay of
the hosted URL could not be verified from that review environment because its
browser received `ERR_EMPTY_RESPONSE`; the successful hosted live run is evidenced
by the supplied JSON and trace. The trace archive passed its integrity check and
records requests only to the owned demo host, with no Authorization or Cookie
request headers.

Render's runtime history is ephemeral. These exported files preserve the two
observations across service restarts and deployments. The raw reports contain
fictional demo details and retain their original data.

## Earlier local development notes

The earlier native-dropdown investigation recorded the following individual
local attempts. They use a different runtime from the hosted results above.

| Measurement | Earlier attempt | Updated attempt |
| --- | --- | --- |
| Result | Inconclusive | Passed |
| Reported elapsed time | 62.59 seconds | 12.54 seconds |
| Keyboard actions | 24 | 8 |
| Model calls | 28 | 8 |
| Total tokens | 56,630 | 14,441 |
| Expected confirmation matched | No | Yes |

The update used keyboard type-ahead to select Calculus before activating the
booking control. These two development attempts are not a general reliability
benchmark, and their timings should not be compared directly with the hosted runs.
