# Host the AccessProof demo

The Docker image serves the dashboard and runs its single browser worker.
NVIDIA model inference continues through Nebius Token Factory. The hosted demo is
<https://accessproof-demo.onrender.com>. The supplied [evaluation](EVALUATION.md)
records two hosted live runs: an observed barrier on the broken fixture and a
successful booking on the repaired fixture.

## Render: first hosted trial

Push the deployment files to the `main` branch of
<https://github.com/SS221908/accessproof> before starting. A Render account and a
working Nebius Token Factory key are needed. Render builds the image from GitHub,
so installing Docker on your Mac is optional.

1. Open <https://dashboard.render.com> and sign in with GitHub.
2. Select **New → Blueprint**, connect the `SS221908/accessproof` repository, and
   select branch **main**. Use the root `render.yaml` file.
3. Review the proposed resources: one **Free Docker web service**, named
   `accessproof-demo`. The Blueprint does not create a database or persistent disk.
4. When Render prompts for `NEBIUS_API_KEY`, provide the full working secret saved
   locally. Paste only its value, without the variable name or surrounding quotes.
   Then create the Blueprint deployment.
5. Wait for the build and deployment to finish. The image includes the Playwright
   browsers and Linux dependencies; the build installs matching Python packages.
6. Open the service's **Environment** page and copy the generated value of
   `ACCESSPROOF_DEMO_PASSWORD`. This is the password for the demo's browser sign-in.
7. Open the service's displayed HTTPS `onrender.com` URL. In the browser sign-in
   prompt, use username **`judge`** and that generated demo password.

Keep the demo password available for the judges through the submission's private
testing instructions. Anyone with it can run the shared demo and view its stored
reports. Use fictional booking details in this demonstration.

On a Mac, this helper checks the saved key's formatting and authenticates it with
the model-list API before saving and copying it. This makes no model-inference
request and never prints the key. Run it from the project folder, then immediately
paste into Render's `NEBIUS_API_KEY` value field:

```bash
source .venv/bin/activate
python scripts/copy_saved_key.py
```

For a fresh replacement key, run `python scripts/copy_saved_key.py --new` and
paste the full new secret only when its hidden prompt appears. Successful
verification saves the key privately in `.env` and copies it to the clipboard.
Use Render's **Save, rebuild, and deploy** action after replacing its value.

If the hosted app still rejects the key's formatting, open
`<your-service-https-url>/api/key-check` in the signed-in browser. This protected
page reports the deployed revision, format validity, invalid-character counts,
and a short SHA-256 fingerprint. Compare its fingerprint with the one printed by
the Mac helper: matching values confirm that both use the same trimmed key.
The page never returns the key or any part of it. A mismatch indicates that the
copied value or the running environment differs; confirm the new deploy is Live
and replace the correct `NEBIUS_API_KEY` value again.

### First checks

1. Open `<your-service-https-url>/health`. A successful response confirms that the
   application is reachable; `live_ready` means a key is configured, not that the
   provider has authenticated it.
2. In the dashboard select **Repaired booking form → Offline fixture demo → Start
   keyboard test**. Verify **Task completed** first. This checks the hosted browser
   without an inference request.
3. Select **Live NVIDIA agent** and run the repaired form again. Confirm the
   expected fictional booking details in its result, then download the JSON
   report, browser test, and trace.
4. Test the unreachable button, modal focus trap, and different form layout. Keep
   both successful and unsuccessful reports when measuring behavior.

The browser worker visits the configured public origin's owned `/demo/` pages.
Those fixture pages and their two assets are public so the worker can load them;
the dashboard, API, and recorded artifacts require demo authentication. On Render,
the app derives its public origin and allowed hostname from
`RENDER_EXTERNAL_URL` automatically.

### Render settings

The Blueprint sets these values. When creating a Web Service manually, use the
same settings and add the secrets through its **Environment** page.

