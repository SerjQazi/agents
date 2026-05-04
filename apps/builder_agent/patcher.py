"""Controlled staging-only apply writer for Builder Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import BuilderConfig
from .diffing import unified_diff_text
from .safety import task_blocks_staging, task_review_warnings
from .storage import utc_now
from .validation import validate_staging


class StagingApplyError(Exception):
    pass


class StagingPatcher:
    def __init__(self, config: BuilderConfig) -> None:
        self.config = config

    def build_patch_specs(self, task: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
        files = plan.get("files_json", [])
        patch_plan = plan.get("patch_plan_json", [])
        if not files:
            files = ["PATCH_PLAN.md"]

        patches = []
        for index, target in enumerate(files, start=1):
            target_path = str(target)
            if target_path == "PATCH_PLAN.md":
                source_path = ""
            else:
                source_path = target_path
            content = self._patch_plan_content(task, plan, target_path, patch_plan)
            patches.append(
                {
                    "source_path": source_path,
                    "target_path": f"patches/{index:02d}-{Path(target_path).name}.patch-plan.md",
                    "action": "write",
                    "content": content,
                }
            )
        return patches

    def apply_to_staging(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        findings: list[dict[str, Any]],
        patches: list[dict[str, Any]],
    ) -> tuple[Path, str, dict[str, Any], str]:
        blockers = task_blocks_staging(patches)
        if blockers:
            raise StagingApplyError("; ".join(blockers))
        review_warnings = task_review_warnings(findings)

        task_id = str(task["id"])
        staging_path = (self.config.staging_dir / task_id).resolve()
        staging_root = self.config.staging_dir.resolve()
        if staging_root not in staging_path.parents:
            raise StagingApplyError("Resolved staging path escaped staging root.")
        staging_path.mkdir(parents=True, exist_ok=True)
        backup_path = staging_path / "backup"
        backup_path.mkdir(parents=True, exist_ok=True)
        (backup_path / "TASK_AND_PLAN_BACKUP.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "created_at": utc_now(),
                    "mode": "staging_only",
                    "note": "No live files were backed up because live apply is disabled.",
                    "safety_warnings": review_warnings,
                    "task": task,
                    "plan": plan,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        manifest = {
            "task_id": task_id,
            "created_at": utc_now(),
            "mode": "staging_only",
            "live_apply": "disabled",
            "review_status": "blocked_review" if review_warnings else "review_ready",
            "safety_warnings": review_warnings,
            "source_task": task,
            "patches": [],
        }

        diffs: list[str] = []
        for patch in patches:
            relative_target = Path(str(patch["target_path"]))
            output_path = (staging_path / relative_target).resolve()
            if staging_path not in output_path.parents:
                raise StagingApplyError("Patch target escaped task staging path.")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            content = str(patch["content"])
            if review_warnings:
                content = self._review_warning_block(review_warnings) + "\n" + content
            output_path.write_text(content, encoding="utf-8")
            source = self._source_path_for(task, patch)
            diffs.append(unified_diff_text(source, output_path, str(relative_target)))
            manifest["patches"].append(
                {
                    "source_path": patch.get("source_path", ""),
                    "target_path": str(relative_target),
                    "action": patch.get("action", "write"),
                }
            )

        (staging_path / "PATCH_SPEC.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        rollback_notes = self._rollback_notes(task_id, staging_path, review_warnings)
        (staging_path / "ROLLBACK_NOTES.md").write_text(rollback_notes, encoding="utf-8")
        diff_text = "\n".join(diff for diff in diffs if diff).strip()
        if not diff_text:
            diff_text = "No source file diff available; staging artifacts were generated for review."
        (staging_path / "DIFF_PREVIEW.patch").write_text(diff_text + "\n", encoding="utf-8")
        validation = validate_staging(staging_path)
        if review_warnings:
            validation["checks"].append(
                {
                    "file": str(staging_path / "PATCH_SPEC.json"),
                    "check": "sql_live_apply_block",
                    "status": "blocked_review",
                    "message": "SQL detected. Review only. Live apply blocked.",
                }
            )
            if validation.get("status") != "failed":
                validation["status"] = "blocked_review"
        return staging_path, diff_text, validation, rollback_notes

    def _source_path_for(self, task: dict[str, Any], patch: dict[str, Any]) -> Path | None:
        source_path = str(patch.get("source_path", ""))
        if not source_path:
            return None
        script_path = task.get("script_path")
        if script_path:
            raw_script = Path(str(script_path))
            if raw_script.is_absolute():
                base = raw_script.resolve()
            else:
                base = (self.config.agents_root / raw_script).resolve()
        else:
            base = self.config.incoming_dir.resolve()
        incoming_candidate = (base / source_path).resolve()
        incoming_root = self.config.incoming_dir.resolve()
        if incoming_root in incoming_candidate.parents and incoming_candidate.is_file():
            return incoming_candidate
        return None

    def _patch_plan_content(self, task: dict[str, Any], plan: dict[str, Any], target_path: str, patch_plan: list[str]) -> str:
        lines = [
            f"# Staged Patch Plan: {target_path}",
            "",
            f"Task: `{task['id']}`",
            "Mode: staging_only",
            "",
            "This is a controlled staging artifact. It does not modify live FiveM resources.",
            "",
            "## Summary",
            "",
            str(plan.get("summary", "")),
            "",
            "## Proposed Steps",
            "",
        ]
        for step in patch_plan:
            lines.append(f"- {step}")
        lines.extend(
            [
                "",
                "## Safety",
                "",
                "- Live apply is disabled.",
                "- SQL execution is blocked.",
                "- Destructive deletes are blocked.",
                "- qb-core edits are blocked without separate approval.",
                "- Shell commands from model output are never executed.",
            ]
        )
        return "\n".join(lines) + "\n"

    def _review_warning_block(self, review_warnings: list[str]) -> str:
        lines = ["# Review Blockers", ""]
        for warning in review_warnings:
            lines.append(f"- {warning}")
        lines.extend(["", "Live apply remains disabled. These staged files are for review only."])
        return "\n".join(lines) + "\n"

    def _rollback_notes(self, task_id: str, staging_path: Path, review_warnings: list[str]) -> str:
        warning_lines = "\n".join(f"- {warning}" for warning in review_warnings) if review_warnings else "- None."
        return (
            f"# Rollback Notes - {task_id}\n\n"
            "No live files were changed by this staging-only apply run.\n\n"
            "## Review Blockers\n\n"
            f"{warning_lines}\n\n"
            "SQL review blockers mean live apply remains disabled. Do not run SQL from this task automatically.\n\n"
            f"To discard staged output, remove or ignore this staging folder after review: `{staging_path}`.\n"
        )
