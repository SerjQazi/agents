"""Isolated FastAPI app for Planner Agent."""

from __future__ import annotations

import json
import re
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from .config import settings
from .dashboard import render_dashboard, render_task_detail
from .logger import PlannerLogger
from .memory import seed_default_memory
from .models import ApplyResponse, ApprovalRequest, TaskCreate, TaskResponse, UploadCompleteRequest, UploadStartRequest
from .ollama_client import OllamaClient
from .patcher import StagingApplyError, StagingPatcher
from .planner import Planner
from .reports import ReportWriter
from .scanner import ScriptScanner
from .services import collect_service_inventory
from .storage import Storage


app = FastAPI(title=settings.app_name)
storage = Storage(settings.database_path)
logger = PlannerLogger(storage, settings.logs_dir)
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


@app.post("/uploads/start")
def start_upload(request: UploadStartRequest) -> dict[str, str]:
    title = _task_title(request.title or request.prompt or "Uploaded script")
    task_name = _safe_task_name(title)
    destination = _unique_incoming_path(task_name)
    destination.mkdir(parents=True, exist_ok=False)
    metadata = {
        "title": title,
        "description": request.description or request.prompt or "Uploaded files staged for Planner review.",
        "prompt": request.prompt or f"Review uploaded script folder {destination.name} and create a compatibility plan.",
        "model": request.model or settings.model,
    }
    (destination / ".planner-upload.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    logger.log("upload_started", "Upload area created.", details={"destination": str(destination)})
    return {"upload_id": destination.name, "task_name": destination.name, "incoming_path": str(destination)}


@app.put("/uploads/{upload_id}/files")
async def upload_file(
    upload_id: str,
    request: Request,
    x_relative_path: str | None = Header(default=None),
) -> dict[str, str]:
    destination = _incoming_upload_path(upload_id)
    relative_path = _safe_relative_path(x_relative_path or "upload.bin")
    target = (destination / relative_path).resolve()
    if destination.resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid upload path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await request.body())
    return {"status": "stored", "path": str(target)}


@app.post("/uploads/{upload_id}/complete", response_model=TaskResponse)
def complete_upload(upload_id: str, request: UploadCompleteRequest) -> TaskResponse:
    destination = _incoming_upload_path(upload_id)
    metadata_path = destination / ".planner-upload.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    title = _task_title(request.title or metadata.get("title") or upload_id)
    description = request.description or metadata.get("description") or "Uploaded files staged for Planner review."
    prompt = request.prompt or metadata.get("prompt") or f"Review uploaded script folder {destination.name} and create a compatibility plan."
    model = request.model or metadata.get("model") or settings.model

    extracted = _extract_zip_uploads(destination)
    if extracted:
        logger.log("upload_zip_extracted", "ZIP upload extracted into incoming task folder.", details={"files": extracted, "destination": str(destination)})

    response = _create_task(
        prompt=prompt,
        title=title,
        description=description,
        script_path=str(destination),
        model=model,
    )
    logger.log("upload_completed", "Upload converted into Planner task.", task_id=response.task_id, details={"destination": str(destination)})
    return response


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


@app.post("/tasks/{task_id}/generate-fix-plan")
def generate_fix_plan(task_id: str) -> dict:
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    plan = storage.get_plan(task_id)
    if not plan:
        raise HTTPException(status_code=409, detail="Task has no stored plan.")
    analysis = plan.get("integration_analysis") or {}
    logger.log("fix_plan_generated", "Structured integration fix plan prepared.", task_id=task_id, details=analysis)
    return {
        "task_id": task_id,
        "status": "ready",
        "integration_analysis": analysis,
        "mapping_rules": plan.get("mapping_rules", {}),
        "recommended_actions": analysis.get("recommended_actions", []),
    }


