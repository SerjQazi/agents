"""SQLite persistence for Planner Agent tasks, logs, findings, plans, reports, and memory."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    prompt TEXT NOT NULL,
                    script_path TEXT,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    level TEXT NOT NULL,
                    action TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plans (
                    task_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    risks_json TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    backup_plan_json TEXT NOT NULL,
                    patch_plan_json TEXT NOT NULL,
                    test_checklist_json TEXT NOT NULL,
                    raw_model_response TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(note_type, key)
                );

                CREATE TABLE IF NOT EXISTS patches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    action TEXT NOT NULL,
                    content TEXT NOT NULL,
                    safety_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS apply_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    staging_path TEXT NOT NULL,
                    diff_text TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    rollback_notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "tasks", "approval_status", "TEXT NOT NULL DEFAULT 'pending'")
            self._ensure_column(conn, "tasks", "apply_mode", "TEXT NOT NULL DEFAULT 'none'")
            self._ensure_column(conn, "tasks", "staging_path", "TEXT")
            self._ensure_column(conn, "tasks", "applied_at", "TEXT")
            self._ensure_column(conn, "tasks", "validation_status", "TEXT")
            self._ensure_column(conn, "tasks", "title", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "tasks", "description", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "plans", "integration_analysis_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "plans", "mapping_rules_json", "TEXT NOT NULL DEFAULT '{}'")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_task(
        self,
        task_id: str,
        prompt: str,
        script_path: str | None,
        model: str,
        title: str,
        description: str,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, title, description, prompt, script_path, model, status, approval_status, apply_mode, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'planning', 'pending', 'none', ?, ?)
                """,
                (task_id, title, description, prompt, script_path, model, now, now),
            )

    def update_task(self, task_id: str, status: str, summary: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, summary = ?, updated_at = ? WHERE id = ?",
                (status, summary, utc_now(), task_id),
            )

    def add_log(
        self,
        task_id: str | None,
        level: str,
        action: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO logs (task_id, level, action, message, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, level, action, message, json.dumps(details or {}, sort_keys=True), utc_now()),
            )

    def add_findings(self, task_id: str, findings: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            for finding in findings:
                conn.execute(
                    """
                    INSERT INTO findings (task_id, category, severity, message, evidence_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        str(finding.get("category", "general")),
                        str(finding.get("severity", "info")),
                        str(finding.get("message", "")),
                        json.dumps(finding.get("evidence", {}), sort_keys=True),
                        utc_now(),
                    ),
                )

    def save_plan(self, task_id: str, plan: dict[str, Any], raw_model_response: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO plans (
                    task_id, summary, risks_json, files_json, backup_plan_json,
                    patch_plan_json, test_checklist_json, raw_model_response, integration_analysis_json, mapping_rules_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    str(plan.get("summary", "")),
                    json.dumps(plan.get("risks", []), sort_keys=True),
                    json.dumps(plan.get("files_it_would_change", []), sort_keys=True),
                    json.dumps(plan.get("backup_plan", []), sort_keys=True),
                    json.dumps(plan.get("patch_plan", []), sort_keys=True),
                    json.dumps(plan.get("test_checklist", []), sort_keys=True),
                    raw_model_response,
                    json.dumps(plan.get("integration_analysis", {}), sort_keys=True),
                    json.dumps(plan.get("mapping_rules", {}), sort_keys=True),
                    utc_now(),
                ),
            )

    def add_report(self, task_id: str, path: Path, title: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO reports (task_id, path, title, created_at) VALUES (?, ?, ?, ?)",
                (task_id, str(path), title, utc_now()),
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def get_plan(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ["risks_json", "files_json", "backup_plan_json", "patch_plan_json", "test_checklist_json"]:
            data[key] = json.loads(data[key] or "[]")
        data["integration_analysis"] = json.loads(data.get("integration_analysis_json") or "{}")
        data["mapping_rules"] = json.loads(data.get("mapping_rules_json") or "{}")
        return data

    def list_for_task(self, table: str, task_id: str) -> list[dict[str, Any]]:
        allowed = {"logs", "findings", "reports", "patches", "apply_runs", "approvals"}
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE task_id = ? ORDER BY created_at DESC",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_approval(self, task_id: str, decision: str, note: str | None = None) -> None:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE tasks SET approval_status = ?, status = CASE WHEN ? = 'approved' THEN 'approved' ELSE status END, updated_at = ? WHERE id = ?",
                (decision, decision, now, task_id),
            )
            conn.execute(
                "INSERT INTO approvals (task_id, decision, note, created_at) VALUES (?, ?, ?, ?)",
                (task_id, decision, note, now),
            )

    def add_patch(self, task_id: str, source_path: str, target_path: str, action: str, content: str, safety_status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO patches (task_id, source_path, target_path, action, content, safety_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, source_path, target_path, action, content, safety_status, utc_now()),
            )

    def add_apply_run(
        self,
        task_id: str,
        mode: str,
        status: str,
        staging_path: Path,
        diff_text: str,
        validation: dict[str, Any],
        rollback_notes: str,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO apply_runs (
                    task_id, mode, status, staging_path, diff_text, validation_json, rollback_notes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, mode, status, str(staging_path), diff_text, json.dumps(validation, sort_keys=True), rollback_notes, now),
            )
            conn.execute(
                """
                UPDATE tasks
                SET apply_mode = ?, staging_path = ?, applied_at = ?, validation_status = ?, status = 'staged', updated_at = ?
                WHERE id = ?
                """,
                (mode, str(staging_path), now, status, now, task_id),
            )

    def upsert_memory_note(self, note_type: str, key: str, value: str, source: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_notes (note_type, key, value, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(note_type, key)
                DO UPDATE SET value = excluded.value, source = excluded.source
                """,
                (note_type, key, value, source, utc_now()),
            )

    def list_recent(self, table: str, limit: int = 50) -> list[dict[str, Any]]:
        allowed = {"tasks", "logs", "findings", "plans", "reports", "memory_notes", "patches", "apply_runs", "approvals"}
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
