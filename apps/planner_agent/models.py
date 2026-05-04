"""Pydantic request and response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    prompt: str = Field(..., min_length=1)
    title: str | None = None
    description: str | None = None
    script_path: str | None = None
    model: str | None = None


class TaskResponse(BaseModel):
    task_id: str
    title: str
    description: str
    task_name: str = ""
    task_summary: str = ""
    created_at_human: str = ""
    risk_label: str = ""
    status: str
    summary: str
    report_path: str | None = None
    staging_path: str | None = None
    findings: list[dict[str, Any]] = []
    plan: dict[str, Any] = {}
    integration_analysis: dict[str, Any] = {}


class UploadStartRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    prompt: str | None = None
    model: str | None = None


class UploadCompleteRequest(BaseModel):
    prompt: str | None = None
    title: str | None = None
    description: str | None = None
    model: str | None = None


class ApprovalRequest(BaseModel):
    note: str | None = None


class ApplyResponse(BaseModel):
    task_id: str
    status: str
    staging_path: str | None = None
    validation: dict[str, Any] = {}
    diff_preview: str = ""
