"""AgentOS Orchestrator Engine - Core task orchestration logic."""

from datetime import datetime
from typing import Any

from orchestrator.models import (
    Task,
    TaskStatus,
    Step,
    StepStatus,
    RiskLevel,
    ToolType,
    ExecutionPreview,
    TimelineEventType,
)
from orchestrator.store import TaskStore
from orchestrator.router import StepRouter
from orchestrator.approvals import ApprovalQueue
from orchestrator.executor import ToolExecutor, ExecutionStepDispatcher, ExecutionContext


class Orchestrator:
    def __init__(self, store: TaskStore | None = None, dry_run_default: bool = True, timeout: int = 30):
        self.store = store or TaskStore()
        self.router = StepRouter()
        self.dry_run_default = dry_run_default
        self.approvals = ApprovalQueue()
        self.executor = ToolExecutor(dry_run=dry_run_default, timeout=timeout, max_retries=0)
        self.execution_dispatcher = self.executor.get_dispatcher()
        self.timeout = timeout

    def create_task(
        self,
        name: str,
        description: str,
        initial_data: dict[str, Any] | None = None,
        dry_run: bool | None = None,
    ) -> Task:
        dry_run = dry_run if dry_run is not None else self.dry_run_default
        task = Task(
            name=name,
            description=description,
            status=TaskStatus.PENDING,
            dry_run=dry_run,
            metadata={"initial_data": initial_data or {}},
            logs=[f"Task created at {datetime.now().isoformat()}"],
        )
        task.add_timeline(
            event_type=TimelineEventType.CREATED,
            details=f"Task '{name}' created (dry_run={dry_run})",
        )
        return self.store.create(task)

    def generate_plan(self, task_id: str, step_specs: list[dict[str, str]]) -> Task | None:
        task = self.store.get(task_id)
        if not task:
            return None

        task.status = TaskStatus.PLANNING
        task.logs.append(f"Plan generation started at {datetime.now().isoformat()}")

        steps = []
        for spec in step_specs:
            step = self.router.route_step(
                step_name=spec.get("name", "Unnamed Step"),
                step_description=spec.get("description", ""),
                context=spec.get("context", {}),
            )
            task.add_timeline(
                event_type=TimelineEventType.ROUTED,
                step_id=step.step_id,
                step_name=step.name,
                tool_used=step.tool,
                risk_level=step.risk_level,
                details=f"Routed to {step.tool.value} ({step.purpose})",
            )
            steps.append(step)

        from orchestrator.models import Plan

        plan = Plan(
            name=f"Plan for {task.name}",
            description=task.description,
            steps=steps,
            total_steps=len(steps),
            completed_steps=0,
        )
        task.plan = plan
        task.status = TaskStatus.READY
        task.add_timeline(
            event_type=TimelineEventType.PLANNED,
            details=f"Plan generated with {len(steps)} steps",
        )

        task.logs.append(
            f"Plan generated with {len(steps)} steps at {datetime.now().isoformat()}"
        )

        return self.store.update(task)

    def preview_execution(self, task_id: str) -> list[ExecutionPreview] | None:
        task = self.store.get(task_id)
        if not task or not task.plan:
            return None

        previews = []
        for step in task.plan.steps:
            action_desc = f"Execute {step.tool.value} for: {step.name}"
            approval_needed = self.router.requires_approval(step)

            files_affected = []
            if step.tool == ToolType.LOCAL_SCRIPT:
                files_affected = step.input_data.get("scripts", [])
            elif step.tool in (ToolType.OPENCODE, ToolType.CODEX):
                files_affected = step.input_data.get("files", [])

            previews.append(
                ExecutionPreview(
                    step_id=step.step_id,
                    step_name=step.name,
                    tool=step.tool,
                    purpose=step.purpose,
                    risk_level=step.risk_level,
                    action_description=action_desc,
                    files_affected=files_affected,
                    approval_needed=approval_needed,
                )
            )

        return previews

    def execute_step(self, task_id: str, step_id: str) -> Task | None:
        import time

        task = self.store.get(task_id)
        if not task or not task.plan:
            return None

        step = next((s for s in task.plan.steps if s.step_id == step_id), None)
        if not step:
            return None

        start_time = time.time()

        if (
            self.router.requires_approval(step)
            and not task.dry_run
            and step.status != StepStatus.AWAITING_APPROVAL
        ):
            step.status = StepStatus.AWAITING_APPROVAL
            task.approval_required = True
            self.approvals.enqueue(
                task_id=task.task_id,
                step_id=step.step_id,
                risk_level=step.risk_level.value,
                tool=step.tool.value,
                step_name=step.name,
            )
            task.add_timeline(
                event_type=TimelineEventType.AWAITING_APPROVAL,
                step_id=step.step_id,
                step_name=step.name,
                tool_used=step.tool,
                risk_level=step.risk_level,
                details=f"Step requires approval ({step.risk_level.value} risk)",
            )
            task.logs.append(
                f"Step {step_id} requires approval at {datetime.now().isoformat()}"
            )
            return self.store.update(task)

        step, task = self.executor.execute_step(step, task)

        task.plan.completed_steps = sum(
            1 for s in task.plan.steps if s.status == StepStatus.COMPLETED
        )

        if task.plan.completed_steps == task.plan.total_steps:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.logs.append(
                f"Task completed at {datetime.now().isoformat()}"
            )

        return self.store.update(task)

    def execute_all_steps(self, task_id: str) -> Task | None:
        task = self.store.get(task_id)
        if not task or not task.plan:
            return None

        task.execution_count += 1
        task.add_event("execution_started", f"Execution #{task.execution_count}")
        task.add_timeline(
            event_type=TimelineEventType.EXECUTING,
            details=f"Execution #{task.execution_count} started",
        )
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self.store.update(task)

        for step in task.plan.steps:
            result = self.execute_step(task_id, step.step_id)
            if result:
                task = result
            if task.plan and any(
                s.status == StepStatus.AWAITING_APPROVAL for s in task.plan.steps
            ):
                task.status = TaskStatus.PAUSED
                task.add_timeline(
                    event_type=TimelineEventType.PAUSED,
                    details="Task paused - approval required",
                )
                task.logs.append("Task paused - approval required")
                break

        if task.status == TaskStatus.COMPLETED:
            task.add_timeline(
                event_type=TimelineEventType.COMPLETED,
                details=f"Task completed ({task.plan.completed_steps}/{task.plan.total_steps} steps)",
            )
        elif task.status == TaskStatus.FAILED:
            task.add_timeline(
                event_type=TimelineEventType.FAILED,
                details="Task failed",
            )

        return self.store.update(task)

    def approve_step(self, task_id: str, step_id: str, approved: bool) -> Task | None:
        return self.approve_step_with_reason(
            task_id,
            step_id,
            approved,
            decided_by="unknown",
            reason=None,
        )

    def approve_step_with_reason(
        self,
        task_id: str,
        step_id: str,
        approved: bool,
        decided_by: str = "unknown",
        reason: str | None = None,
    ) -> Task | None:
        task = self.store.get(task_id)
        if not task or not task.plan:
            return None

        step = next((s for s in task.plan.steps if s.step_id == step_id), None)
        if not step:
            return None

        if approved:
            task.approval_status = "approved"
            task.add_timeline(
                event_type=TimelineEventType.APPROVED,
                step_id=step.step_id,
                step_name=step.name,
                tool_used=step.tool,
                risk_level=step.risk_level,
                details=f"Approved by {decided_by}" + (f": {reason}" if reason else ""),
                user=decided_by,
            )
            self.approvals.decide(
                task_id=task.task_id,
                step_id=step.step_id,
                decision="approved",
                decided_by=decided_by,
                reason=reason,
            )
            task.logs.append(
                f"Step {step_id} approved by {decided_by} at {datetime.now().isoformat()}"
            )
            if reason:
                task.logs.append(f"Approval reason: {reason}")
            # Persist the approval decision/logs before resuming execution.
            self.store.update(task)
            return self.execute_step(task_id, step_id)
        else:
            task.approval_status = "rejected"
            task.add_timeline(
                event_type=TimelineEventType.REJECTED,
                step_id=step.step_id,
                step_name=step.name,
                tool_used=step.tool,
                risk_level=step.risk_level,
                details=f"Rejected by {decided_by}" + (f": {reason}" if reason else ""),
                user=decided_by,
            )
            step.status = StepStatus.SKIPPED
            self.approvals.decide(
                task_id=task.task_id,
                step_id=step.step_id,
                decision="rejected",
                decided_by=decided_by,
                reason=reason,
            )
            task.logs.append(
                f"Step {step_id} rejected by {decided_by} at {datetime.now().isoformat()}"
            )
            if reason:
                task.logs.append(f"Rejection reason: {reason}")
            return self.store.update(task)

    def get_task(self, task_id: str) -> Task | None:
        return self.store.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        if status:
            return self.store.list_by_status(status)
        return self.store.list_all()

    def add_step(self, task_id: str, name: str, description: str) -> Task | None:
        task = self.store.get(task_id)
        if not task or not task.plan:
            return None

        step = self.router.route_step(name, description)
        task.plan.steps.append(step)
        task.plan.total_steps += 1

        task.logs.append(f"Step added: {name} at {datetime.now().isoformat()}")
        return self.store.update(task)

    def get_task_summary(self, task_id: str) -> dict | None:
        task = self.store.get(task_id)
        if not task:
            return None

        summary = {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "dry_run": task.dry_run,
            "created_at": task.created_at.isoformat(),
            "plan": None,
        }

        if task.plan:
            summary["plan"] = {
                "total_steps": task.plan.total_steps,
                "completed_steps": task.plan.completed_steps,
                "steps": [
                    {
                        "step_id": s.step_id,
                        "name": s.name,
                        "tool": s.tool.value,
                        "risk": s.risk_level.value,
                        "status": s.status.value,
                        "cost": s.cost_estimate,
                    }
                    for s in task.plan.steps
                ],
            }

        return summary

    def get_execution_audit_log(self) -> list[dict]:
        """Get combined audit log from all execution wrappers."""
        return self.executor.get_all_audit_logs()

    def get_execution_state(self, task_id: str, step_id: str) -> dict | None:
        """Get execution state for a step."""
        state = self.executor.get_execution_state(task_id, step_id)
        if not state:
            return None
        return {
            "task_id": state.task_id,
            "step_id": state.step_id,
            "status": state.status,
            "attempts": state.attempts,
            "last_attempt": state.last_attempt.isoformat() if state.last_attempt else None,
            "wrapper_used": state.wrapper_used,
            "execution_type": state.execution_type,
            "rollback_metadata": state.rollback_metadata,
            "last_result": state.last_result,
        }

    def get_dispatcher(self) -> ExecutionStepDispatcher:
        """Get the execution dispatcher."""
        return self.execution_dispatcher
