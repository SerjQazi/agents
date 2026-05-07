"""AgentOS Maintenance and Cleanup System.

Handles:
- Task archival policies
- Cleanup commands
- Approval queue cleanup
- Stale task detection
- Orphaned timeline/approval detection
- Retention policies
- Task pruning
- Storage integrity checks
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from orchestrator.models import TaskStatus


class CleanupManager:
    """Manages task cleanup and maintenance."""

    def __init__(
        self,
        tasks_path: str = "/home/agentzero/agents/orchestrator/tasks",
        archive_path: str = "/home/agentzero/agents/orchestrator/archive",
        approvals_path: str = "/home/agentzero/agents/orchestrator/approvals",
    ):
        self.tasks_path = Path(tasks_path)
        self.archive_path = Path(archive_path)
        self.approvals_path = Path(approvals_path)

    def cleanup_completed_tasks(
        self,
        older_than_days: int = 7,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Archive completed tasks older than N days."""
        results = {"archived": [], "skipped": [], "errors": []}

        if not self.tasks_path.exists():
            return results

        cutoff = datetime.now() - timedelta(days=older_than_days)

        for task_file in self.tasks_path.glob("*.json"):
            if task_file.name.startswith("_"):
                continue

            try:
                with open(task_file) as f:
                    data = json.load(f)

                if data.get("status") != "completed":
                    results["skipped"].append(task_file.stem)
                    continue

                updated_at = data.get("updated_at")
                if not updated_at:
                    results["skipped"].append(task_file.stem)
                    continue

                if isinstance(updated_at, str):
                    try:
                        task_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    except ValueError:
                        results["skipped"].append(task_file.stem)
                        continue
                else:
                    results["skipped"].append(task_file.stem)
                    continue

                if task_time < cutoff:
                    if dry_run:
                        results["archived"].append(task_file.stem)
                    else:
                        archive_name = f"{task_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                        dest = self.archive_path / archive_name

                        try:
                            with open(dest, "w") as af:
                                json.dump(data, af, indent=2)
                            task_file.unlink()
                            results["archived"].append(task_file.stem)
                        except IOError as e:
                            results["errors"].append({"task": task_file.stem, "error": str(e)})

            except (json.JSONDecodeError, IOError) as e:
                results["errors"].append({"task": task_file.stem, "error": str(e)})

        return results

    def cleanup_approvals(
        self,
        older_than_days: int = 30,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Clean up old approval records."""
        results = {"removed": [], "kept": [], "errors": []}

        queue_file = self.approvals_path / "_queue.json"
        if not queue_file.exists():
            return results

        try:
            with open(queue_file) as f:
                data = json.load(f)

            cutoff = datetime.now() - timedelta(days=older_than_days)
            queue = data.get("queue", [])

            new_queue = []
            for record in queue:
                created_at = record.get("created_at", "")
                if not created_at:
                    new_queue.append(record)
                    results["kept"].append(record.get("task_id", "unknown"))
                    continue

                try:
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if created < cutoff:
                        if not dry_run:
                            results["removed"].append(record.get("task_id", "unknown"))
                            continue
                        results["removed"].append(record.get("task_id", "unknown"))
                    else:
                        new_queue.append(record)
                        results["kept"].append(record.get("task_id", "unknown"))
                except ValueError:
                    new_queue.append(record)
                    results["kept"].append(record.get("task_id", "unknown"))

            if not dry_run:
                with open(queue_file, "w") as f:
                    json.dump({"queue": new_queue}, f, indent=2)

        except (json.JSONDecodeError, IOError) as e:
            results["errors"].append(str(e))

        return results

    def detect_stale_tasks(self, stale_days: int = 30) -> list[dict[str, Any]]:
        """Detect stale tasks (not updated in N days)."""
        stale = []
        cutoff = datetime.now() - timedelta(days=stale_days)

        if not self.tasks_path.exists():
            return stale

        for task_file in self.tasks_path.glob("*.json"):
            if task_file.name.startswith("_"):
                continue

            try:
                with open(task_file) as f:
                    data = json.load(f)

                status = data.get("status", "unknown")
                if status in ["completed", "failed", "cancelled"]:
                    continue

                updated_at = data.get("updated_at")
                if not updated_at:
                    continue

                if isinstance(updated_at, str):
                    try:
                        task_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                else:
                    continue

                if task_time < cutoff:
                    days_old = (datetime.now() - task_time).days
                    stale.append({
                        "task_id": data.get("task_id", task_file.stem),
                        "name": data.get("name", "Unknown"),
                        "status": status,
                        "days_stale": days_old,
                        "updated_at": updated_at,
                    })

            except (json.JSONDecodeError, IOError):
                continue

        return stale

    def detect_orphaned_timelines(self) -> list[dict[str, Any]]:
        """Detect tasks with missing or empty timelines."""
        orphaned = []

        if not self.tasks_path.exists():
            return orphaned

        for task_file in self.tasks_path.glob("*.json"):
            if task_file.name.startswith("_"):
                continue

            try:
                with open(task_file) as f:
                    data = json.load(f)

                status = data.get("status", "unknown")
                if status in ["pending", "planning", "ready"]:
                    continue

                timeline = data.get("timeline", [])
                if not timeline:
                    orphaned.append({
                        "task_id": data.get("task_id", task_file.stem),
                        "name": data.get("name", "Unknown"),
                        "status": status,
                        "issue": "missing_timeline",
                    })

            except (json.JSONDecodeError, IOError):
                continue

        return orphaned

    def detect_orphaned_approvals(self) -> list[dict[str, Any]]:
        """Detect approvals for non-existent tasks."""
        orphaned = []

        if not self.approvals_path.exists():
            return orphaned

        queue_file = self.approvals_path / "_queue.json"
        if not queue_file.exists():
            return orphaned

        try:
            with open(queue_file) as f:
                data = json.load(f)

            task_ids = set()
            if self.tasks_path.exists():
                for task_file in self.tasks_path.glob("*.json"):
                    if task_file.name.startswith("_"):
                        continue
                    try:
                        with open(task_file) as tf:
                            td = json.load(tf)
                            task_ids.add(td.get("task_id"))
                    except (json.JSONDecodeError, IOError):
                        continue

            for record in data.get("queue", []):
                task_id = record.get("task_id")
                if task_id and task_id not in task_ids:
                    orphaned.append({
                        "task_id": task_id,
                        "step_id": record.get("step_id"),
                        "step_name": record.get("step_name"),
                        "status": record.get("status"),
                    })

        except (json.JSONDecodeError, IOError):
            pass

        return orphaned

    def verify_storage_integrity(self) -> dict[str, Any]:
        """Verify storage integrity."""
        results = {
            "total_tasks": 0,
            "valid_tasks": 0,
            "corrupted": [],
            "missing_index": False,
            "empty_tasks": [],
            "archive_stats": {},
        }

        index_file = self.tasks_path / "_index.json"
        if not index_file.exists():
            results["missing_index"] = True
        else:
            try:
                with open(index_file) as f:
                    index = json.load(f)
                    results["total_tasks"] = len(index.get("tasks", []))
            except (json.JSONDecodeError, IOError):
                results["missing_index"] = True

        if not self.tasks_path.exists():
            return results

        for task_file in self.tasks_path.glob("*.json"):
            if task_file.name.startswith("_"):
                continue

            try:
                with open(task_file) as f:
                    data = json.load(f)
                    results["valid_tasks"] += 1

                    if not data.get("task_id"):
                        results["corrupted"].append({
                            "file": task_file.name,
                            "issue": "missing_task_id",
                        })

                    if not data.get("name"):
                        results["corrupted"].append({
                            "file": task_file.name,
                            "issue": "missing_name",
                        })

                    if not data.get("status"):
                        results["empty_tasks"].append(task_file.name)

            except json.JSONDecodeError:
                results["corrupted"].append({
                    "file": task_file.name,
                    "issue": "invalid_json",
                })

        archive_count = 0
        if self.archive_path.exists():
            archive_count = len(list(self.archive_path.glob("*.json")))
        results["archive_stats"] = {
            "total_archived": archive_count,
        }

        return results


class RetentionPolicy:
    """Defines retention policies for tasks."""

    RETENTION = {
        "completed": 30,
        "failed": 60,
        "paused": 90,
        "active": 365,
    }

    @classmethod
    def get_retention_days(cls, status: str) -> int:
        return cls.RETENTION.get(status, 30)

    @classmethod
    def get_policy_summary(cls) -> dict[str, int]:
        return cls.RETENTION.copy()