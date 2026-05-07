"""Execution wrappers base classes."""

from datetime import datetime
from enum import Enum
from typing import Any
from dataclasses import dataclass, field
from pathlib import Path


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    APPROVED = "approved"
    EXECUTED = "executed"
    FAILED = "failed"
    DRY_RUN = "dry_run"


@dataclass
class ExecutionResult:
    """Result of an execution attempt."""

    status: ExecutionStatus
    risk_level: RiskLevel
    command: str
    output: str = ""
    error: str | None = None
    dry_run: bool = True
    approved: bool = False
    approval_required: bool = False
    timestamp: datetime = field(default_factory=datetime.now)
    path_restricted: bool = False
    path_allowed: str | None = None
    blocked_reason: str | None = None
    rollback_metadata: dict[str, Any] = field(default_factory=dict)
    audit_log: list[str] = field(default_factory=list)

    def is_allowed(self) -> bool:
        return self.status in (ExecutionStatus.ALLOWED, ExecutionStatus.EXECUTED, ExecutionStatus.DRY_RUN)

    def requires_approval(self) -> bool:
        return self.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)


class ExecutionWrapper:
    """Base class for safe execution wrappers."""

    ALLOWED_BASE_PATH = "/home/agentzero/agents"
    BLOCKED_PATHS = ["/etc", "/root", "/var", "/usr", "/bin", "/sbin"]

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.execution_log: list[ExecutionResult] = []

    def _check_path(self, path: str) -> tuple[bool, str | None]:
        """Check if path is allowed."""
        path_obj = Path(path).resolve()

        if not str(path_obj).startswith(self.ALLOWED_BASE_PATH):
            return False, f"Path outside allowed base: {self.ALLOWED_BASE_PATH}"

        for blocked in self.BLOCKED_PATHS:
            if str(path_obj).startswith(blocked):
                return False, f"Path in blocked directory: {blocked}"

        return True, None

    def _log_execution(self, result: ExecutionResult) -> None:
        """Log execution to audit trail."""
        self.execution_log.append(result)

    def get_audit_log(self) -> list[dict]:
        """Get audit log for all executions."""
        return [
            {
                "timestamp": r.timestamp.isoformat(),
                "status": r.status.value,
                "risk": r.risk_level.value,
                "command": r.command,
                "dry_run": r.dry_run,
                "approved": r.approved,
            }
            for r in self.execution_log
        ]

    def get_allowed_paths(self) -> list[str]:
        """Return list of allowed base paths."""
        return [self.ALLOWED_BASE_PATH]

    def get_blocked_paths(self) -> list[str]:
        """Return list of blocked paths."""
        return self.BLOCKED_PATHS