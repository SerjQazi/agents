"""Planning stub for coding_agent."""

from __future__ import annotations

from typing import Any


def generate_plan(data: Any) -> str:
    file_count = len(data.get("files", [])) if isinstance(data, dict) else 0
    prompt = str(data.get("prompt", "")) if isinstance(data, dict) else ""
    return (
        "Placeholder compatibility plan only. No files were modified.\n\n"
        f"- Prompt reviewed: {prompt[:180]}\n"
        f"- Files scanned: {file_count}\n"
        "- Future checks will cover ESX to QBCore, ox_inventory to qb-inventory, "
        "ox_target to qb-target, and mysql-async to oxmysql.\n"
        "- SQL execution, live apply, Git push, FiveM restart, and qb-core edits remain blocked."
    )
