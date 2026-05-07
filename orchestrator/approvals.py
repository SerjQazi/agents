"""File-based approval queue (Phase 1).

This is intentionally lightweight and CLI-first:
- Writes a small queue file under `orchestrator/approvals/_queue.json`
- Records pending approvals and decision metadata (timestamps, who, reason)
- Does not change the existing task flow; it observes and annotates it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ApprovalRecord:
    task_id: str
    step_id: str
    status: str  # pending|approved|rejected|stale
    created_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    reason: str | None = None
    risk_level: str | None = None
    tool: str | None = None
    step_name: str | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ApprovalRecord":
        return ApprovalRecord(
            task_id=str(data.get("task_id", "")),
            step_id=str(data.get("step_id", "")),
            status=str(data.get("status", "")),
            created_at=str(data.get("created_at", "")),
            decided_at=data.get("decided_at"),
            decided_by=data.get("decided_by"),
            reason=data.get("reason"),
            risk_level=data.get("risk_level"),
            tool=data.get("tool"),
            step_name=data.get("step_name"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "status": self.status,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "tool": self.tool,
            "step_name": self.step_name,
        }


class ApprovalQueue:
    def __init__(self, approvals_dir: str | Path | None = None):
        if approvals_dir is None:
            approvals_dir = Path(__file__).resolve().parent / "approvals"
        self.approvals_dir = Path(approvals_dir)
        self.approvals_dir.mkdir(parents=True, exist_ok=True)
        self.queue_file = self.approvals_dir / "_queue.json"

    def _load(self) -> dict[str, Any]:
        if self.queue_file.exists():
            return json.loads(self.queue_file.read_text(encoding="utf-8"))
        return {"records": [], "last_updated": None}

    def _save(self, data: dict[str, Any]) -> None:
        data["last_updated"] = datetime.now().isoformat()
        self.queue_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _key(task_id: str, step_id: str) -> str:
        return f"{task_id}:{step_id}"

    def list_records(self) -> list[ApprovalRecord]:
        data = self._load()
        records = [ApprovalRecord.from_dict(r) for r in data.get("records", [])]
        # newest first
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def list_pending(self) -> list[ApprovalRecord]:
        return [r for r in self.list_records() if r.status == "pending"]

    def list_for_task(self, task_id: str) -> list[ApprovalRecord]:
        return [r for r in self.list_records() if r.task_id == task_id]

    def get(self, task_id: str, step_id: str) -> ApprovalRecord | None:
        key = self._key(task_id, step_id)
        for r in self.list_records():
            if self._key(r.task_id, r.step_id) == key:
                return r
        return None

    def enqueue(
        self,
        *,
        task_id: str,
        step_id: str,
        risk_level: str | None = None,
        tool: str | None = None,
        step_name: str | None = None,
    ) -> ApprovalRecord:
        data = self._load()
        records: list[dict[str, Any]] = list(data.get("records", []))

        key = self._key(task_id, step_id)
        for r in records:
            if self._key(str(r.get("task_id", "")), str(r.get("step_id", ""))) == key:
                # already tracked; do not duplicate
                existing = ApprovalRecord.from_dict(r)
                if existing.status != "pending":
                    # if it was decided before and we re-queued, treat as new pending
                    r["status"] = "pending"
                    r["created_at"] = datetime.now().isoformat()
                    r["decided_at"] = None
                    r["decided_by"] = None
                    r["reason"] = None
                if risk_level:
                    r["risk_level"] = risk_level
                if tool:
                    r["tool"] = tool
                if step_name:
                    r["step_name"] = step_name
                self._save(data)
                return ApprovalRecord.from_dict(r)

        rec = ApprovalRecord(
            task_id=task_id,
            step_id=step_id,
            status="pending",
            created_at=datetime.now().isoformat(),
            risk_level=risk_level,
            tool=tool,
            step_name=step_name,
        )
        records.append(rec.to_dict())
        data["records"] = records
        self._save(data)
        return rec

    def decide(
        self,
        *,
        task_id: str,
        step_id: str,
        decision: str,  # approved|rejected
        decided_by: str,
        reason: str | None = None,
    ) -> ApprovalRecord:
        if decision not in ("approved", "rejected"):
            raise ValueError("decision must be 'approved' or 'rejected'")

        data = self._load()
        records: list[dict[str, Any]] = list(data.get("records", []))
        key = self._key(task_id, step_id)

        for r in records:
            if self._key(str(r.get("task_id", "")), str(r.get("step_id", ""))) == key:
                r["status"] = decision
                r["decided_at"] = datetime.now().isoformat()
                r["decided_by"] = decided_by
                if reason is not None:
                    r["reason"] = reason
                data["records"] = records
                self._save(data)
                return ApprovalRecord.from_dict(r)

        # If it was never enqueued (older tasks), create a decided record.
        rec = ApprovalRecord(
            task_id=task_id,
            step_id=step_id,
            status=decision,
            created_at=datetime.now().isoformat(),
            decided_at=datetime.now().isoformat(),
            decided_by=decided_by,
            reason=reason,
        )
        records.append(rec.to_dict())
        data["records"] = records
        self._save(data)
        return rec

