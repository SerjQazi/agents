"""Execution Step Dispatcher - Routes steps to safe execution wrappers.

This module provides:
- ExecutionStepDispatcher: Routes execution to appropriate wrapper
- ToolExecutor: Coordinates wrapper execution with audit, rollback, and retry logic
- Maps orchestrator ToolType to execution wrapper types
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from orchestrator.models import (
    RiskLevel as ModelRiskLevel,
    Step,
    StepStatus,
    Task,
    TaskStatus,
    TimelineEventType,
    ToolType,
)
from orchestrator.execution.base import ExecutionResult as WrapperResult, ExecutionStatus, RiskLevel
from orchestrator.execution.shell import SafeShell
from orchestrator.execution.git import SafeGit
from orchestrator.execution.file_edit import SafeFileEdit
from orchestrator.execution.validation import SafeValidation


EXECUTION_TYPE_SHELL = "shell_readonly"
EXECUTION_TYPE_GIT = "git_readonly"
EXECUTION_TYPE_FILE_EDIT = "file_edit"
EXECUTION_TYPE_VALIDATION = "validation"


@dataclass
class ExecutionContext:
    """Context for step execution."""

    task_id: str
    step_id: str
    dry_run: bool
    timeout: int = 30
    max_retries: int = 0
    approved: bool = False


@dataclass
class ExecutionState:
    """Tracks execution state for retry-safe operations."""

    task_id: str
    step_id: str
    status: str = "pending"
    attempts: int = 0
    last_attempt: datetime | None = None
    last_result: dict[str, Any] | None = None
    wrapper_used: str | None = None
    execution_type: str | None = None
    rollback_metadata: dict[str, Any] = field(default_factory=dict)
    audit_log: list[str] = field(default_factory=list)


class ExecutionStepDispatcher:
    """Dispatches steps to appropriate execution wrapper based on tool type and operation."""

    def __init__(self, dry_run: bool = True, timeout: int = 30):
        self.dry_run = dry_run
        self.timeout = timeout
        self._shell = SafeShell(dry_run=dry_run, timeout=timeout)
        self._git = SafeGit(dry_run=dry_run, timeout=timeout)
        self._file_edit = SafeFileEdit(dry_run=dry_run)
        self._validation = SafeValidation(dry_run=dry_run)

    def get_execution_type(self, step: Step) -> str:
        """Determine execution type from step tool and description."""
        tool = step.tool
        desc = step.description.lower()
        name = step.name.lower()

        if tool == ToolType.LOCAL_SCRIPT:
            if "git" in desc or "git" in name:
                return EXECUTION_TYPE_GIT
            return EXECUTION_TYPE_SHELL

        if tool == ToolType.MANUAL:
            return EXECUTION_TYPE_VALIDATION

        if any(kw in desc for kw in ["edit", "write", "modify", "create file", "update"]):
            return EXECUTION_TYPE_FILE_EDIT

        if any(kw in desc for kw in ["validate", "check", "syntax", "scan", "verify"]):
            return EXECUTION_TYPE_VALIDATION

        if any(kw in desc for kw in ["read", "list", "show", "get", "status", "diff"]):
            if "git" in desc:
                return EXECUTION_TYPE_GIT
            return EXECUTION_TYPE_SHELL

        return EXECUTION_TYPE_SHELL

    def dispatch(
        self,
        step: Step,
        context: ExecutionContext,
    ) -> WrapperResult:
        """Execute step through appropriate wrapper."""
        exec_type = self.get_execution_type(step)

        if exec_type == EXECUTION_TYPE_GIT:
            return self._execute_git(step, context)
        elif exec_type == EXECUTION_TYPE_FILE_EDIT:
            return self._execute_file_edit(step, context)
        elif exec_type == EXECUTION_TYPE_VALIDATION:
            return self._execute_validation(step, context)
        else:
            return self._execute_shell(step, context)

    def _execute_shell(self, step: Step, context: ExecutionContext) -> WrapperResult:
        """Execute shell command through SafeShell."""
        command = step.input_data.get("command", step.description)

        result = self._shell.execute(command)
        return result

    def _execute_git(self, step: Step, context: ExecutionContext) -> WrapperResult:
        """Execute git command through SafeGit."""
        command = step.input_data.get("command", step.description.replace("git ", ""))

        result = self._git.execute(command)
        return result

    def _execute_file_edit(self, step: Step, context: ExecutionContext) -> WrapperResult:
        """Execute file edit through SafeFileEdit."""
        file_path = step.input_data.get("file_path")
        content = step.input_data.get("content", "")
        create_if_missing = step.input_data.get("create_if_missing", False)

        if not file_path:
            return WrapperResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command="file_edit",
                blocked_reason="No file_path provided",
            )

        result = self._file_edit.edit(file_path, content, create_if_missing=create_if_missing)
        return result

    def _execute_validation(self, step: Step, context: ExecutionContext) -> WrapperResult:
        """Execute validation through SafeValidation."""
        file_path = step.input_data.get("file_path")
        validation_type = step.input_data.get("validation_type", "python_syntax")

        if not file_path:
            return WrapperResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command="validation",
                blocked_reason="No file_path provided",
            )

        if validation_type == "python_syntax":
            return self._validation.validate_python_syntax(file_path)
        elif validation_type == "json_syntax":
            return self._validation.validate_json_syntax(file_path)
        elif validation_type == "yaml_syntax":
            return self._validation.validate_yaml_syntax(file_path)
        elif validation_type == "shell_syntax":
            return self._validation.validate_shell_syntax(file_path)
        elif validation_type == "secret_scan":
            return self._validation.scan_for_secrets(file_path)
        else:
            return WrapperResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command="validation",
                blocked_reason=f"Unknown validation type: {validation_type}",
            )

    def get_wrapper_audit_log(self) -> list[dict]:
        """Get combined audit log from all wrappers."""
        logs = []
        logs.extend(self._shell.get_audit_log())
        logs.extend(self._git.get_audit_log())
        return logs

    def get_shell(self) -> SafeShell:
        return self._shell

    def get_git(self) -> SafeGit:
        return self._git

    def get_file_edit(self) -> SafeFileEdit:
        return self._file_edit

    def get_validation(self) -> SafeValidation:
        return self._validation


class ToolExecutor:
    """Coordinates execution with audit, rollback, and retry logic."""

    def __init__(self, dry_run: bool = True, timeout: int = 30, max_retries: int = 0):
        self.dispatcher = ExecutionStepDispatcher(dry_run=dry_run, timeout=timeout)
        self.dry_run = dry_run
        self.timeout = timeout
        self.max_retries = max_retries
        self._execution_states: dict[str, ExecutionState] = {}

    def execute_step(
        self,
        step: Step,
        task: Task,
    ) -> tuple[Step, Task]:
        """Execute step through dispatcher and update task with results."""
        context = ExecutionContext(
            task_id=task.task_id,
            step_id=step.step_id,
            dry_run=task.dry_run,
            timeout=self.timeout,
            max_retries=self.max_retries,
            approved=task.approval_status == "approved",
        )

        execution_key = f"{task.task_id}:{step.step_id}"
        state = self._execution_states.get(execution_key, ExecutionState(
            task_id=task.task_id,
            step_id=step.step_id,
        ))
        state.status = "running"
        state.attempts += 1
        state.last_attempt = datetime.now()
        state.wrapper_used = self.dispatcher.get_execution_type(step)

        step.status = StepStatus.RUNNING
        step.started_at = datetime.now()
        task.add_timeline(
            event_type=TimelineEventType.EXECUTING,
            step_id=step.step_id,
            step_name=step.name,
            tool_used=step.tool,
            risk_level=self._convert_risk(step.risk_level),
            details=f"Executing via {state.wrapper_used}",
        )

        result = self.dispatcher.dispatch(step, context)

        state.last_result = {
            "status": result.status.value,
            "risk": result.risk_level.value,
            "output": result.output,
            "error": result.error,
            "dry_run": result.dry_run,
        }

        exec_type = self.dispatcher.get_execution_type(step)
        state.execution_type = exec_type

        if result.rollback_metadata:
            state.rollback_metadata.update(result.rollback_metadata)
            if not task.rollback.enabled:
                task.rollback.enabled = True
                task.rollback.created_at = datetime.now()
            if result.rollback_metadata.get("backup_path"):
                task.rollback.instructions.append(
                    f"Restore from backup: {result.rollback_metadata.get('backup_path')}"
                )

        step.log.extend(result.audit_log or [])

        if result.status == ExecutionStatus.BLOCKED:
            step.status = StepStatus.FAILED
            step.error = result.blocked_reason
            step.completed_at = datetime.now()
            self._update_task_on_blocked(task, step, result)
            self._execution_states[execution_key] = state
            return step, task

        if result.status == ExecutionStatus.FAILED:
            step.status = StepStatus.FAILED
            step.error = result.error
            step.completed_at = datetime.now()
            task.add_timeline(
                event_type=TimelineEventType.FAILED,
                step_id=step.step_id,
                step_name=step.name,
                tool_used=step.tool,
                risk_level=self._convert_risk(step.risk_level),
                details=f"Execution failed: {result.error}",
            )
            step.log.append(f"FAILED: {result.error}")
            self._execution_states[execution_key] = state
            return step, task

        if result.status == ExecutionStatus.DRY_RUN:
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.now()
            step.output_data = {"dry_run": True, "result": result.output}
            task.add_timeline(
                event_type=TimelineEventType.COMPLETED,
                step_id=step.step_id,
                step_name=step.name,
                tool_used=step.tool,
                risk_level=self._convert_risk(step.risk_level),
                details="Dry-run completed",
            )
            step.log.append(f"DRY-RUN: {result.output}")
            self._execution_states[execution_key] = state
            return step, task

        step.status = StepStatus.COMPLETED
        step.completed_at = datetime.now()
        step.output_data = {
            "result": result.output,
            "status": result.status.value,
            "execution_type": exec_type,
        }

        if result.error:
            step.error = result.error

        task.add_timeline(
            event_type=TimelineEventType.VALIDATED,
            step_id=step.step_id,
            step_name=step.name,
            tool_used=step.tool,
            risk_level=self._convert_risk(step.risk_level),
            details=f"Completed via {exec_type}",
        )

        task.add_timeline(
            event_type=TimelineEventType.COMPLETED,
            step_id=step.step_id,
            step_name=step.name,
            tool_used=step.tool,
            risk_level=self._convert_risk(step.risk_level),
            details="Step completed successfully",
        )

        step.log.append(f"COMPLETED: {result.output}")
        self._execution_states[execution_key] = state
        return step, task

    def _update_task_on_blocked(self, task: Task, step: Step, result: WrapperResult) -> None:
        """Update task timeline when operation is blocked."""
        if result.requires_approval():
            task.approval_required = True
            step.status = StepStatus.AWAITING_APPROVAL
            task.add_timeline(
                event_type=TimelineEventType.AWAITING_APPROVAL,
                step_id=step.step_id,
                step_name=step.name,
                tool_used=step.tool,
                risk_level=self._convert_risk(step.risk_level),
                details=f"Blocked - approval required: {result.blocked_reason}",
            )
        else:
            task.add_timeline(
                event_type=TimelineEventType.FAILED,
                step_id=step.step_id,
                step_name=step.name,
                tool_used=step.tool,
                risk_level=self._convert_risk(step.risk_level),
                details=f"Blocked: {result.blocked_reason}",
            )

    def _convert_risk(self, risk: ModelRiskLevel) -> ModelRiskLevel:
        """RiskLevel already matches between models and execution wrappers."""
        return risk

    def get_execution_state(self, task_id: str, step_id: str) -> ExecutionState | None:
        """Get execution state for retry tracking."""
        return self._execution_states.get(f"{task_id}:{step_id}")

    def get_all_audit_logs(self) -> list[dict]:
        """Get all audit logs from dispatcher."""
        return self.dispatcher.get_wrapper_audit_log()

    def can_retry(self, task_id: str, step_id: str) -> bool:
        """Check if step can be retried."""
        state = self.get_execution_state(task_id, step_id)
        if not state:
            return False
        return state.attempts < self.max_retries and state.status == "running"

    def get_dispatcher(self) -> ExecutionStepDispatcher:
        """Get the dispatcher for external access."""
        return self.dispatcher