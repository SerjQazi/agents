"""Safety checks for Builder Agent staging-only apply mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any


BLOCKED_PATH_PARTS = {".git", ".venv", "venv", "env", "__pycache__"}
SENSITIVE_NAMES = {".env", "server.cfg"}
SQL_REVIEW_MESSAGE = "SQL detected. Review only. Live apply blocked."


def safety_check_patch(patch: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    action = str(patch.get("action", "")).lower()
    target_path = str(patch.get("target_path", ""))
    source_path = str(patch.get("source_path", ""))

    if action not in {"write", "update"}:
        reasons.append("Only write/update patch actions are allowed.")
    if not target_path:
        reasons.append("Patch target path is required.")
    if Path(target_path).is_absolute() or Path(source_path).is_absolute():
        reasons.append("Patch paths must be relative.")
    lowered = target_path.lower()
    parts = set(Path(target_path).parts)
    if lowered.endswith(".sql"):
        reasons.append("SQL file writes are blocked.")
    if "qb-core" in parts or "qb-core" in lowered:
        reasons.append("qb-core edits require separate explicit approval and are blocked for now.")
    if parts & BLOCKED_PATH_PARTS:
        reasons.append("Patch path targets blocked internal folders.")
    if Path(target_path).name in SENSITIVE_NAMES:
        reasons.append("Sensitive config files are blocked.")
    if ".." in Path(target_path).parts:
        reasons.append("Parent directory traversal is blocked.")

    return not reasons, reasons


def task_blocks_staging(patches: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for patch in patches:
        ok, patch_reasons = safety_check_patch(patch)
        if not ok:
            reasons.extend(patch_reasons)
    return sorted(set(reasons))


def task_review_warnings(findings: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for finding in findings:
        if finding.get("category") == "database" and finding.get("severity") in {"high", "error"}:
            warnings.append(SQL_REVIEW_MESSAGE)
            warnings.append(str(finding.get("message", "SQL/database risk requires manual review.")))
    return sorted(set(warnings))


def task_blocks_live_apply(findings: list[dict[str, Any]], patches: list[dict[str, Any]]) -> list[str]:
    reasons = task_review_warnings(findings)
    reasons.extend(task_blocks_staging(patches))
    return sorted(set(reasons))
