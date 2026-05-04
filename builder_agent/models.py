"""Pydantic request and response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    prompt: str = Field(..., min_length=1)
    script_path: str | None = None
    model: str | None = None


class TaskResponse(BaseModel):
    task_id: str
    status: str
    summary: str
    report_path: str | None = None
    findings: list[dict[str, Any]] = []
    plan: dict[str, Any] = {}


class ApprovalRequest(BaseModel):
    note: str | None = None


class ApplyResponse(BaseModel):
    task_id: str
    status: str
    staging_path: str | None = None
    validation: dict[str, Any] = {}
    diff_preview: str = ""

