"""FastAPI entrypoint for the isolated coding_agent service."""

from __future__ import annotations

import json
import difflib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .config import AGENTS_ROOT, INCOMING_PATH, REPORTS_PATH
from .planner import generate_plan
from .scanner import scan_folder
from apps.shared_layout import render_layout


app = FastAPI(title="coding_agent")


class TaskRequest(BaseModel):
    prompt: str
    script_path: str | None = None
    source_task_id: str | None = None
    planner_json: dict[str, Any] | None = None
    mapping_rules: dict[str, str] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "coding_agent"}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    content = """
      <section class="panel"><h2>Coding Agent</h2><p>Local-only FiveM compatibility staging worker.</p></section>
      <section class="panel"><h2>Health</h2><p><code>GET /health</code></p></section>
      <section class="panel"><h2>Available Endpoints</h2><ul><li><code>POST /tasks</code> accepts prompt, script_path, source_task_id, planner_json, and mapping_rules.</li><li><code>GET /staging/{task_id}</code> previews staged output.</li><li><code>GET /review/{task_id}</code> shows the human code review.</li><li><code>GET /reports/daily</code> shows today's digest.</li></ul></section>
      <section class="panel"><h2>Safety Mode</h2><p>Planning and staging only. No SQL execution, no live apply, no Git push, no FiveM restart, and no qb-core edits.</p></section>
    """
    return HTMLResponse(render_layout("Coding Agent", "coding", content, _shared_page_css(), subtitle="Staged code generation and review."))


@app.post("/tasks")
def create_task(request: TaskRequest) -> dict[str, object]:
    task_id = f"coding-{uuid4().hex[:12]}"
    try:
        files = _scan_requested_path(request.script_path)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    planner_json = request.planner_json or _extract_planner_json(request.prompt)
    mapping_rules = request.mapping_rules or _default_mapping_rules()
    plan = generate_plan({"prompt": request.prompt, "files": files, "source_task_id": request.source_task_id, "planner_json": planner_json})
    staging_path, changed_files, patch_notes = _write_staging_output(task_id, request, files, plan)
    review = _write_review_report(task_id, staging_path, request, planner_json, changed_files)
    report_path = staging_path / "PATCH_NOTES.md"
    return {
        "task_id": task_id,
        "status": "staged",
        "agent": "coding_agent",
        "summary": "Staged coding plan created. No live files were modified.",
        "report_path": str(report_path),
        "staging_path": str(staging_path),
        "changed_files": changed_files,
        "patch_notes": patch_notes,
        "review_report": review,
        "review_url": f"/review/{task_id}",
        "source_task_id": request.source_task_id,
        "staging_preview_url": f"/staging/{task_id}",
    }


@app.get("/staging/{task_id}", response_class=HTMLResponse)
def staging_preview(task_id: str) -> HTMLResponse:
    staging_path = _safe_staging_task_path(task_id)
    manifest_path = staging_path / "STAGING_SUMMARY.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Staging task not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    diff_text = (staging_path / "DIFF_PREVIEW.patch").read_text(encoding="utf-8", errors="ignore") if (staging_path / "DIFF_PREVIEW.patch").is_file() else ""
    changed_files = manifest.get("changed_files", [])
    file_rows = "".join(f"<li><code>{_esc(item)}</code></li>" for item in changed_files) or "<li>No changed files.</li>"
    content = f"""
      <section class="panel"><div class="head"><h2>Staging Preview</h2><a class="button" href="/review/{_esc(task_id)}">View Review</a></div><div class="body summary">{_esc(manifest.get("summary", ""))}</div></section>
      <section class="panel"><div class="head"><h2>Changed Files</h2><code>{_esc(str(manifest.get("staging_path", "")))}</code></div><div class="body"><ul>{file_rows}</ul></div></section>
      <section class="panel"><div class="head"><h2>Diff Preview</h2><span>side-by-side source patch</span></div><div class="body diff"><pre>{_esc(diff_text)}</pre><pre>{_esc(_diff_summary(diff_text))}</pre></div></section>
    """
    return HTMLResponse(render_layout("Staging Preview", "staging", content, _shared_page_css(), subtitle=task_id))


