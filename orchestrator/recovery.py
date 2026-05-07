"""AgentOS Task Recovery System.

Handles:
- Task recovery on orchestrator startup
- Approval queue persistence
- Timeline verification
- Log replay support
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.models import Task, TaskStatus


class RecoveryManager:
    """Manages task recovery and persistence verification."""

    def __init__(
        self,
        tasks_path: str = "/home/agentzero/agents/orchestrator/tasks",
        archive_path: str = "/home/agentzero/agents/orchestrator/archive",
        approvals_path: str = "/home/agentzero/agents/orchestrator/approvals",
    ):
        self.tasks_path = Path(tasks_path)
        self.archive_path = Path(archive_path)
        self.approvals_path = Path(approvals_path)

    def scan_tasks(self) -> dict[str, list[dict[str, Any]]]:
        """Scan all tasks and categorize by status."""
        result = {
            "active": [],
            "paused": [],
            "completed": [],
            "failed": [],
            "archived": [],
            "orphaned": [],
        }

        if not self.tasks_path.exists():
            return result

        for task_file in self.tasks_path.glob("*.json"):
            if task_file.name.startswith("_"):
                continue
            try:
                with open(task_file) as f:
                    data = json.load(f)
                status = data.get("status", "unknown")
                task_id = data.get("task_id", task_file.stem)

                category = self._categorize_status(status)
                result[category].append({
                    "task_id": task_id,
                    "name": data.get("name", "Unknown"),
                    "status": status,
                    "file": str(task_file),
                    "has_timeline": "timeline" in data and len(data.get("timeline", [])) > 0,
                    "has_logs": "logs" in data and len(data.get("logs", [])) > 0,
                    "approval_required": data.get("approval_required", False),
                    "updated_at": data.get("updated_at"),
                })
            except (json.JSONDecodeError, IOError) as e:
                result["orphaned"].append({
                    "file": str(task_file),
                    "error": str(e),
                })

        return result

    def _categorize_status(self, status: str) -> str:
        """Map task status to directory category."""
        mapping = {
            "pending": "active",
            "planning": "active",
            "ready": "active",
            "running": "active",
            "paused": "paused",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "failed",
        }
        return mapping.get(status, "active")

    def verify_timeline_persistence(self, task: Task) -> dict[str, Any]:
        """Verify timeline was properly persisted."""
        return {
            "has_timeline": len(task.timeline) > 0,
            "event_count": len(task.timeline),
            "total_duration_ms": task.total_duration_ms(),
            "has_created_event": any(e.event_type.value == "created" for e in task.timeline),
            "has_completed_event": any(e.event_type.value == "completed" for e in task.timeline),
        }

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Get all pending approvals from queue."""
        queue_file = self.approvals_path / "_queue.json"
        if not queue_file.exists():
            return []

        try:
            with open(queue_file) as f:
                data = json.load(f)
            return [r for r in data.get("queue", []) if r.get("status") == "pending"]
        except (json.JSONDecodeError, IOError):
            return []

    def recover_task(self, task_id: str) -> dict[str, Any]:
        """Attempt to recover a specific task."""
        task_file = self.tasks_path / f"{task_id}.json"
        if not task_file.exists():
            return {"success": False, "error": "Task file not found"}

        try:
            with open(task_file) as f:
                data = json.load(f)
            task = Task(**data)

            timeline_check = self.verify_timeline_persistence(task)

            return {
                "success": True,
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status.value,
                "recovery_status": "healthy" if timeline_check["has_timeline"] else "missing_timeline",
                "timeline_verification": timeline_check,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_task_logs(self, task_id: str) -> list[str] | None:
        """Get task logs (for replay)."""
        task_file = self.tasks_path / f"{task_id}.json"
        if not task_file.exists():
            return None

        try:
            with open(task_file) as f:
                data = json.load(f)
            return data.get("logs", [])
        except (json.JSONDecodeError, IOError):
            return None

    def replay_logs(self, task_id: str) -> str:
        """Replay task logs in order."""
        logs = self.get_task_logs(task_id)
        if logs is None:
            return f"Task {task_id} not found"

        if not logs:
            return f"Task {task_id} has no logs"

        output = [f"=== Replaying logs for task {task_id} ==="]
        for i, log in enumerate(logs, 1):
            output.append(f"{i:3}. {log}")

        return "\n".join(output)


class TaskDirectoryManager:
    """Manages structured task directories."""

    def __init__(self, base_path: str = "/home/agentzero/agents/orchestrator"):
        self.base_path = Path(base_path)
        self.tasks_path = self.base_path / "tasks"

    def ensure_directories(self) -> None:
        """Create status-based directories if they don't exist."""
        dirs = ["active", "paused", "completed", "failed"]
        for d in dirs:
            (self.tasks_path / d).mkdir(exist_ok=True)

    def organize_tasks(self) -> dict[str, int]:
        """Move tasks to appropriate directories based on status."""
        self.ensure_directories()

        counts = {"active": 0, "paused": 0, "completed": 0, "failed": 0}

        for task_file in self.tasks_path.glob("*.json"):
            if task_file.name.startswith("_"):
                continue

            try:
                with open(task_file) as f:
                    data = json.load(f)

                status = data.get("status", "pending")
                category = {
                    "pending": "active",
                    "planning": "active",
                    "ready": "active",
                    "running": "active",
                    "paused": "paused",
                    "completed": "completed",
                    "failed": "failed",
                    "cancelled": "failed",
                }.get(status, "active")

                dest_dir = self.tasks_path / category
                dest_file = dest_dir / task_file.name

                if dest_file != task_file:
                    task_file.rename(dest_file)
                    counts[category] += 1
            except (json.JSONDecodeError, IOError):
                continue

        return counts

    def get_directory_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for each directory."""
        stats = {}
        for category in ["active", "paused", "completed", "failed"]:
            dir_path = self.tasks_path / category
            if not dir_path.exists():
                stats[category] = {"count": 0, "tasks": []}
                continue

            tasks = []
            for f in dir_path.glob("*.json"):
                try:
                    with open(f) as tf:
                        data = json.load(tf)
                    tasks.append({
                        "task_id": data.get("task_id", f.stem),
                        "name": data.get("name", "Unknown"),
                        "status": data.get("status", "unknown"),
                    })
                except (json.JSONDecodeError, IOError):
                    continue

            stats[category] = {"count": len(tasks), "tasks": tasks}

        return stats