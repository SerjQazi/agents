"""Structured file and SQLite logging for Planner Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import Storage, utc_now


class PlannerLogger:
    def __init__(self, storage: Storage, logs_dir: Path) -> None:
        self.storage = storage
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.logs_dir / "planner-agent.jsonl"

    def log(
        self,
        action: str,
        message: str,
        *,
        task_id: str | None = None,
        level: str = "info",
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "timestamp": utc_now(),
            "task_id": task_id,
            "level": level,
            "action": action,
            "message": message,
            "details": details or {},
        }
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        self.storage.add_log(task_id, level, action, message, details)