def _write_review_report(
    task_id: str,
    staging_path: Path,
    request: TaskRequest,
    planner_json: dict[str, Any],
    changed_files: list[str],
) -> dict[str, Any]:
    diff_text = (staging_path / "DIFF_PREVIEW.patch").read_text(encoding="utf-8", errors="ignore") if (staging_path / "DIFF_PREVIEW.patch").is_file() else ""
    task_name = _review_task_name(request, planner_json)
    changes_made = _plain_changes(planner_json, diff_text, changed_files)
    risk_notes = _risk_notes(planner_json, changed_files, diff_text)
    risk_level = _review_risk_level(planner_json, changed_files, diff_text)
    status = _review_status(risk_level, changed_files, diff_text)
    summary = _review_summary(task_name, changes_made, risk_notes)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    review = {
        "task_id": task_id,
        "task_name": task_name,
        "summary": summary,
        "what_changed": changes_made,
        "files_modified": _review_files_modified(changed_files),
        "risk_level": risk_level,
        "changes_made": changes_made,
        "risk_notes": risk_notes,
        "status": status,
        "notes": _human_explanation(task_name, changes_made, risk_notes, status),
        "human_explanation": _human_explanation(task_name, changes_made, risk_notes, status),
        "code_snippets": _review_code_snippets(diff_text),
        "created_at": now,
    }
    review_path = _review_report_path(task_id, create=True)
    review_path.write_text(json.dumps(review, indent=2, sort_keys=True), encoding="utf-8")
    (staging_path / "review_report.json").write_text(json.dumps(review, indent=2, sort_keys=True), encoding="utf-8")
    return review


def _review_task_name(request: TaskRequest, planner_json: dict[str, Any]) -> str:
    if request.script_path:
        return Path(request.script_path).name.replace("-", " ").replace("_", " ").title()
    framework = planner_json.get("framework_detected") or "Script"
    return f"{framework} Script Review"


def _plain_changes(planner_json: dict[str, Any], diff_text: str, changed_files: list[str]) -> list[str]:
    changes: list[str] = []
    issues = planner_json.get("issues", []) if isinstance(planner_json, dict) else []
    issue_types = {str(issue.get("type", "")) for issue in issues}
    dependencies = set(planner_json.get("dependencies_detected", [])) if isinstance(planner_json, dict) else set()
    framework = str(planner_json.get("framework_detected", "")) if isinstance(planner_json, dict) else ""
    if framework == "ESX" or "framework" in issue_types:
        changes.append("Replaced parts of the ESX player system with QBCore-friendly equivalents.")
    if "mysql-async" in dependencies or "database" in issue_types or "MySQL.Async" in diff_text:
        changes.append("Updated old database calls toward the newer oxmysql style.")
    if "ox_target" in dependencies or "targeting" in issue_types or "qb-target" in diff_text:
        changes.append("Adjusted targeting references so the script points toward qb-target.")
    if "inventory" in issue_types:
        changes.append("Prepared inventory usage for QBCore-compatible inventory handling.")
    staged_source_files = [path for path in changed_files if path.startswith("files/")]
    if staged_source_files:
        changes.append(f"Created staged copies of {len(staged_source_files)} script file(s) for review.")
    if not changes:
        changes.append("Created a staged review note because no automatic source replacement was safe.")
    return _dedupe(changes)


def _risk_notes(planner_json: dict[str, Any], changed_files: list[str], diff_text: str) -> list[str]:
    notes: list[str] = []
    risk_level = str(planner_json.get("risk_level", "low")) if isinstance(planner_json, dict) else "low"
    issues = planner_json.get("issues", []) if isinstance(planner_json, dict) else []
    if risk_level == "high":
        notes.append("Planner marked this as high risk, so a person should review it before use.")
    if any(issue.get("type") == "database" for issue in issues):
        notes.append("Database behavior changed or was detected. No SQL was run, but the query logic needs human review.")
    if any("fxmanifest" in path for path in changed_files):
        notes.append("The resource manifest was staged, so dependencies should be checked before starting the resource.")
    if "AGENT FIX START" not in diff_text:
        notes.append("No wrapped code edit appeared in the diff, so the staged output may be guidance only.")
    if not notes:
        notes.append("No major warning was detected, but staged files still need review before use.")
    return _dedupe(notes)


