"""Markdown report generation for Planner Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import utc_now


class ReportWriter:
    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def write_task_report(
        self,
        task_id: str,
        prompt: str,
        model: str,
        scan: dict[str, Any],
        plan: dict[str, Any],
        raw_model_response: str,
    ) -> Path:
        path = self.reports_dir / f"{task_id}.md"
        lines = [
            f"# Planner Agent Report - {task_id}",
            "",
            f"Created: {utc_now()}",
            f"Model: `{model}`",
            "Mode: plan-only/read-only",
            "",
            "## Safety",
            "",
            "- No files were modified.",
            "- No SQL was run.",
            "- FiveM was not restarted.",
            "- Git was not pushed.",
            "- qb-core was not modified.",
            "",
            "## Task",
            "",
            prompt,
            "",
            "## Scan Summary",
            "",
            "```text",
            str(scan.get("summary_text", "")),
            "```",
            "",
            "## Findings",
            "",
        ]
        for finding in scan.get("findings", []):
            lines.append(f"- **{finding.get('severity', 'info')}** `{finding.get('category', 'general')}`: {finding.get('message', '')}")

        lines.extend(["", "## Files Read", ""])
        for file_path in scan.get("text_files_read", []):
            lines.append(f"- {file_path}")
        if not scan.get("text_files_read"):
            lines.append("None.")

        lines.extend(["", "## Files It Would Change", ""])
        for file_path in plan.get("files_it_would_change", []):
            lines.append(f"- {file_path}")
        if not plan.get("files_it_would_change"):
            lines.append("None identified yet.")

        self._section(lines, "Risks", plan.get("risks", []))
        self._section(lines, "Backup Plan", plan.get("backup_plan", []))
        self._section(lines, "Patch Plan", plan.get("patch_plan", []))
        self._section(lines, "Manual Test Checklist", plan.get("test_checklist", []))

        lines.extend(["", "## Ollama Plan Text", ""])
        if raw_model_response:
            lines.extend(["```text", raw_model_response, "```"])
        else:
            lines.append("Ollama was unavailable or returned no content; deterministic fallback plan was used.")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _section(self, lines: list[str], title: str, items: list[str]) -> None:
        lines.extend(["", f"## {title}", ""])
        if not items:
            lines.append("None.")
            return
        for item in items:
            lines.append(f"- {item}")