@app.post("/tasks/{task_id}/send-to-coding-agent")
def send_task_to_coding_agent(task_id: str) -> dict:
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    plan = storage.get_plan(task_id)
    payload = {
        "prompt": _plan_prompt(task, plan),
        "script_path": task.get("script_path"),
        "source_task_id": task_id,
        "planner_json": plan.get("integration_analysis") if plan else None,
        "mapping_rules": plan.get("mapping_rules") if plan else {},
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
    return _create_task(
        prompt=request.prompt,
        title=request.title,
        description=request.description,
        script_path=request.script_path,
        model=request.model or settings.model,
    )


def _create_task(prompt: str, title: str | None, description: str | None, script_path: str | None, model: str) -> TaskResponse:
    task_id = f"planner-{uuid4().hex[:12]}"
    title = _task_title(title or prompt)
    description = (description or prompt).strip()
    storage.create_task(task_id, prompt, script_path, model, title, description)
    logger.log(
        "task_created",
        "Task intake accepted in plan-only mode.",
        task_id=task_id,
        details={"title": title, "script_path": script_path, "model": model},
    )

    try:
        scan = scanner.scan(script_path)
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
    plan, raw_model_response, ollama_error = planner.build_plan(prompt, scan, memory_notes, model)
    if ollama_error:
        logger.log("ollama_unavailable", ollama_error, task_id=task_id, level="warning", details={"model": model})
    else:
        logger.log("ollama_plan_completed", "Ollama returned plan text.", task_id=task_id, details={"model": model})

    report_path = report_writer.write_task_report(task_id, prompt, model, scan, plan, raw_model_response)
    storage.save_plan(task_id, plan, raw_model_response)
    storage.add_report(task_id, report_path, title)
    storage.update_task(task_id, "ready", str(plan.get("summary", "")))
    logger.log(
        "task_completed",
        "Plan-only task completed; no files were modified.",
        task_id=task_id,
        details={"report_path": str(report_path), "model": model},
    )

    return TaskResponse(
        task_id=task_id,
        title=title,
        description=description,
        status="ready",
        summary=str(plan.get("summary", "")),
        report_path=str(report_path),
        staging_path=None,
        findings=scan.get("findings", []),
        plan=plan,
        integration_analysis=plan.get("integration_analysis", {}),
    )


def _task_title(value: str) -> str:
    text = " ".join(value.strip().split())
    if not text:
        return "Planner task"
    sentence = re.split(r"[.!?\n]", text, maxsplit=1)[0].strip()
    words = sentence.split()[:10]
    return " ".join(words)[:90] or "Planner task"


def _safe_task_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return (slug or f"upload-{uuid4().hex[:8]}")[:80]


def _unique_incoming_path(task_name: str) -> Path:
    base = settings.incoming_dir / task_name
    if not base.exists():
        return base
    for index in range(2, 1000):
        candidate = settings.incoming_dir / f"{task_name}-{index}"
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=409, detail="Could not allocate incoming upload path.")


def _incoming_upload_path(upload_id: str) -> Path:
    safe_id = _safe_task_name(upload_id)
    path = (settings.incoming_dir / safe_id).resolve()
    incoming_root = settings.incoming_dir.resolve()
    if path != incoming_root and incoming_root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid upload id.")
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Upload not found.")
    return path


def _safe_relative_path(value: str) -> Path:
    clean = value.replace("\\", "/").lstrip("/")
    parts = [part for part in clean.split("/") if part and part not in {".", ".."}]
    if not parts:
        raise HTTPException(status_code=400, detail="Invalid file path.")
    return Path(*parts)


def _extract_zip_uploads(destination: Path) -> list[str]:
    extracted: list[str] = []
    for archive in destination.rglob("*.zip"):
        extract_root = destination / archive.stem
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zip_file:
            for member in zip_file.infolist():
                member_path = _safe_relative_path(member.filename)
                target = (extract_root / member_path).resolve()
                if extract_root.resolve() not in target.parents and target != extract_root.resolve():
                    continue
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                extracted.append(str(target))
    return extracted


def _plan_prompt(task: dict, plan: dict | None) -> str:
    if not plan:
        return str(task.get("prompt", ""))
    sections = [
        f"Implement from Planner Agent task {task.get('id')}: {task.get('title') or task.get('prompt')}",
        "",
        "Summary:",
        str(plan.get("summary", "")),
        "",
        "Planner JSON:",
        json.dumps(plan.get("integration_analysis", {}), indent=2, sort_keys=True),
        "",
        "Patch plan:",
        "\n".join(f"- {item}" for item in plan.get("patch_plan_json", [])),
        "",
        "Files Planner expects may change:",
        "\n".join(f"- {item}" for item in plan.get("files_json", [])),
        "",
        "Test checklist:",
        "\n".join(f"- {item}" for item in plan.get("test_checklist_json", [])),
        "",
        "Safety: stage output only; do not modify live resources, run SQL, edit qb-core, restart services, or push Git.",
    ]
    return "\n".join(sections)


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
