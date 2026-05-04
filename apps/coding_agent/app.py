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

from .config import AGENTS_ROOT, INCOMING_PATH, REPORTS_PATH, STAGING_PATH
from .planner import generate_plan
from .scanner import scan_folder


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
<section class="card"><h2>Available Endpoints</h2><ul><li><code>POST /tasks</code> accepts prompt, script_path, source_task_id, planner_json, and mapping_rules.</li><li><code>GET /staging/{task_id}</code> previews staged output.</li></ul></section>
<section class="card"><h2>Safety Mode</h2><p>Planning and staging only. No SQL execution, no live apply, no Git push, no FiveM restart, and no qb-core edits.</p></section>
</main></body></html>"""
    )


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
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Staging Preview { _esc(task_id) }</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0d1726;color:#edf5ff}}
main{{max-width:1280px;margin:0 auto;padding:22px;display:grid;gap:16px}}
.panel{{border:1px solid #253850;background:#121f32;border-radius:8px;overflow:hidden}}
.head{{padding:14px 16px;border-bottom:1px solid #253850;background:#0f1b2c;display:flex;justify-content:space-between;gap:12px;align-items:center}}
.body{{padding:16px;overflow-wrap:anywhere}}
code,pre{{background:#08111f;border:1px solid #253850;border-radius:6px}}
code{{padding:2px 6px}}
pre{{margin:0;padding:12px;white-space:pre-wrap;overflow:auto;line-height:1.45}}
.diff{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.summary{{color:#9fb1c7}}
@media(max-width:800px){{.diff{{grid-template-columns:1fr}}}}
</style></head><body><main>
<section class="panel"><div class="head"><h1>Staging Preview</h1><code>{_esc(task_id)}</code></div><div class="body summary">{_esc(manifest.get("summary", ""))}</div></section>
<section class="panel"><div class="head"><h2>Changed Files</h2><code>{_esc(str(manifest.get("staging_path", "")))}</code></div><div class="body"><ul>{file_rows}</ul></div></section>
<section class="panel"><div class="head"><h2>Diff Preview</h2><span>side-by-side source patch</span></div><div class="body diff"><pre>{_esc(diff_text)}</pre><pre>{_esc(_diff_summary(diff_text))}</pre></div></section>
</main></body></html>"""
    )


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


def _write_report(
    task_id: str,
    request: TaskRequest,
    files: list[str],
    plan: str,
    staging_path: Path,
    changed_files: list[str],
    patch_notes: list[str],
) -> Path:
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
                f"Source Planner Task: {request.source_task_id or 'none'}",
                f"Script Path: {request.script_path or 'none'}",
                f"Staging Path: {staging_path}",
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
                "## Staged Output",
                "",
                *[f"- {item}" for item in changed_files],
                "",
                "## Patch Notes",
                "",
                *[f"- {note}" for note in patch_notes],
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