def _review_risk_level(planner_json: dict[str, Any], changed_files: list[str], diff_text: str) -> str:
    risk_level = str(planner_json.get("risk_level", "low")) if isinstance(planner_json, dict) else "low"
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "low"
    if any(path.endswith("INTEGRATION_GUIDANCE.lua") for path in changed_files):
        risk_level = "medium" if risk_level == "low" else risk_level
    if "Database behavior changed" in " ".join(_risk_notes(planner_json, changed_files, diff_text)):
        risk_level = "medium" if risk_level == "low" else risk_level
    return risk_level


def _review_status(risk_level: str, changed_files: list[str], diff_text: str) -> str:
    if not changed_files:
        return "fail"
    if risk_level == "high" or "AGENT FIX START" not in diff_text:
        return "warning"
    return "pass"


def _review_summary(task_name: str, changes_made: list[str], risk_notes: list[str]) -> str:
    return f"{task_name} was converted into staged review files with {len(changes_made)} plain-English change note(s) and {len(risk_notes)} risk note(s)."


def _human_explanation(task_name: str, changes_made: list[str], risk_notes: list[str], status: str) -> str:
    change_text = " ".join(changes_made)
    risk_text = " ".join(risk_notes)
    if status == "pass":
        opening = "The staged changes look straightforward."
    elif status == "fail":
        opening = "The review could not confirm usable staged changes."
    else:
        opening = "The staged changes need a careful human review before use."
    return (
        f"{opening}\n\n"
        f"{task_name} was copied into a safe staging area. The live server files were not changed.\n\n"
        f"What changed: {change_text}\n\n"
        f"What to watch: {risk_text}"
    )


def _review_files_modified(changed_files: list[str]) -> list[str]:
    return [path for path in changed_files if path.startswith("files/")]


def _review_code_snippets(diff_text: str) -> list[str]:
    snippets = [line for line in diff_text.splitlines() if line.startswith("+") and "AGENT FIX" in line]
    return snippets[:8]


def _review_report_path(task_id: str, create: bool = False) -> Path:
    if not task_id.startswith("coding-") or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in task_id):
        raise HTTPException(status_code=400, detail="Invalid review task id")
    root = (REPORTS_PATH.parent / "reviews").resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    path = (root / f"{task_id}.json").resolve()
    if root != path.parent:
        raise HTTPException(status_code=400, detail="Invalid review path")
    return path


def _load_review_report(task_id: str) -> dict[str, Any] | None:
    review_path = _review_report_path(task_id)
    if review_path.is_file():
        return json.loads(review_path.read_text(encoding="utf-8"))
    legacy_path = _safe_staging_task_path(task_id) / "review_report.json"
    if legacy_path.is_file():
        return json.loads(legacy_path.read_text(encoding="utf-8"))
    return None


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


@app.get("/review/{task_id}", response_class=HTMLResponse)
def review_page(task_id: str) -> HTMLResponse:
    review = _load_review_report(task_id)
    if not review:
        content = f"""
          <section class="panel">
            <div class="head"><h2>Review Not Ready</h2><span class="badge warning">Missing</span></div>
            <div class="body summary">No review has been saved for <code>{_esc(task_id)}</code> yet.</div>
          </section>
          <section class="panel">
            <div class="body">Run the Coding Agent task again or open the staging preview after the task finishes. No live server files were changed.</div>
          </section>
        """
        return HTMLResponse(render_layout("Code Review", "reviews", content, _shared_page_css(), subtitle="Review not found"), status_code=404)
    change_items = "".join(f"<li>{_esc(item)}</li>" for item in review.get("what_changed", review.get("changes_made", []))) or "<li>No changes were generated.</li>"
    risk_items = "".join(f"<li>{_esc(item)}</li>" for item in review.get("risk_notes", [])) or "<li>No major risks were detected.</li>"
    file_items = "".join(f"<li><code>{_esc(item)}</code></li>" for item in review.get("files_modified", [])) or "<li>No staged source files were changed.</li>"
    status = str(review.get("status", "warning"))
    risk_level = str(review.get("risk_level", "medium"))
    content = f"""
      <section class="panel"><div class="head"><h2>{_esc(review.get("task_name", "Code Review"))}</h2><span class="badge {status}">{_esc(status.title())}</span></div><div class="body summary">{_esc(review.get("summary", ""))}</div></section>
      <section class="panel"><div class="head"><h2>Changes Made</h2></div><div class="body"><ul>{change_items}</ul></div></section>
      <section class="panel"><div class="head"><h2>Files Modified</h2><span class="badge {_esc(risk_level)}">{_esc(risk_level.title())} Risk</span></div><div class="body"><ul>{file_items}</ul></div></section>
      <section class="panel"><div class="head"><h2>Risk Warnings</h2></div><div class="body"><ul>{risk_items}</ul></div></section>
      <section class="panel"><div class="head"><h2>Plain-English Explanation</h2></div><div class="body explanation">{_esc(review.get("notes", review.get("human_explanation", "")))}</div></section>
      <section class="panel"><div class="head"><h2>Links</h2></div><div class="body"><a class="button" href="/staging/{_esc(task_id)}">Back to staging preview</a></div></section>
    """
    return HTMLResponse(render_layout("Code Review", "reviews", content, _shared_page_css(), subtitle=task_id))


