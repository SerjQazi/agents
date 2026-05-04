"""Isolated FastAPI app for Builder Agent."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from .config import settings
from .dashboard import render_dashboard, render_task_detail
from .logger import BuilderLogger
from .memory import seed_default_memory
from .models import ApplyResponse, ApprovalRequest, TaskCreate, TaskResponse
from .ollama_client import OllamaClient
from .patcher import StagingApplyError, StagingPatcher
from .planner import Planner
from .reports import ReportWriter
from .scanner import ScriptScanner
from .services import collect_service_inventory
from .storage import Storage


app = FastAPI(title=settings.app_name)
storage = Storage(settings.database_path)
logger = BuilderLogger(storage, settings.logs_dir)
scanner = ScriptScanner(settings)
ollama = OllamaClient(settings.ollama_url, settings.model)
planner = Planner(ollama)
report_writer = ReportWriter(settings.reports_dir)
patcher = StagingPatcher(settings)
seed_default_memory(storage, settings)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    data = {
        "tasks": storage.list_recent("tasks", 100),
        "logs": storage.list_recent("logs", 100),
        "findings": storage.list_recent("findings", 100),
        "reports": storage.list_recent("reports", 100),
        "memory_notes": storage.list_recent("memory_notes", 100),
        "service_inventory": collect_service_inventory(),
    }
    return HTMLResponse(render_dashboard(settings, data))


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "mode": "plan-only/read-only",
        "model": settings.model,
        "host": settings.host,
    }


@app.get("/tasks")
def list_tasks() -> list[dict]:
    return storage.list_recent("tasks", 100)


@app.get("/tasks/{task_id}/view", response_class=HTMLResponse)
def task_detail(task_id: str) -> HTMLResponse:
    detail = _task_detail(task_id)
    return HTMLResponse(render_task_detail(settings, detail))


@app.get("/logs")
def list_logs() -> list[dict]:
    return storage.list_recent("logs", 200)


@app.get("/memory")
def list_memory() -> list[dict]:
    return storage.list_recent("memory_notes", 200)


@app.get("/reports")
def list_reports() -> list[dict]:
    return storage.list_recent("reports", 100)


@app.get("/reports/{task_id}/view")
def view_report(task_id: str) -> FileResponse:
    report_path = (settings.reports_dir / f"{task_id}.md").resolve()
    reports_root = settings.reports_dir.resolve()
    if reports_root not in report_path.parents or not report_path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(report_path, media_type="text/markdown", filename=report_path.name)


@app.post("/tasks/{task_id}/approve")
def approve_task(task_id: str, request: ApprovalRequest | None = None) -> dict[str, str]:
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    storage.set_approval(task_id, "approved", request.note if request else None)
    logger.log("task_approved", "Task approved for staging-only apply.", task_id=task_id, details={"note": request.note if request else None})
    return {"task_id": task_id, "approval_status": "approved"}


@app.post("/tasks/{task_id}/reject")
def reject_task(task_id: str, request: ApprovalRequest | None = None) -> dict[str, str]:
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    storage.set_approval(task_id, "rejected", request.note if request else None)
    logger.log("task_rejected", "Task rejected; staging apply is blocked.", task_id=task_id, details={"note": request.note if request else None})
    return {"task_id": task_id, "approval_status": "rejected"}


@app.post("/tasks/{task_id}/send-to-coding-agent")
def send_task_to_coding_agent(task_id: str) -> dict:
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = {
        "prompt": task.get("prompt", ""),
        "script_path": task.get("script_path"),
        "source_task_id": task_id,
    }
    request = urllib.request.Request(
        "http://127.0.0.1:8020/tasks",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    logger.log("coding_agent_handoff_started", "Sending task to coding_agent.", task_id=task_id, details=payload)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8")
        logger.log("coding_agent_handoff_failed", detail, task_id=task_id, level="error")
        raise HTTPException(status_code=502, detail=detail) from error
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        logger.log("coding_agent_handoff_failed", str(error), task_id=task_id, level="error")
        raise HTTPException(status_code=502, detail=f"coding_agent unavailable: {error}") from error
    logger.log("coding_agent_handoff_completed", "coding_agent returned a planning response.", task_id=task_id, details=result)
    return result


@app.post("/tasks/{task_id}/apply", response_model=ApplyResponse)
def apply_task_to_staging(task_id: str) -> ApplyResponse:
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("approval_status") != "approved":
        logger.log("apply_blocked", "Apply blocked because task is not approved.", task_id=task_id, level="warning")
        raise HTTPException(status_code=409, detail="Task must be approved before staging apply.")

    plan = storage.get_plan(task_id)
    if not plan:
        raise HTTPException(status_code=409, detail="Task has no stored plan.")

    findings = storage.list_for_task("findings", task_id)
    patches = patcher.build_patch_specs(task, plan)
    for patch in patches:
        storage.add_patch(
            task_id,
            str(patch.get("source_path", "")),
            str(patch.get("target_path", "")),
            str(patch.get("action", "")),
            str(patch.get("content", "")),
            "pending",
        )

    logger.log("staging_apply_started", "Starting controlled staging-only apply.", task_id=task_id, details={"patch_count": len(patches)})
    try:
        staging_path, diff_text, validation, rollback_notes = patcher.apply_to_staging(task, plan, findings, patches)
    except StagingApplyError as error:
        storage.add_apply_run(task_id, "staging_only", "failed", settings.staging_dir / task_id, "", {"status": "failed", "error": str(error)}, "No live files changed.")
        logger.log("staging_apply_failed", str(error), task_id=task_id, level="error")
        raise HTTPException(status_code=409, detail=str(error)) from error

    status = str(validation.get("status", "passed"))
    storage.add_apply_run(task_id, "staging_only", status, staging_path, diff_text, validation, rollback_notes)
    logger.log(
        "staging_apply_completed",
        "Controlled staging-only apply completed.",
        task_id=task_id,
        details={"staging_path": str(staging_path), "validation_status": status},
    )
    return ApplyResponse(
        task_id=task_id,
        status=status,
        staging_path=str(staging_path),
        validation=validation,
        diff_preview=diff_text,
    )


@app.post("/tasks", response_model=TaskResponse)
def create_task(request: TaskCreate) -> TaskResponse:
    task_id = f"builder-{uuid4().hex[:12]}"
    model = request.model or settings.model
    storage.create_task(task_id, request.prompt, request.script_path, model)
    logger.log(
        "task_created",
        "Task intake accepted in plan-only mode.",
        task_id=task_id,
        details={"script_path": request.script_path, "model": model},
    )

    try:
        scan = scanner.scan(request.script_path)
    except (FileNotFoundError, ValueError) as error:
        logger.log("scan_failed", str(error), task_id=task_id, level="error")
        storage.update_task(task_id, "failed", str(error))
        raise HTTPException(status_code=400, detail=str(error)) from error

    logger.log(
        "scan_completed",
        "Read-only script scan completed.",
        task_id=task_id,
        details={
            "files_read": scan.get("text_files_read", []),
            "sql_files": scan.get("sql_files", []),
            "script_path": scan.get("script_path"),
        },
    )
    storage.add_findings(task_id, scan.get("findings", []))
    memory_notes = storage.list_recent("memory_notes", 100)
    plan, raw_model_response, ollama_error = planner.build_plan(request.prompt, scan, memory_notes, model)
    if ollama_error:
        logger.log("ollama_unavailable", ollama_error, task_id=task_id, level="warning", details={"model": model})
    else:
        logger.log("ollama_plan_completed", "Ollama returned plan text.", task_id=task_id, details={"model": model})

    report_path = report_writer.write_task_report(task_id, request.prompt, model, scan, plan, raw_model_response)
    storage.save_plan(task_id, plan, raw_model_response)
    storage.add_report(task_id, report_path, f"Builder Agent Report {task_id}")
    storage.update_task(task_id, "completed", str(plan.get("summary", "")))
    logger.log(
        "task_completed",
        "Plan-only task completed; no files were modified.",
        task_id=task_id,
        details={"report_path": str(report_path), "model": model},
    )

    return TaskResponse(
        task_id=task_id,
        status="completed",
        summary=str(plan.get("summary", "")),
        report_path=str(report_path),
        findings=scan.get("findings", []),
        plan=plan,
    )


def _task_detail(task_id: str) -> dict:
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task": task,
        "plan": storage.get_plan(task_id),
        "findings": storage.list_for_task("findings", task_id),
        "reports": storage.list_for_task("reports", task_id),
        "logs": storage.list_for_task("logs", task_id),
        "patches": storage.list_for_task("patches", task_id),
        "apply_runs": storage.list_for_task("apply_runs", task_id),
        "approvals": storage.list_for_task("approvals", task_id),
    }
