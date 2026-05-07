"""AgentOS Task Orchestration Models."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    ROUTED = "routed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolType(str, Enum):
    GEMINI = "gemini"
    OPENCODE = "opencode"
    CODEX = "codex"
    OLLAMA = "ollama"
    LOCAL_SCRIPT = "local_script"
    MANUAL = "manual"


class Step(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    name: str
    description: str
    tool: ToolType
    purpose: str
    risk_level: RiskLevel = RiskLevel.SAFE
    status: StepStatus = StepStatus.PENDING
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    log: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cost_estimate: str = "free"


class Plan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    name: str
    description: str
    steps: list[Step] = Field(default_factory=list)
    total_steps: int = 0
    completed_steps: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class LifecycleEvent(BaseModel):
    event: str
    timestamp: datetime = Field(default_factory=datetime.now)
    details: str | None = None
    user: str = "system"


class TimelineEventType(str, Enum):
    CREATED = "created"
    PLANNED = "planned"
    ROUTED = "routed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    VALIDATED = "validated"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PAUSED = "paused"
    RESUMED = "resumed"


class TimelineEvent(BaseModel):
    event_type: TimelineEventType
    timestamp: datetime = Field(default_factory=datetime.now)
    step_id: str | None = None
    step_name: str | None = None
    role_used: str | None = None
    tool_used: ToolType | None = None
    risk_level: RiskLevel | None = None
    duration_ms: int | None = None
    details: str | None = None
    user: str = "system"

    def duration_str(self) -> str:
        if self.duration_ms is None:
            return "-"
        if self.duration_ms < 1000:
            return f"{self.duration_ms}ms"
        return f"{self.duration_ms / 1000:.1f}s"


class RollbackMetadata(BaseModel):
    enabled: bool = False
    created_at: datetime | None = None
    instructions: list[str] = Field(default_factory=list)
    rollback_from_state: str | None = None
    can_rollback: bool = True


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4())[:12])
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    plan: Plan | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    logs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    approval_required: bool = False
    approval_status: str | None = None
    lifecycle_events: list[LifecycleEvent] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    rollback: RollbackMetadata = Field(default_factory=RollbackMetadata)
    archived: bool = False
    archive_path: str | None = None
    execution_count: int = 0

    def add_event(self, event: str, details: str | None = None, user: str = "system") -> None:
        self.lifecycle_events.append(
            LifecycleEvent(event=event, details=details, user=user, timestamp=datetime.now())
        )

    def add_timeline(
        self,
        event_type: TimelineEventType,
        step_id: str | None = None,
        step_name: str | None = None,
        role_used: str | None = None,
        tool_used: ToolType | None = None,
        risk_level: RiskLevel | None = None,
        duration_ms: int | None = None,
        details: str | None = None,
        user: str = "system",
    ) -> None:
        self.timeline.append(
            TimelineEvent(
                event_type=event_type,
                timestamp=datetime.now(),
                step_id=step_id,
                step_name=step_name,
                role_used=role_used,
                tool_used=tool_used,
                risk_level=risk_level,
                duration_ms=duration_ms,
                details=details,
                user=user,
            )
        )

    def get_recent_events(self, count: int = 10) -> list[LifecycleEvent]:
        return self.lifecycle_events[-count:]

    def get_timeline(self) -> list[TimelineEvent]:
        return self.timeline

    def total_duration_ms(self) -> int:
        return sum(e.duration_ms for e in self.timeline if e.duration_ms)

    def prepare_rollback(self, instructions: list[str]) -> None:
        self.rollback.enabled = True
        self.rollback.created_at = datetime.now()
        self.rollback.instructions = instructions
        self.rollback.rollback_from_state = self.status.value


class TaskCreateRequest(BaseModel):
    name: str
    description: str
    initial_data: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True


class ExecutionPreview(BaseModel):
    step_id: str
    step_name: str
    tool: ToolType
    purpose: str
    risk_level: RiskLevel
    action_description: str
    files_affected: list[str] = Field(default_factory=list)
    approval_needed: bool = False