import asyncio
from contextlib import asynccontextmanager
import inspect
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings, get_settings
from .schemas import RunRequest, SCENARIOS
from .store import RunStore, now


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    store = RunStore(settings.data_dir / "accessproof.sqlite3")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.recover()
        app.state.jobs = set()
        app.state.run_lock = asyncio.Semaphore(1)
        yield
        for task in list(app.state.jobs):
            task.cancel()
        await asyncio.gather(*list(app.state.jobs), return_exceptions=True)

    app = FastAPI(title="AccessProof", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    allowed_hosts = [value.strip() for value in os.getenv("ACCESSPROOF_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if value.strip()]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    def get_run(run_id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise HTTPException(404, "Run not found")
        document = store.get(run_id)
        if document is None:
            raise HTTPException(404, "Run not found")
        return document

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "AccessProof", "version": "0.1.0", "live_ready": bool(settings.api_key), "model": settings.model}

    @app.get("/api/config")
    async def config():
        return {"model": settings.model, "live_ready": bool(settings.api_key), "max_steps": settings.max_steps, "scenarios": SCENARIOS}

    @app.get("/api/runs")
    async def list_runs():
        result = []
        for document in store.list():
            document["steps_count"] = len(document.get("steps", []))
            document.pop("steps", None)
            result.append(document)
        return result

    async def execute(document: dict, origin: str):
        from .model import LivePlanner, OfflinePlanner, PlannerError
        from .runner import run_browser

        planner = None
        try:
            async with app.state.run_lock:
                store.update(document["id"], lambda current: current.update(status="running"))
                planner = LivePlanner(api_key=settings.api_key, model=settings.model, base_url=settings.base_url) if document["mode"] == "live" else OfflinePlanner()

                async def decide(observation: dict):
                    observation["scenario"] = document["scenario"]
                    decision = await planner.decide(observation)
                    store.update(document["id"], lambda current: current.update(
                        model_calls=getattr(planner, "calls_made", 0),
                        token_usage=getattr(planner, "total_usage", {}),
                    ))
                    return decision

                async def emit(event: dict):
                    store.update(document["id"], lambda current: current["steps"].append(event))

                result = await run_browser(
                    run_id=document["id"],
                    url=f"{origin}/demo/{document['scenario']}",
                    goal=document["goal"],
                    artifacts_dir=settings.artifacts_dir / document["id"],
                    decide=decide,
                    emit=emit,
                    max_steps=settings.max_steps,
                    allowed_origin=origin,
                    expected_text=document["expected_text"],
                )
                result.pop("steps", None)
                store.update(document["id"], lambda current: current.update(result))
        except asyncio.CancelledError:
            store.update(document["id"], lambda current: current.update(status="error", error="The run stopped when the server restarted."))
            raise
        except PlannerError as error:
            # The model adapter deliberately exposes only safe public messages.
            message = getattr(error, "message", str(error))
            store.update(document["id"], lambda current: current.update(status="error", error=message))
        except Exception as error:
            message = f"Run stopped ({type(error).__name__}). Check that Chromium is installed: python -m playwright install chromium"
            store.update(document["id"], lambda current: current.update(status="error", error=message))
        finally:
            if planner is not None:
                store.update(document["id"], lambda current: current.update(
                    model_calls=getattr(planner, "calls_made", 0),
                    token_usage=getattr(planner, "total_usage", {}),
                ))
                for name in ("aclose", "close"):
                    closer = getattr(planner, name, None)
                    if closer:
                        result = closer()
                        if inspect.isawaitable(result):
                            await result
                        break

    @app.post("/api/runs", status_code=201)
    async def start_run(spec: RunRequest, request: Request):
        origin = str(request.base_url).rstrip("/")
        request_origin = request.headers.get("origin")
        if request_origin and request_origin.rstrip("/") != origin:
            raise HTTPException(403, "Open AccessProof and start the test from its dashboard.")
        if spec.mode == "live" and not settings.api_key:
            raise HTTPException(503, "Add your Nebius key with python scripts/configure_key.py, then restart the server.")
        if spec.parent_id:
            get_run(spec.parent_id)
        if len(app.state.jobs) >= 3:
            raise HTTPException(429, "Three runs are already active or queued. Wait for a run to finish.")
        timestamp = now()
        document = store.put({
            "id": uuid4().hex, "scenario": spec.scenario, "goal": spec.goal.strip(),
            "expected_text": spec.expected_text.strip(),
            "mode": spec.mode, "model": settings.model if spec.mode == "live" else "Offline fixture policy (no AI calls)",
            "status": "queued", "created_at": timestamp, "updated_at": timestamp,
            "parent_id": spec.parent_id, "steps": [], "report": None, "error": None,
            "model_calls": 0, "token_usage": {},
        })
        task = asyncio.create_task(execute(document, origin))
        app.state.jobs.add(task)
        task.add_done_callback(app.state.jobs.discard)
        return document

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str):
        return get_run(run_id)

    @app.get("/api/runs/{run_id}/report")
    async def report(run_id: str):
        document = get_run(run_id)
        return Response(json.dumps(document, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="accessproof-{run_id[:8]}.json"'})

    def artifact(run_id: str, name: str):
        get_run(run_id)
        path = settings.artifacts_dir / run_id / name
        if not path.is_file():
            raise HTTPException(404, "This artifact is available after browser execution finishes.")
        return path

    @app.get("/api/runs/{run_id}/reproducer")
    async def reproducer(run_id: str):
        return FileResponse(artifact(run_id, "reproducer.py"), filename=f"accessproof-{run_id[:8]}.py", media_type="text/x-python")

    @app.get("/api/runs/{run_id}/trace")
    async def trace(run_id: str):
        return FileResponse(artifact(run_id, "trace.zip"), filename=f"accessproof-{run_id[:8]}-trace.zip")

    @app.get("/demo/{scenario}")
    async def demo(scenario: str):
        if scenario not in {item["id"] for item in SCENARIOS}:
            raise HTTPException(404, "Example not found")
        return FileResponse(settings.root / "static" / "demo.html")

    app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")
    app.mount("/static", StaticFiles(directory=settings.root / "static"), name="static")

    @app.get("/")
    async def dashboard():
        return FileResponse(settings.root / "static" / "index.html")

    return app


app = create_app()
