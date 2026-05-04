"""FastAPI entrypoint for the isolated coding_agent service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .config import INCOMING_PATH, REPORTS_PATH, STAGING_PATH
from .planner import generate_plan
from .scanner import scan_folder


app = FastAPI(title="coding_agent")


class TaskRequest(BaseModel):
    prompt: str
    script_path: str | None = None
    source_task_id: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "coding_agent"}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>coding_agent</title>
<style>
body{margin:0;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0d1726;color:#edf5ff}
main{max-width:880px;margin:0 auto;padding:28px;display:grid;gap:16px}
.card{border:1px solid #253850;background:#121f32;border-radius:10px;padding:18px}
code{background:#08111f;border:1px solid #253850;border-radius:6px;padding:2px 6px}
li{margin:6px 0}
</style></head>
<body><main>
<section class="card"><h1>coding_agent</h1><p>Local-only FiveM compatibility planning worker.</p></section>
<section class="card"><h2>Health</h2><p><code>GET /health</code></p></section>
<section class="card"><h2>Available Endpoints</h2><ul><li><code>POST /tasks</code> accepts prompt, script_path, and source_task_id.</li></ul></section>
<section class="card"><h2>Safety Mode</h2><p>Planning and staging only. No SQL execution, no live apply, no Git push, no FiveM restart, and no qb-core edits.</p></section>
</main></body></html>"""
    )


@app.post("/tasks")
def create_task(request: TaskRequest) -> dict[str, str | None]:
    task_id = f"coding-{uuid4().hex[:12]}"
    try:
        files = _scan_requested_path(request.script_path)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    plan = generate_plan({"prompt": request.prompt, "files": files, "source_task_id": request.source_task_id})
    report_path = _write_report(task_id, request, files, plan)
    return {
        "task_id": task_id,
        "status": "completed",
        "agent": "coding_agent",
        "summary": "Placeholder compatibility plan created. No files were modified.",
        "report_path": str(report_path),
    }


def _scan_requested_path(script_path: str | None) -> list[str]:
    if not script_path:
        return []
    raw_path = Path(script_path)
    if raw_path.is_absolute():
        target = raw_path.resolve()
    else:
        target = (INCOMING_PATH.parent / raw_path).resolve()
    incoming_root = INCOMING_PATH.resolve()
    if target != incoming_root and incoming_root not in target.parents:
        raise ValueError("script_path must stay under /home/agentzero/agents/incoming")
    return scan_folder(target)


def _write_report(task_id: str, request: TaskRequest, files: list[str], plan: str) -> Path:
    REPORTS_PATH.mkdir(parents=True, exist_ok=True)
    STAGING_PATH.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_PATH / f"{task_id}.md"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report_path.write_text(
        "\n".join(
            [
                f"# coding_agent Compatibility Plan - {task_id}",
                "",
                f"Created: {now}",
                f"Source Builder Task: {request.source_task_id or 'none'}",
                f"Script Path: {request.script_path or 'none'}",
                "",
                "## Safety",
                "",
                "- Planning/staging only.",
                "- No SQL was run.",
                "- No FiveM live resources were modified.",
                "- No Git push was run.",
                "- qb-core edits remain blocked.",
                "",
                "## Prompt",
                "",
                request.prompt,
                "",
                "## Scan",
                "",
                f"Files found: {len(files)}",
                "",
                "## Plan",
                "",
                plan,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report_path
