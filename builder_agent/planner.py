"""Plan-only task generation for Builder Agent."""

from __future__ import annotations

from typing import Any

from .ollama_client import OllamaClient


class Planner:
    def __init__(self, ollama: OllamaClient) -> None:
        self.ollama = ollama

    def build_plan(self, prompt: str, scan: dict[str, Any], memory_notes: list[dict[str, Any]], model: str) -> tuple[dict[str, Any], str, str]:
        llm_prompt = self._build_prompt(prompt, scan, memory_notes)
        result = self.ollama.chat(llm_prompt, model=model)
        fallback = self._fallback_plan(prompt, scan)
        if not result.ok or not result.content:
            fallback["risks"].append(f"Ollama unavailable or returned no content: {result.error or 'empty response'}")
            return fallback, "", result.error

        plan = dict(fallback)
        plan["summary"] = result.content.splitlines()[0][:300] if result.content.splitlines() else fallback["summary"]
        plan["patch_plan"].insert(0, "Review the Ollama plan text in the generated report before approving any future apply mode.")
        return plan, result.content, ""

    def _build_prompt(self, prompt: str, scan: dict[str, Any], memory_notes: list[dict[str, Any]]) -> str:
        memory_text = "\n".join(f"- {note['note_type']}:{note['key']} = {note['value']}" for note in memory_notes[:30])
        return f"""Task:
{prompt}

Builder Agent mode:
- Plan-only and read-only.
- Do not apply changes.
- Do not run SQL.
- Do not restart FiveM.
- Do not modify qb-core.

Memory:
{memory_text}

Read-only scan summary:
{scan.get('summary_text', '')}

Findings:
{scan.get('findings', [])}

Return a practical plan with summary, risks, files that would change, backup plan, patch plan, and manual test checklist.
"""

    def _fallback_plan(self, prompt: str, scan: dict[str, Any]) -> dict[str, Any]:
        files = scan.get("files", [])
        likely_files = [
            path for path in files if path.endswith((".lua", ".js", ".json", ".cfg")) and "qb-core" not in path
        ][:25]
        risks = [
            "MVP is plan-only; no files were changed.",
            "Any SQL files must be reviewed manually and must not be run automatically.",
            "Any inventory, money, permissions, or player data changes require explicit approval.",
            "Direct qb-core edits are blocked unless explicitly approved.",
        ]
        if scan.get("sql_files"):
            risks.insert(1, f"SQL files detected: {', '.join(scan['sql_files'])}")
        return {
            "summary": f"Plan-only Builder Agent task prepared for: {prompt[:160]}",
            "risks": risks,
            "files_it_would_change": likely_files,
            "backup_plan": [
                "Create a timestamped backup under /home/agentzero/agents/backups before any future apply step.",
                "Keep original incoming script untouched until an approved staging patch is generated.",
                "Record backup path in the task report.",
            ],
            "patch_plan": [
                "Keep work in staging first; do not modify live FiveM resources in MVP.",
                "Map framework, database, target, and inventory APIs only inside the incoming script or compatibility adapters.",
                "Add AGENT FIX START and AGENT FIX END comments around major generated changes in a future approved apply mode.",
                "Write a detailed report before asking for apply approval.",
            ],
            "test_checklist": [
                "Review generated patch plan and risk list.",
                "Check Lua syntax for changed Lua files after any future apply.",
                "Check JavaScript syntax with node --check for changed JS files after any future apply.",
                "Start FiveM manually only after approval and review.",
                "Join with a test character and exercise the adapted resource.",
                "Confirm no SQL was run by Builder Agent.",
            ],
        }