| Setting | Value |
| --- | --- |
| Source repository | `https://github.com/SS221908/accessproof` |
| Branch | `main` |
| Language / runtime | Docker |
| Dockerfile | `./Dockerfile` |
| Docker context | Repository root |
| Instance plan | Free, for the first trial |
| Health check path | `/health` |
| `NEBIUS_API_KEY` | Full verified Token Factory key |
| `NEBIUS_MODEL` | `nvidia/Nemotron-3.5-Super-VL` |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1/` |
| `ACCESSPROOF_DEMO_PASSWORD` | Generated secret, at least 16 characters |
| `ACCESSPROOF_REQUIRE_DEMO_AUTH` | `true` |
| `ACCESSPROOF_HOST` | `0.0.0.0` |
| `PORT` | `10000` |

Leave Docker Command empty to use the image's command. The application runs one
Uvicorn worker because its queue and browser lock live in that process. Keep one
service instance for this starter.

### Free-tier limits

Render Free provides 0.1 CPU and 512 MB RAM. The supplied reports record completed
Chromium workflows on the hosted service, but memory headroom, sustained capacity,
and uptime have not been measured. A healthy `/health` response alone does not
verify browser execution. Check the offline workflow and service logs if deploying
another instance.

Free services sleep after 15 minutes without inbound traffic; waking takes about
a minute. SQLite history and browser artifacts are lost on restart, redeploy, or
idle shutdown because the filesystem is ephemeral. Download useful evidence
before leaving the service. Free services cannot attach a persistent disk.

The workspace also has free-instance-hour, bandwidth, and build-minute limits.
Review those in Render's Billing page. A saved payment method can permit usage
charges beyond included bandwidth/build allowances. This Blueprint selects the
Free plan; it does not provision a paid instance or storage.

If the browser exits or logs an out-of-memory error, stop and inspect the service
logs. Extra CPU on a plan with the same RAM does not resolve a memory limit.
Choose a larger host only after checking the resource requirement and budget.

## Optional local Docker check

These commands require Docker to be installed and running. The example binds
only to your own Mac and supplies no Nebius key; use **Offline fixture demo**.

```bash
docker build -t accessproof:demo .
docker run --rm -p 127.0.0.1:10000:10000 \
  -e ACCESSPROOF_PUBLIC_ORIGIN=http://127.0.0.1:10000 \
  -e ACCESSPROOF_DEMO_PASSWORD=local-browser-check-only \
  accessproof:demo
```

Open <http://127.0.0.1:10000> and sign in with username `judge` and the local
example password above. Stop the container with Ctrl+C. The container runs as UID
10001 under `tini`, and writes records under `/var/lib/accessproof/data` and
`/var/lib/accessproof/artifacts`. Without an attached volume, removing the
container removes those records.

The image explicitly copies source files and excludes local credentials,
environments, caches, and generated records from its build context. The
`requirements-hosted.txt` file pins direct package versions. The official
`mcr.microsoft.com/playwright/python:v1.63.0-noble` base contains the browsers and
Linux dependencies, and the Python Playwright package is pinned to the same
version. Transitive dependencies are not a complete lockfile.

## Other container hosts

The same image can run on another Linux container host with an HTTPS ingress.
Provide `ACCESSPROOF_PUBLIC_ORIGIN` as the exact public HTTPS origin,
`ACCESSPROOF_ALLOWED_HOSTS` as its hostname, `ACCESSPROOF_DEMO_PASSWORD`, and the
Nebius environment variables above. Set `PORT` to the host's HTTP port and keep one
worker and instance. Keep the demo auth requirement enabled.

Nebius Serverless Endpoints supports CPU-only custom containers and managed HTTPS
URLs, so it is another deployment option. It requires a published container image
and an AI Cloud project with Compute access. Its computing and storage resources
are billed using Compute pricing; Token Factory credits should not be assumed to
cover those resources. No Nebius Compute resources are created by these files.

## References

- [Render Docker deployment](https://render.com/docs/docker)
- [Render Blueprint fields and generated secrets](https://render.com/docs/blueprint-spec)
- [Render environment variables and secrets](https://render.com/docs/configure-environment-variables)
- [Render default environment variables](https://render.com/docs/environment-variables)
- [Render health checks](https://render.com/docs/health-checks)
- [Render Free limits](https://render.com/docs/free)
- [Render compute plans](https://render.com/docs/compute-plans)
- [Playwright Docker image and version matching](https://playwright.dev/python/docs/docker)
- [Playwright browser installation](https://playwright.dev/python/docs/browsers)
- [Nebius CPU/custom endpoint setup](https://docs.nebius.com/serverless/endpoints/manage)
- [Nebius Serverless pricing](https://docs.nebius.com/serverless/pricing-quotas)