@app.get("/reports/daily", response_class=HTMLResponse)
def daily_digest() -> HTMLResponse:
    today = datetime.now(timezone.utc).date()
    reports = []
    reviews_root = (REPORTS_PATH.parent / "reviews").resolve()
    if reviews_root.is_dir():
        for review_path in sorted(reviews_root.glob("coding-*.json")):
            try:
                review = json.loads(review_path.read_text(encoding="utf-8"))
                created_at = datetime.fromisoformat(str(review.get("created_at", "")).replace("Z", "+00:00"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if created_at.date() == today:
                review["task_id"] = review.get("task_id") or review_path.stem
                reports.append(review)
    if reports:
        rows = "".join(
            "<section class='panel'>"
            f"<div class='head'><h2>{_esc(_human_time(report.get('created_at', '')))} - {_esc(report.get('task_name', 'Coding task'))}</h2><span class='badge {_esc(report.get('status', 'warning'))}'>{_esc(str(report.get('status', 'warning')).title())}</span></div>"
            f"<div class='body'><p>{_esc(report.get('summary', ''))}</p><p>{_esc(report.get('notes', report.get('human_explanation', '')))}</p><a class='button' href='/review/{_esc(report.get('task_id', ''))}'>Open review</a></div>"
            "</section>"
            for report in reports
        )
    else:
        rows = "<section class='panel'><div class='body'>No Coding Agent reviews have been created today.</div></section>"
    content = f"""
      <section class="panel"><div class="head"><h2>Daily Coding Digest</h2><span>{_esc(today.isoformat())}</span></div><div class="body summary">Readable timeline of today's staged coding tasks.</div></section>
      {rows}
    """
    return HTMLResponse(render_layout("Daily Digest", "daily", content, _shared_page_css(), subtitle="Readable timeline of staged coding tasks."))


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


def _write_staging_output(task_id: str, request: TaskRequest, files: list[str], plan: str) -> tuple[Path, list[str], list[str]]:
    staging_path = _safe_staging_task_path(task_id, create=True)
    staging_path.mkdir(parents=True, exist_ok=True)
    patch_plan_path = staging_path / "PATCH_NOTES.md"
    manifest_path = staging_path / "STAGING_SUMMARY.json"
    planner_json = request.planner_json or _extract_planner_json(request.prompt)
    mapping_rules = request.mapping_rules or _default_mapping_rules()
    patched_files, diff_text = _generate_patched_files(staging_path, request.script_path, files, planner_json, mapping_rules)
    diff_path = staging_path / "DIFF_PREVIEW.patch"
    diff_path.write_text(diff_text or "No text changes generated.\n", encoding="utf-8")
    changed_files = patched_files + ["PATCH_NOTES.md", "STAGING_SUMMARY.json", "DIFF_PREVIEW.patch"]
    patch_notes = [
        "Generated staging-only compatibility patches from Planner JSON.",
        "No live resources were modified.",
        "No SQL was executed.",
        "No Git push or server restart was run.",
        "Every generated source edit is wrapped with AGENT FIX START and AGENT FIX END markers.",
        "Review the plan before manually applying any code changes.",
    ]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    patch_plan_path.write_text(
        "\n".join(
            [
                f"# Coding Agent Staging Notes - {task_id}",
                "",
                f"Created: {now}",
                f"Source Planner Task: {request.source_task_id or 'none'}",
                f"Script Path: {request.script_path or 'none'}",
                "",
                "## Patch Notes",
                "",
                *[f"- {note}" for note in patch_notes],
                "",
                "## Generated Plan",
                "",
                plan,
                "",
                "## Planner JSON",
                "",
                json.dumps(planner_json, indent=2, sort_keys=True),
                "",
            ]
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "source_task_id": request.source_task_id,
                "script_path": request.script_path,
                "status": "staged",
                "summary": "Staged compatibility patch set created. No live files were modified.",
                "staging_path": str(staging_path),
                "changed_files": changed_files,
                "patch_notes": patch_notes,
                "planner_json": planner_json,
                "created_at": now,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return staging_path, changed_files, patch_notes


def _generate_patched_files(
    staging_path: Path,
    script_path: str | None,
    files: list[str],
    planner_json: dict[str, Any],
    mapping_rules: dict[str, str],
) -> tuple[list[str], str]:
    if not script_path:
        return [], ""
    source_root = _resolve_incoming_path(script_path)
    patched: list[str] = []
    diff_chunks: list[str] = []
    issue_files = {str(issue.get("file", "")) for issue in planner_json.get("issues", []) if issue.get("file")}
    for absolute in files:
        source = Path(absolute).resolve()
        if not source.is_file() or source_root not in source.parents and source != source_root:
            continue
        relative = source.relative_to(source_root)
        if issue_files and relative.as_posix() not in issue_files and not _contains_mapping(source, mapping_rules):
            continue
        if source.suffix.lower() not in {".lua", ".js", ".json", ".cfg", ".html", ".css", ".txt", ".md"} and source.name not in {"fxmanifest.lua", "__resource.lua"}:
            continue
        original = source.read_text(encoding="utf-8", errors="ignore")
        modified, notes = _apply_mapping_rules(original, mapping_rules)
        if modified == original:
            continue
        modified = _wrap_agent_fix(modified, notes)
        target = (staging_path / "files" / relative).resolve()
        staging_root = staging_path.resolve()
        if staging_root not in target.parents:
            raise HTTPException(status_code=500, detail="Unsafe staging path blocked")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(modified, encoding="utf-8")
        patched_path = target.relative_to(staging_path).as_posix()
        patched.append(patched_path)
        diff_chunks.extend(
            difflib.unified_diff(
                original.splitlines(),
                modified.splitlines(),
                fromfile=f"original/{relative.as_posix()}",
                tofile=f"staged/{patched_path}",
                lineterm="",
            )
        )
    if not patched:
        guidance = _wrap_agent_fix("-- No direct mapping replacements were generated.\n", ["Review Planner issues manually; no source text matched automated mapping rules."])
        target = staging_path / "files" / "INTEGRATION_GUIDANCE.lua"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(guidance, encoding="utf-8")
        patched.append("files/INTEGRATION_GUIDANCE.lua")
        diff_chunks.extend(
            difflib.unified_diff(
                [],
                guidance.splitlines(),
                fromfile="original/INTEGRATION_GUIDANCE.lua",
                tofile="staged/files/INTEGRATION_GUIDANCE.lua",
                lineterm="",
            )
        )
    return patched, "\n".join(diff_chunks) + "\n"


def _apply_mapping_rules(content: str, mapping_rules: dict[str, str]) -> tuple[str, list[str]]:
    modified = content
    notes: list[str] = []
    for source, target in sorted(mapping_rules.items(), key=lambda item: len(item[0]), reverse=True):
        if source in modified:
            modified = modified.replace(source, target)
            notes.append(f"Mapped {source} to {target}.")
    return modified, notes


def _contains_mapping(path: Path, mapping_rules: dict[str, str]) -> bool:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(source in content for source in mapping_rules)


def _wrap_agent_fix(content: str, notes: list[str]) -> str:
    explanation = "\n".join(f"-- {note}" for note in notes) or "-- Staged compatibility update generated from Planner JSON."
    return "\n".join(["-- AGENT FIX START", explanation, "-- AGENT FIX END", content])


def _resolve_incoming_path(script_path: str) -> Path:
    raw_path = Path(script_path)
    target = raw_path.resolve() if raw_path.is_absolute() else (INCOMING_PATH.parent / raw_path).resolve()
    incoming_root = INCOMING_PATH.resolve()
    if target != incoming_root and incoming_root not in target.parents:
        raise HTTPException(status_code=400, detail="script_path must stay under /home/agentzero/agents/incoming")
    if not target.exists():
        raise HTTPException(status_code=400, detail=f"script_path not found: {target}")
    return target


def _safe_staging_task_path(task_id: str, create: bool = False) -> Path:
    if not task_id.startswith("coding-") or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in task_id):
        raise HTTPException(status_code=400, detail="Invalid staging task id")
    path = (AGENTS_ROOT / "staging" / task_id).resolve()
    staging_root = (AGENTS_ROOT / "staging").resolve()
    if staging_root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid staging path")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _extract_planner_json(prompt: str) -> dict[str, Any]:
    marker = "Planner JSON:"
    if marker not in prompt:
        return {}
    raw = prompt.split(marker, 1)[1].strip()
    start = raw.find("{")
    if start < 0:
        return {}
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(raw[start:])
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _default_mapping_rules() -> dict[str, str]:
    return {
        "local ESX = exports['es_extended']:getSharedObject()": "local QBCore = exports['qb-core']:GetCoreObject()",
        "exports['es_extended']:getSharedObject()": "exports['qb-core']:GetCoreObject()",
        "esx:getSharedObject": "exports['qb-core']:GetCoreObject()",
        "ESX.GetPlayerFromId": "QBCore.Functions.GetPlayer",
        "ESX.ShowNotification": "QBCore.Functions.Notify",
        "ESX.PlayerData": "QBCore.PlayerData",
        "ESX.GetPlayerData": "QBCore.Functions.GetPlayerData",
        "player.identifier": "player.PlayerData.citizenid",
        "mysql-async": "oxmysql",
        "MySQL.Async": "MySQL",
        "exports.ox_target": "exports['qb-target']",
        "exports['ox_target']": "exports['qb-target']",
        "ox_target": "qb-target",
        "xPlayer.addInventoryItem": "Player.Functions.AddItem",
        "xPlayer.removeInventoryItem": "Player.Functions.RemoveItem",
    }


def _diff_summary(diff_text: str) -> str:
    lines = [line for line in diff_text.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
    return "\n".join(lines[:400]) or "No line-level changes."


def _esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _shared_page_css() -> str:
    return """
.panel{border:1px solid #253850;background:#121f32;border-radius:8px;overflow:hidden}
.head{padding:14px 16px;border-bottom:1px solid #253850;background:#0f1b2c;display:flex;justify-content:space-between;gap:12px;align-items:center}
.body{padding:16px;overflow-wrap:anywhere;line-height:1.55}
.summary{color:#9fb1c7}
.explanation{white-space:pre-wrap}
.button{display:inline-flex;align-items:center;min-height:36px;padding:8px 12px;border:1px solid #31506f;border-radius:8px;background:#10243a;color:#edf5ff;text-decoration:none;font-weight:850}
.button:hover{background:#163453}
.badge{display:inline-flex;padding:4px 9px;border-radius:999px;border:1px solid #31506f;background:#0b1422;color:#9fdcff;font-weight:850;font-size:12px}
.badge.pass{color:#5eead4;border-color:rgba(94,234,212,.35)}
.badge.warning{color:#fbbf24;border-color:rgba(251,191,36,.38)}
.badge.fail{color:#fb7185;border-color:rgba(251,113,133,.35)}
.badge.low{color:#5eead4;border-color:rgba(94,234,212,.35)}
.badge.medium{color:#fbbf24;border-color:rgba(251,191,36,.38)}
.badge.high{color:#fb7185;border-color:rgba(251,113,133,.35)}
li{margin:7px 0}
"""


def _human_time(value: object) -> str:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.strftime('%B')} {dt.day}, {hour}:{dt.strftime('%M')} {dt.strftime('%p')}"
