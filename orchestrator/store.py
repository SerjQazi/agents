"""AgentOS Task Store - JSON file-based persistence with archive support."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.models import Task, TaskStatus


class TaskStore:
    def __init__(
        self,
        tasks_path: str = "/home/agentzero/agents/orchestrator/tasks",
        archive_path: str = "/home/agentzero/agents/orchestrator/archive",
    ):
        self.tasks_path = Path(tasks_path)
        self.archive_path = Path(archive_path)
        self.tasks_path.mkdir(parents=True, exist_ok=True)
        self.archive_path.mkdir(parents=True, exist_ok=True)
        self._index_file = self.tasks_path / "_index.json"

    def _get_task_path(self, task_id: str) -> Path:
        return self.tasks_path / f"{task_id}.json"

    def _get_archive_path(self, task_id: str) -> Path:
        return self.archive_path / f"{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    def _load_index(self) -> dict[str, Any]:
        if self._index_file.exists():
            with open(self._index_file) as f:
                return json.load(f)
        return {"tasks": [], "last_updated": None, "archived": []}

    def _save_index(self, index: dict[str, Any]) -> None:
        index["last_updated"] = datetime.now().isoformat()
        with open(self._index_file, "w") as f:
            json.dump(index, f, indent=2)

    def _serialize_task(self, task: Task) -> dict[str, Any]:
        data = task.model_dump(mode="json")
        for event in data.get("lifecycle_events", []):
            if isinstance(event.get("timestamp"), datetime):
                event["timestamp"] = event["timestamp"].isoformat()
        if data.get("rollback", {}).get("created_at"):
            rollback = data["rollback"]
            if isinstance(rollback.get("created_at"), datetime):
                rollback["created_at"] = rollback["created_at"].isoformat()
        return data

    def create(self, task: Task) -> Task:
        task.add_event("created", f"Task '{task.name}' created")
        task_path = self._get_task_path(task.task_id)
        with open(task_path, "w") as f:
            json.dump(self._serialize_task(task), f, indent=2)

        index = self._load_index()
        if task.task_id not in index["tasks"]:
            index["tasks"].append(task.task_id)
        self._save_index(index)

        return task

    def get(self, task_id: str) -> Task | None:
        task_path = self._get_task_path(task_id)
        if not task_path.exists():
            return None
        with open(task_path) as f:
            data = json.load(f)
        return Task(**data)

    def update(self, task: Task) -> Task:
        task.updated_at = datetime.now()
        task.add_event("updated", f"Status changed to {task.status.value}")
        return self.create(task)

    def append_log(self, task_id: str, message: str) -> Task | None:
        task = self.get(task_id)
        if not task:
            return None
        timestamp = datetime.now().isoformat()
        task.logs.append(f"[{timestamp}] {message}")
        return self.create(task)

    def delete(self, task_id: str) -> bool:
        task_path = self._get_task_path(task_id)
        if task_path.exists():
            task_path.unlink()
            index = self._load_index()
            index["tasks"] = [t for t in index["tasks"] if t != task_id]
            self._save_index(index)
            return True
        return False

    def archive_task(self, task_id: str) -> Task | None:
        task = self.get(task_id)
        if not task:
            return None

        task.add_event("archived", "Task archived")
        task.archived = True

        archive_file = self._get_archive_path(task_id)
        with open(archive_file, "w") as f:
            json.dump(self._serialize_task(task), f, indent=2)

        task.archive_path = str(archive_file)

        index = self._load_index()
        if "archived" not in index:
            index["archived"] = []
        index["tasks"] = [t for t in index["tasks"] if t != task_id]
        index["archived"].append({
            "task_id": task_id,
            "archived_at": datetime.now().isoformat(),
            "path": str(archive_file),
            "status": task.status.value,
        })
        self._save_index(index)

        self.delete(task_id)
        return task

    def list_all(self) -> list[Task]:
        tasks = []
        for task_id in self._load_index()["tasks"]:
            task = self.get(task_id)
            if task:
                tasks.append(task)
        return tasks

    def list_by_status(self, status: TaskStatus) -> list[Task]:
        return [t for t in self.list_all() if t.status == status]

    def list_recent_tasks(self, count: int = 10) -> list[Task]:
        all_tasks = sorted(
            self.list_all(),
            key=lambda t: t.updated_at,
            reverse=True,
        )
        return all_tasks[:count]

    def list_archived(self) -> list[dict[str, Any]]:
        return self._load_index().get("archived", [])

    def search(self, query: str) -> list[Task]:
        query_lower = query.lower()
        return [
            t for t in self.list_all()
            if query_lower in t.name.lower() or query_lower in t.description.lower()
        ]

    def get_task_history(self, task_id: str) -> dict[str, Any] | None:
        task = self.get(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "name": task.name,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "status": task.status.value,
            "lifecycle_events": [
                {
                    "event": e.event,
                    "timestamp": e.timestamp.isoformat(),
                    "details": e.details,
                    "user": e.user,
                }
                for e in task.lifecycle_events
            ],
            "logs": task.logs,
            "execution_count": task.execution_count,
            "archived": task.archived,
        }

    def get_execution_logs(self, task_id: str) -> list[str] | None:
        task = self.get(task_id)
        if not task:
            return None
        return task.logs

    def save_task(self, task: Task) -> Task:
        """Alias for create/update."""
        return self.create(task)

    def load_task(self, task_id: str) -> Task | None:
        """Alias for get."""
        return self.get(task_id)