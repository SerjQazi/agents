#!/usr/bin/env python3
"""AgentOS Orchestrator CLI."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import Orchestrator, TaskStatus
from orchestrator.roles_loader import RoleLoader
from orchestrator.models import StepStatus


def cmd_create(args):
    orch = Orchestrator(dry_run_default=not args.execute)
    initial_data = {}
    if args.data:
        initial_data = json.loads(args.data)

    task = orch.create_task(
        name=args.name,
        description=args.description,
        initial_data=initial_data,
    )
    print(f"Task created: {task.task_id}")
    print(f"  Name: {task.name}")
    print(f"  Dry-run: {task.dry_run}")
    return task.task_id


def cmd_plan(args):
    orch = Orchestrator()
    step_specs = []
    if args.steps_file:
        with open(args.steps_file) as f:
            step_specs = json.load(f)
    else:
        step_specs = json.loads(args.steps) if args.steps else []

    task = orch.generate_plan(args.task_id, step_specs)
    if not task:
        print(f"Error: Task {args.task_id} not found")
        return 1

    print(f"Plan generated for task: {task.task_id}")
    print(f"  Steps: {task.plan.total_steps}")
    for i, step in enumerate(task.plan.steps, 1):
        print(f"    {i}. {step.name}")
        print(f"       Tool: {step.tool.value} | Risk: {step.risk_level.value} | Cost: {step.cost_estimate}")
    return 0


def cmd_preview(args):
    orch = Orchestrator()
    previews = orch.preview_execution(args.task_id)
    if not previews:
        print(f"Error: Task {args.task_id} not found or no plan")
        return 1

    print(f"Execution Preview for task: {args.task_id}")
    print("=" * 60)
    for p in previews:
        print(f"\nStep: {p.step_name}")
        print(f"  Tool: {p.tool.value}")
        print(f"  Purpose: {p.purpose}")
        print(f"  Risk: {p.risk_level.value}")
        print(f"  Action: {p.action_description}")
        if p.files_affected:
            print(f"  Files: {', '.join(p.files_affected)}")
        print(f"  Approval needed: {'YES' if p.approval_needed else 'NO'}")
    return 0


def cmd_execute(args):
    orch = Orchestrator()
    if args.all:
        task = orch.execute_all_steps(args.task_id)
    else:
        task = orch.execute_step(args.task_id, args.step_id)

    if not task:
        print(f"Error: Task {args.task_id} not found")
        return 1

    print(f"Execution complete for task: {task.task_id}")
    print(f"  Status: {task.status.value}")
    if task.plan:
        print(f"  Progress: {task.plan.completed_steps}/{task.plan.total_steps} steps")
    return 0


def cmd_status(args):
    orch = Orchestrator()
    if args.task_id:
        task = orch.get_task(args.task_id)
        if not task:
            print(f"Error: Task {args.task_id} not found")
            return 1
        print(f"Task: {task.task_id}")
        print(f"  Name: {task.name}")
        print(f"  Status: {task.status.value}")
        print(f"  Dry-run: {task.dry_run}")
        print(f"  Created: {task.created_at.isoformat()}")
        if task.plan:
            print(f"  Plan steps: {task.plan.completed_steps}/{task.plan.total_steps}")
            for step in task.plan.steps:
                print(f"    - {step.name}: {step.status.value}")
        print(f"\nLogs:")
        for log in task.logs:
            print(f"  {log}")
    else:
        tasks = orch.list_tasks()
        print(f"Total tasks: {len(tasks)}")
        for task in tasks:
            print(f"  {task.task_id}: {task.name} [{task.status.value}]")
    return 0


def cmd_approve(args):
    orch = Orchestrator()
    approved = not args.reject
    task = orch.approve_step(args.task_id, args.step_id, approved)
    if not task:
        print(f"Error: Task {args.task_id} or step {args.step_id} not found")
        return 1

    print(f"Step {args.step_id} {'approved' if approved else 'rejected'}")
    print(f"  Task status: {task.status.value}")
    return 0


def cmd_add_step(args):
    orch = Orchestrator()
    task = orch.add_step(args.task_id, args.name, args.description)
    if not task:
        print(f"Error: Task {args.task_id} not found")
        return 1

    print(f"Step added to task {args.task_id}")
    print(f"  Total steps: {task.plan.total_steps}")
    return 0


def cmd_summary(args):
    orch = Orchestrator()
    summary = orch.get_task_summary(args.task_id)
    if not summary:
        print(f"Error: Task {args.task_id} not found")
        return 1

    print(json.dumps(summary, indent=2))
    return 0


def cmd_test(args):
    """Run safety verification tests."""
    orch = Orchestrator()
    print("=" * 60)
    print("AgentOS Orchestrator Safety Test")
    print("=" * 60)

    tests_passed = 0
    tests_failed = 0
    pending_before = len(orch.approvals.list_pending())

    print("\n[TEST 1] Safe tasks complete automatically (dry-run)")
    task1 = orch.create_task(
        name="Test Safe Task",
        description="Read files and generate report",
        dry_run=True
    )
    step_specs_1 = [
        {"name": "Read files", "description": "Read files from disk", "context": {}},
        {"name": "Generate report", "description": "Create summary report", "context": {}},
    ]
    task1 = orch.generate_plan(task1.task_id, step_specs_1)
    task1 = orch.execute_all_steps(task1.task_id)

    if task1.status.value == "completed":
        print("  PASS: Safe tasks completed automatically")
        tests_passed += 1
    else:
        print(f"  FAIL: Expected 'completed', got '{task1.status.value}'")
        tests_failed += 1

    pending_after_safe = len(orch.approvals.list_pending())
    if pending_after_safe == pending_before:
        print("  PASS: Safe task bypassed approval queue")
        tests_passed += 1
    else:
        print(f"  FAIL: Safe task unexpectedly added approvals (before={pending_before}, after={pending_after_safe})")
        tests_failed += 1

    print("\n[TEST 2] High-risk tasks pause for approval")
    task2 = orch.create_task(
        name="Test High Risk",
        description="Git push to remote",
        dry_run=False
    )
    step_specs_2 = [
        {"name": "Git push", "description": "Push to remote repository", "context": {}},
    ]
    task2 = orch.generate_plan(task2.task_id, step_specs_2)
    task2 = orch.execute_all_steps(task2.task_id)
    pending_after_risk = orch.approvals.list_pending()
    queued_for_task2 = [r for r in pending_after_risk if r.task_id == task2.task_id]

    if task2.status.value == "paused" and task2.approval_required:
        print("  PASS: High-risk task paused for approval")
        tests_passed += 1
    else:
        print(f"  FAIL: Expected 'paused' with approval, got '{task2.status.value}', approval={task2.approval_required}")
        tests_failed += 1

    if queued_for_task2:
        print("  PASS: High-risk task entered approval queue")
        tests_passed += 1
    else:
        print("  FAIL: High-risk task did not enter approval queue")
        tests_failed += 1

    print("\n[TEST 3] Approval completes the paused step")
    step_id_2 = task2.plan.steps[0].step_id
    task2 = orch.approve_step(task2.task_id, step_id_2, True)
    rec2 = orch.approvals.get(task2.task_id, step_id_2)

    if task2.status.value == "completed" and task2.plan.steps[0].status.value == "completed":
        print("  PASS: Approval completed the paused step")
        tests_passed += 1
    else:
        print(f"  FAIL: Expected 'completed', got task={task2.status.value}, step={task2.plan.steps[0].status.value}")
        tests_failed += 1

    if rec2 and rec2.status == "approved" and rec2.decided_at:
        print("  PASS: Approval decision recorded with timestamp")
        tests_passed += 1
    else:
        print("  FAIL: Approval decision not recorded correctly")
        tests_failed += 1

    if any("approved by" in log.lower() for log in task2.logs):
        print("  PASS: Approval decision logged to task")
        tests_passed += 1
    else:
        print("  FAIL: Approval decision missing from task logs")
        tests_failed += 1

    print("\n[TEST 4] Rejected steps stay blocked")
    task3 = orch.create_task(
        name="Test Rejection",
        description="Deploy to production",
        dry_run=False
    )
    step_specs_3 = [
        {"name": "Deploy", "description": "Deploy to production server", "context": {}},
    ]
    task3 = orch.generate_plan(task3.task_id, step_specs_3)
    task3 = orch.execute_all_steps(task3.task_id)
    step_id_3 = task3.plan.steps[0].step_id

    task3 = orch.approve_step(task3.task_id, step_id_3, False)
    rec3 = orch.approvals.get(task3.task_id, step_id_3)

    if task3.plan.steps[0].status.value == "skipped":
        print("  PASS: Rejected step is skipped/blocked")
        tests_passed += 1
    else:
        print(f"  FAIL: Expected 'skipped', got '{task3.plan.steps[0].status.value}'")
        tests_failed += 1

    if rec3 and rec3.status == "rejected" and rec3.decided_at:
        print("  PASS: Rejection decision recorded with timestamp")
        tests_passed += 1
    else:
        print("  FAIL: Rejection decision not recorded correctly")
        tests_failed += 1

    if any("rejected by" in log.lower() for log in task3.logs):
        print("  PASS: Rejection decision logged to task")
        tests_passed += 1
    else:
        print("  FAIL: Rejection decision missing from task logs")
        tests_failed += 1

    print("\n[TEST 5] No dangerous actions execute automatically (dry-run mode)")
    dangerous_steps = [
        {"name": "Sudo command", "description": "Run sudo rm -rf /", "context": {}},
        {"name": "Git push", "description": "Push to remote", "context": {}},
        {"name": "Systemctl", "description": "Restart critical service", "context": {}},
        {"name": "Install package", "description": "Install new package", "context": {}},
        {"name": "Database drop", "description": "Drop database", "context": {}},
    ]

    all_safe = True
    for step_spec in dangerous_steps:
        task_d = orch.create_task(
            name=f"Test Dangerous: {step_spec['name']}",
            description=step_spec["description"],
            dry_run=False
        )
        task_d = orch.generate_plan(task_d.task_id, [step_spec])
        task_d = orch.execute_all_steps(task_d.task_id)

        previews = orch.preview_execution(task_d.task_id)
        if previews and previews[0].approval_needed:
            print(f"  PASS: {step_spec['name']} requires approval")
            tests_passed += 1
        else:
            print(f"  FAIL: {step_spec['name']} did NOT require approval")
            tests_failed += 1
            all_safe = False

    print("\n[TEST 6] Execution wrapper hardening (shell/git/python/file)")
    from orchestrator.execution import SafeShell, SafeGit, SafePython, SafeFileEdit, SafeValidation

    shell = SafeShell(dry_run=False)
    git = SafeGit(dry_run=False)
    py = SafePython(dry_run=False)
    fe = SafeFileEdit(dry_run=False)
    val = SafeValidation(dry_run=False)

    # Blocked: rm -rf /
    r = shell.execute("rm -rf /")
    if r.status.value == "blocked":
        print("  PASS: shell blocks 'rm -rf /'")
        tests_passed += 1
    else:
        print(f"  FAIL: shell did not block rm -rf / (status={r.status.value})")
        tests_failed += 1

    # Blocked: command injection
    r = shell.execute("ls; touch PWNED")
    if r.status.value == "blocked":
        print("  PASS: shell blocks ';' chaining")
        tests_passed += 1
    else:
        print("  FAIL: shell did not block ';' chaining")
        tests_failed += 1

    # Blocked: redirection
    r = shell.execute("echo hi > file")
    if r.status.value == "blocked":
        print("  PASS: shell blocks redirection")
        tests_passed += 1
    else:
        print("  FAIL: shell did not block redirection")
        tests_failed += 1

    # Blocked: absolute path outside repo
    r = shell.execute("cat /etc/passwd")
    if r.status.value == "blocked":
        print("  PASS: shell blocks /etc/passwd")
        tests_passed += 1
    else:
        print("  FAIL: shell did not block /etc/passwd")
        tests_failed += 1

    # Blocked: git injection
    r = git.execute("status; touch PWNED")
    if r.status.value == "blocked":
        print("  PASS: git blocks ';' injection")
        tests_passed += 1
    else:
        print("  FAIL: git did not block ';' injection")
        tests_failed += 1

    # Blocked: git push
    r = git.execute("push origin main")
    if r.status.value == "blocked":
        print("  PASS: git blocks push")
        tests_passed += 1
    else:
        print("  FAIL: git did not block push")
        tests_failed += 1

    # Blocked: git reset --hard
    r = git.execute("reset --hard HEAD~1")
    if r.status.value == "blocked":
        print("  PASS: git blocks reset --hard (approval-gated)")
        tests_passed += 1
    else:
        print("  FAIL: git did not block reset --hard")
        tests_failed += 1

    # Blocked: SafePython.execute
    r = py.execute("import subprocess\nprint('x')\n")
    if r.status.value == "blocked":
        print("  PASS: python execution is disabled")
        tests_passed += 1
    else:
        print("  FAIL: python execution was not blocked")
        tests_failed += 1

    # Allowed: python syntax validation
    r = py.validate_syntax("print('ok')\n")
    if r.status.value == "executed":
        print("  PASS: python syntax validation works")
        tests_passed += 1
    else:
        print("  FAIL: python syntax validation failed")
        tests_failed += 1

    # Blocked: file edit outside repo
    r = fe.edit("/etc/passwd", "nope\n", create_if_missing=False)
    if r.status.value == "blocked":
        print("  PASS: file edit blocks /etc/passwd")
        tests_passed += 1
    else:
        print("  FAIL: file edit did not block /etc/passwd")
        tests_failed += 1

    # Blocked: file edit through symlink escape
    from pathlib import Path
    link_path = Path("/home/agentzero/agents/tmp_symlink_escape")
    try:
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to("/etc/passwd")
        r = fe.edit(str(link_path), "nope\n", create_if_missing=False)
        if r.status.value == "blocked":
            print("  PASS: file edit blocks symlink escape")
            tests_passed += 1
        else:
            print("  FAIL: file edit did not block symlink escape")
            tests_failed += 1
    finally:
        try:
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
        except OSError:
            pass

    # Allowed: safe file edit inside repo with backup metadata
    target = Path("/home/agentzero/agents/tmp_safe_edit_test.txt")
    target.write_text("before\n", encoding="utf-8")
    r = fe.edit(str(target), "after\n", create_if_missing=False)
    meta_ok = bool(r.rollback_metadata.get("backup_metadata")) and bool(r.rollback_metadata.get("original_path"))
    if r.status.value == "executed" and meta_ok:
        print("  PASS: safe file edit works and records backup metadata")
        tests_passed += 1
    else:
        print("  FAIL: safe file edit did not record expected rollback metadata")
        tests_failed += 1

    # Allowed: JSON validation
    jf = Path("/home/agentzero/agents/tmp_validation_test.json")
    jf.write_text('{"ok": true}\n', encoding="utf-8")
    r = val.validate_json_syntax(str(jf))
    if r.status.value == "executed":
        print("  PASS: JSON validation works")
        tests_passed += 1
    else:
        print("  FAIL: JSON validation failed")
        tests_failed += 1

    # Allowed: git status / git diff
    r1 = git.execute("status")
    r2 = git.execute("diff")
    if r1.status.value in ("executed", "failed") and r2.status.value in ("executed", "failed"):
        # In a dirty repo, diff may be executed; in a clean repo, diff still executes with rc=0.
        print("  PASS: git status/diff still execute")
        tests_passed += 1
    else:
        print("  FAIL: git status/diff did not execute as expected")
        tests_failed += 1

    # Allowed: ls inside repo
    r = shell.execute("ls /home/agentzero/agents")
    if r.status.value == "executed":
        print("  PASS: shell ls inside repo works")
        tests_passed += 1
    else:
        print("  FAIL: shell ls inside repo did not execute")
        tests_failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {tests_passed} passed, {tests_failed} failed")
    print("=" * 60)

    if tests_failed > 0:
        return 1
    return 0


def cmd_roles(args):
    loader = RoleLoader(roles_dir=args.roles_dir)
    roles_map, errors = loader.load_all(strict=False)

    if args.recommend:
        rec = loader.recommend_role(args.recommend)
        if not rec:
            print("No recommendation available (no roles loaded or no match).")
            return 2
        role = loader.get_role(rec.role_id)
        if role:
            print(f"{role.id} ({role.name}) score={rec.score:.2f} reason={rec.reason}")
        else:
            print(f"{rec.role_id} score={rec.score:.2f} reason={rec.reason}")
        return 0

    if args.list:
        for role_id in sorted(roles_map.keys()):
            print(role_id)
        if errors:
            print(f"\nErrors: {len(errors)} (run with --validate for details)")
        return 0 if not errors else 2

    if args.validate:
        print(f"Roles dir: {loader.roles_dir}")
        print(f"Loaded roles: {len(roles_map)}")
        for role_id in sorted(roles_map.keys()):
            role = roles_map[role_id]
            print(f"- {role.id}: {role.name} ({role.cost_tier}) preferred={role.preferred_model}")

        if errors:
            print("\nRole file errors:")
            for e in errors:
                print(f"- {e.path}: {e.error}")
            return 2
        return 0

    for role_id in sorted(roles_map.keys()):
        role = roles_map[role_id]
        print(f"{role.id}: {role.name}")
    if errors:
        print(f"\nErrors: {len(errors)} (run with --validate for details)")
        return 2
    return 0


def cmd_approvals(args):
    orch = Orchestrator()

    if args.approvals_cmd == "list":
        pending = orch.approvals.list_pending()
        print(f"Pending approvals: {len(pending)}")
        for r in pending:
            meta = []
            if r.risk_level:
                meta.append(f"risk={r.risk_level}")
            if r.tool:
                meta.append(f"tool={r.tool}")
            if r.step_name:
                meta.append(f"step={r.step_name}")
            meta_s = f" ({', '.join(meta)})" if meta else ""
            print(f"- {r.task_id} step={r.step_id} queued_at={r.created_at}{meta_s}")
        return 0

    if args.approvals_cmd == "show":
        records = orch.approvals.list_for_task(args.task_id)
        if not records:
            print(f"No approval records for task {args.task_id}")
            return 2
        print(f"Approval records for task {args.task_id}: {len(records)}")
        for r in records:
            line = f"- step={r.step_id} status={r.status} created_at={r.created_at}"
            if r.decided_at:
                line += f" decided_at={r.decided_at}"
            if r.decided_by:
                line += f" by={r.decided_by}"
            if r.reason:
                line += f" reason={r.reason}"
            print(line)
        return 0

    if args.approvals_cmd in ("approve", "reject"):
        task = orch.get_task(args.task_id)
        if not task or not task.plan:
            print(f"Error: Task {args.task_id} not found or has no plan")
            return 1

        awaiting = [s for s in task.plan.steps if s.status == StepStatus.AWAITING_APPROVAL]
        if not awaiting:
            print(f"No awaiting-approval steps for task {args.task_id}")
            return 2

        step = awaiting[0]
        decided_by = args.by or os.environ.get("USER", "unknown")
        reason = args.reason
        approved = args.approvals_cmd == "approve"

        updated = orch.approve_step_with_reason(
            task.task_id,
            step.step_id,
            approved,
            decided_by=decided_by,
            reason=reason,
        )
        if not updated:
            print(f"Error: Task {args.task_id} or step {step.step_id} not found")
            return 1

        action = "approved" if approved else "rejected"
        print(f"Step {step.step_id} {action} by {decided_by}")
        if reason:
            print(f"  Reason: {reason}")
        print(f"  Task status: {updated.status.value}")
        return 0

    print("Error: unknown approvals command")
    return 1


def cmd_timeline(args):
    """Show task execution timeline."""
    orch = Orchestrator()
    task = orch.store.get(args.task_id)
    if not task:
        print(f"Error: Task {args.task_id} not found")
        return 1

    if args.json or args.export:
        import json
        from datetime import datetime

        timeline_data = {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "total_duration_ms": task.total_duration_ms(),
            "timeline": [
                {
                    "event_type": e.event_type.value,
                    "timestamp": e.timestamp.isoformat(),
                    "step_id": e.step_id,
                    "step_name": e.step_name,
                    "role_used": e.role_used,
                    "tool_used": e.tool_used.value if e.tool_used else None,
                    "risk_level": e.risk_level.value if e.risk_level else None,
                    "duration_ms": e.duration_ms,
                    "details": e.details,
                    "user": e.user,
                }
                for e in task.timeline
            ],
        }

        if args.export:
            export_file = f"/home/agentzero/agents/orchestrator/reports/timeline_{task.task_id}.json"
            with open(export_file, "w") as f:
                json.dump(timeline_data, f, indent=2)
            print(f"Timeline exported to: {export_file}")
        else:
            print(json.dumps(timeline_data, indent=2))
        return 0

    print(f"Task: {task.task_id} - {task.name}")
    print(f"Status: {task.status.value}")
    print(f"Total duration: {task.total_duration_ms()}ms")
    print(f"\nTimeline ({len(task.timeline)} events):")
    print("-" * 70)

    for e in task.timeline:
        duration = e.duration_str() if e.duration_ms is not None else "-"
        step_info = f"{e.step_name}" if e.step_name else ""
        tool_info = f"[{e.tool_used.value}]" if e.tool_used else ""
        risk_info = f"⚠{e.risk_level.value}" if e.risk_level and e.risk_level.value != "safe" else ""
        print(f"  {e.timestamp.strftime('%H:%M:%S.%f')[:-3]} | {e.event_type.value:20} | {duration:8} | {step_info} {tool_info} {risk_info}")
        if e.details:
            print(f"                              {e.details}")

    print("-" * 70)
    return 0


def cmd_recovery_scan(args):
    """Scan all tasks and categorize by status."""
    from orchestrator.recovery import RecoveryManager

    rm = RecoveryManager()
    result = rm.scan_tasks()

    print("=== Task Recovery Scan ===")
    for category, tasks in result.items():
        if tasks:
            print(f"\n{category.upper()} ({len(tasks)}):")
            for t in tasks[:10]:
                timeline_status = "✓" if t.get("has_timeline") else "✗"
                approval_status = "⏳" if t.get("approval_required") else ""
                print(f"  {t['task_id']}: {t['name']} [{t['status']}] {timeline_status} {approval_status}")
            if len(tasks) > 10:
                print(f"  ... and {len(tasks) - 10} more")

    pending_approvals = rm.get_pending_approvals()
    if pending_approvals:
        print(f"\nPENDING APPROVALS ({len(pending_approvals)}):")
        for a in pending_approvals:
            print(f"  {a.get('task_id')}: {a.get('step_name')} [{a.get('risk_level')}]")

    return 0


def cmd_recovery_verify(args):
    """Verify task persistence."""
    from orchestrator.recovery import RecoveryManager

    rm = RecoveryManager()
    result = rm.recover_task(args.task_id)

    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        return 1

    print(f"=== Task Recovery Verification ===")
    print(f"Task: {result['task_id']} - {result['name']}")
    print(f"Status: {result['status']}")
    print(f"Recovery: {result['recovery_status']}")
    print(f"\nTimeline verification:")
    tv = result["timeline_verification"]
    print(f"  Has timeline: {tv['has_timeline']}")
    print(f"  Event count: {tv['event_count']}")
    print(f"  Total duration: {tv['total_duration_ms']}ms")
    print(f"  Has created: {tv['has_created_event']}")
    print(f"  Has completed: {tv['has_completed_event']}")

    return 0


def cmd_recovery_replay(args):
    """Replay task logs."""
    from orchestrator.recovery import RecoveryManager

    rm = RecoveryManager()
    print(rm.replay_logs(args.task_id))
    return 0


def cmd_recovery_organize(args):
    """Organize tasks into directories."""
    from orchestrator.recovery import TaskDirectoryManager

    tdm = TaskDirectoryManager()
    counts = tdm.organize_tasks()

    print("=== Task Organization ===")
    for category, count in counts.items():
        print(f"  {category}: {count} tasks moved")

    return 0


def cmd_recovery_stats(args):
    """Show directory statistics."""
    from orchestrator.recovery import TaskDirectoryManager

    tdm = TaskDirectoryManager()
    stats = tdm.get_directory_stats()

    print("=== Directory Statistics ===")
    for category, data in stats.items():
        print(f"\n{category.upper()} ({data['count']} tasks):")
        for t in data["tasks"][:5]:
            print(f"  - {t['task_id']}: {t['name']}")
        if len(data["tasks"]) > 5:
            print(f"  ... and {len(data['tasks']) - 5} more")

    return 0


def cmd_cleanup_tasks(args):
    """Cleanup old completed tasks."""
    from orchestrator.maintenance import CleanupManager

    cm = CleanupManager()
    dry_run = not getattr(args, "execute", False)

    print(f"=== Cleanup Tasks (dry_run={dry_run}) ===")
    print(f"Archiving completed tasks older than {args.days} days...")

    results = cm.cleanup_completed_tasks(older_than_days=args.days, dry_run=dry_run)

    print(f"\nArchived: {len(results['archived'])}")
    for t in results["archived"][:10]:
        print(f"  - {t}")
    if len(results["archived"]) > 10:
        print(f"  ... and {len(results['archived']) - 10} more")

    print(f"\nSkipped: {len(results['skipped'])}")
    print(f"Errors: {len(results['errors'])}")

    return 0


def cmd_cleanup_approvals(args):
    """Clean old approval records."""
    from orchestrator.maintenance import CleanupManager

    cm = CleanupManager()
    dry_run = not getattr(args, "execute", False)

    print(f"=== Cleanup Approvals (dry_run={dry_run}) ===")
    print(f"Removing approval records older than {args.days} days...")

    results = cm.cleanup_approvals(older_than_days=args.days, dry_run=dry_run)

    print(f"\nRemoved: {len(results['removed'])}")
    print(f"Kept: {len(results['kept'])}")
    print(f"Errors: {len(results['errors'])}")

    return 0


def cmd_detect_stale(args):
    """Detect stale tasks."""
    from orchestrator.maintenance import CleanupManager

    cm = CleanupManager()

    print(f"=== Stale Tasks (older than {args.days} days) ===")

    stale = cm.detect_stale_tasks(stale_days=args.days)

    print(f"\nFound {len(stale)} stale tasks:")
    for s in stale[:20]:
        print(f"  {s['task_id']}: {s['name']} [{s['status']}] - {s['days_stale']} days old")

    if len(stale) > 20:
        print(f"  ... and {len(stale) - 20} more")

    return 0


def cmd_detect_orphaned(args):
    """Detect orphaned timelines/approvals."""
    from orchestrator.maintenance import CleanupManager

    cm = CleanupManager()

    print("=== Orphaned Detection ===")

    if args.type in ("timelines", "all"):
        orphaned_timelines = cm.detect_orphaned_timelines()
        print(f"\nOrphaned timelines: {len(orphaned_timelines)}")
        for o in orphaned_timelines[:10]:
            print(f"  {o['task_id']}: {o['name']} [{o['issue']}]")

    if args.type in ("approvals", "all"):
        orphaned_approvals = cm.detect_orphaned_approvals()
        print(f"\nOrphaned approvals: {len(orphaned_approvals)}")
        for o in orphaned_approvals[:10]:
            print(f"  {o['task_id']}: {o['step_name']} [{o.get('status', 'unknown')}]")

    return 0


def cmd_verify_integrity(args):
    """Verify storage integrity."""
    from orchestrator.maintenance import CleanupManager

    cm = CleanupManager()

    print("=== Storage Integrity Check ===")

    results = cm.verify_storage_integrity()

    print(f"\nTasks in index: {results['total_tasks']}")
    print(f"Valid task files: {results['valid_tasks']}")
    print(f"Missing index: {results['missing_index']}")

    if results["corrupted"]:
        print(f"\nCorrupted tasks: {len(results['corrupted'])}")
        for c in results["corrupted"]:
            print(f"  {c['file']}: {c['issue']}")

    if results["empty_tasks"]:
        print(f"\nEmpty tasks: {len(results['empty_tasks'])}")

    print(f"\nArchive stats: {results['archive_stats']}")

    if not results["corrupted"] and not results["missing_index"]:
        print("\n✓ Storage integrity OK")

    return 0


def cmd_retention_policy(args):
    """Show retention policies."""
    from orchestrator.maintenance import RetentionPolicy

    print("=== Retention Policies ===")

    policy = RetentionPolicy.get_policy_summary()

    for status, days in policy.items():
        print(f"  {status}: {days} days")

    return 0


def cmd_exec_shell(args):
    """Execute safe shell command."""
    from orchestrator.execution import SafeShell

    dry_run = not getattr(args, "execute", False)
    shell = SafeShell(dry_run=dry_run)

    result = shell.execute(args.command)

    print(f"Status: {result.status.value}")
    print(f"Risk: {result.risk_level.value}")
    if result.blocked_reason:
        print(f"Blocked: {result.blocked_reason}")
    if result.output:
        print(f"Output: {result.output[:500]}")
    if result.error:
        print(f"Error: {result.error[:500]}")

    return 0


def cmd_exec_git(args):
    """Execute safe git command."""
    from orchestrator.execution import SafeGit

    dry_run = not getattr(args, "execute", False)
    git = SafeGit(dry_run=dry_run)

    # Phase 1: do not allow bypassing approvals via force flags.
    result = git.execute(args.command, force_approval=False)

    print(f"Status: {result.status.value}")
    print(f"Risk: {result.risk_level.value}")
    print(f"Approval required: {result.approval_required}")
    if result.blocked_reason:
        print(f"Blocked: {result.blocked_reason}")
    if result.output:
        print(f"Output: {result.output[:500]}")

    return 0


def cmd_exec_allowed(args):
    """List allowed commands."""
    from orchestrator.execution import SafeShell, SafeGit, SafePython

    if args.type == "shell":
        shell = SafeShell()
        allowed = shell.list_allowed_commands()
        print("=== Allowed Shell Commands ===")
        for cmd, variants in allowed.items():
            print(f"  {cmd}: {variants}")
    elif args.type == "git":
        git = SafeGit()
        allowed = git.list_allowed_operations()
        print("=== Allowed Git Operations ===")
        for op, cmds in allowed.items():
            print(f"  {op}: {cmds}")
    elif args.type == "python":
        python = SafePython()
        allowed = python.list_allowed_modules()
        print("=== Allowed Python Modules ===")
        for mod, desc in allowed.items():
            print(f"  {mod}: {desc}")

    return 0


def cmd_history(args):
    """Show task history and lifecycle events."""
    orch = Orchestrator()
    history = orch.store.get_task_history(args.task_id)
    if not history:
        print(f"Error: Task {args.task_id} not found")
        return 1

    print(f"Task: {history['task_id']} - {history['name']}")
    print(f"Status: {history['status']}")
    print(f"Created: {history['created_at']}")
    print(f"Updated: {history['updated_at']}")
    print(f"Execution count: {history['execution_count']}")
    print(f"\nLifecycle events ({len(history['lifecycle_events'])}):")
    for e in history['lifecycle_events']:
        print(f"  [{e['timestamp']}] {e['event']}: {e.get('details', '')}")
    print(f"\nLogs ({len(history['logs'])}):")
    for log in history['logs'][:20]:
        print(f"  {log}")
    return 0


def cmd_logs(args):
    """Show task execution logs."""
    orch = Orchestrator()
    logs = orch.store.get_execution_logs(args.task_id)
    if logs is None:
        print(f"Error: Task {args.task_id} not found")
        return 1

    print(f"Execution logs for task: {args.task_id}")
    for log in logs:
        print(log)
    return 0


def cmd_archive_cmd(args):
    """Archive a task."""
    orch = Orchestrator()
    task = orch.store.archive_task(args.task_id)
    if not task:
        print(f"Error: Task {args.task_id} not found")
        return 1

    print(f"Task {args.task_id} archived to: {task.archive_path}")
    return 0


def cmd_recent(args):
    """List recent tasks."""
    orch = Orchestrator()
    recent = orch.store.list_recent_tasks(args.count)
    print(f"Recent tasks (showing {len(recent)}):")
    for task in recent:
        print(f"  {task.task_id}: {task.name} [{task.status.value}]")
    return 0


def main():
    parser = argparse.ArgumentParser(description="AgentOS Orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    create_parser = subparsers.add_parser("create", help="Create a new task")
    create_parser.add_argument("name", help="Task name")
    create_parser.add_argument("description", help="Task description")
    create_parser.add_argument("--data", help="Initial data as JSON")
    create_parser.add_argument("--execute", action="store_true", help="Enable actual execution (not dry-run)")
    create_parser.set_defaults(func=cmd_create)

    plan_parser = subparsers.add_parser("plan", help="Generate a plan for task")
    plan_parser.add_argument("task_id", help="Task ID")
    plan_parser.add_argument("--steps", help="Steps as JSON string")
    plan_parser.add_argument("--steps-file", help="Steps from JSON file")
    plan_parser.set_defaults(func=cmd_plan)

    preview_parser = subparsers.add_parser("preview", help="Preview execution")
    preview_parser.add_argument("task_id", help="Task ID")
    preview_parser.set_defaults(func=cmd_preview)

    exec_parser = subparsers.add_parser("execute", help="Execute steps")
    exec_parser.add_argument("task_id", help="Task ID")
    exec_parser.add_argument("--step-id", help="Step ID to execute")
    exec_parser.add_argument("--all", action="store_true", help="Execute all steps")
    exec_parser.set_defaults(func=cmd_execute)

    status_parser = subparsers.add_parser("status", help="Show task status")
    status_parser.add_argument("--task-id", help="Task ID ( omit for list)")
    status_parser.set_defaults(func=cmd_status)

    approve_parser = subparsers.add_parser("approve", help="Approve/reject a step")
    approve_parser.add_argument("task_id", help="Task ID")
    approve_parser.add_argument("step_id", help="Step ID")
    approve_parser.add_argument("--reject", action="store_true", help="Reject instead of approve")
    approve_parser.set_defaults(func=cmd_approve)

    addstep_parser = subparsers.add_parser("add-step", help="Add a step to task")
    addstep_parser.add_argument("task_id", help="Task ID")
    addstep_parser.add_argument("name", help="Step name")
    addstep_parser.add_argument("description", help="Step description")
    addstep_parser.set_defaults(func=cmd_add_step)

    summary_parser = subparsers.add_parser("summary", help="Get task summary")
    summary_parser.add_argument("task_id", help="Task ID")
    summary_parser.set_defaults(func=cmd_summary)

    test_parser = subparsers.add_parser("test", help="Run safety verification tests")
    test_parser.set_defaults(func=cmd_test)

    history_parser = subparsers.add_parser("history", help="Show task history")
    history_parser.add_argument("task_id", help="Task ID")
    history_parser.set_defaults(func=cmd_history)

    logs_parser = subparsers.add_parser("logs", help="Show task execution logs")
    logs_parser.add_argument("task_id", help="Task ID")
    logs_parser.set_defaults(func=cmd_logs)

    archive_parser = subparsers.add_parser("archive", help="Archive a task")
    archive_parser.add_argument("task_id", help="Task ID")
    archive_parser.set_defaults(func=cmd_archive_cmd)

    recent_parser = subparsers.add_parser("recent", help="List recent tasks")
    recent_parser.add_argument("--count", type=int, default=10, help="Number of tasks to show")
    recent_parser.set_defaults(func=cmd_recent)

    timeline_parser = subparsers.add_parser("timeline", help="Show task execution timeline")
    timeline_parser.add_argument("task_id", help="Task ID")
    timeline_parser.add_argument("--json", action="store_true", help="Export as JSON")
    timeline_parser.add_argument("--export", action="store_true", help="Export to file")
    timeline_parser.set_defaults(func=cmd_timeline)

    recovery_parser = subparsers.add_parser("recovery", help="Task recovery and persistence")
    recovery_sub = recovery_parser.add_subparsers(dest="recovery_cmd", help="Recovery commands")

    recovery_scan = recovery_sub.add_parser("scan", help="Scan all tasks and categorize by status")
    recovery_scan.set_defaults(func=cmd_recovery_scan)

    recovery_verify = recovery_sub.add_parser("verify", help="Verify task persistence")
    recovery_verify.add_argument("task_id", help="Task ID to verify")
    recovery_verify.set_defaults(func=cmd_recovery_verify)

    recovery_replay = recovery_sub.add_parser("replay", help="Replay task logs")
    recovery_replay.add_argument("task_id", help="Task ID")
    recovery_replay.set_defaults(func=cmd_recovery_replay)

    recovery_org = recovery_sub.add_parser("organize", help="Organize tasks into directories")
    recovery_org.set_defaults(func=cmd_recovery_organize)

    recovery_stats = recovery_sub.add_parser("stats", help="Show directory statistics")
    recovery_stats.set_defaults(func=cmd_recovery_stats)

    maintenance_parser = subparsers.add_parser("maintenance", help="Maintenance and cleanup")
    maintenance_sub = maintenance_parser.add_subparsers(dest="maintenance_cmd", help="Maintenance commands")

    cleanup_tasks = maintenance_sub.add_parser("cleanup-tasks", help="Cleanup old completed tasks")
    cleanup_tasks.add_argument("--days", type=int, default=7, help="Archive tasks older than N days")
    cleanup_tasks.add_argument("--execute", action="store_true", help="Actually execute (default is dry-run)")
    cleanup_tasks.set_defaults(func=cmd_cleanup_tasks)

    cleanup_approvals = maintenance_sub.add_parser("cleanup-approvals", help="Clean old approval records")
    cleanup_approvals.add_argument("--days", type=int, default=30, help="Remove approvals older than N days")
    cleanup_approvals.add_argument("--execute", action="store_true", help="Actually execute (default is dry-run)")
    cleanup_approvals.set_defaults(func=cmd_cleanup_approvals)

    detect_stale = maintenance_sub.add_parser("stale", help="Detect stale tasks")
    detect_stale.add_argument("--days", type=int, default=30, help="Tasks not updated in N days")
    detect_stale.set_defaults(func=cmd_detect_stale)

    detect_orphaned = maintenance_sub.add_parser("orphaned", help="Detect orphaned timelines/approvals")
    detect_orphaned.add_argument("--type", choices=["timelines", "approvals", "all"], default="all", help="Type to check")
    detect_orphaned.set_defaults(func=cmd_detect_orphaned)

    verify_integrity = maintenance_sub.add_parser("integrity", help="Verify storage integrity")
    verify_integrity.set_defaults(func=cmd_verify_integrity)

    retention_policy = maintenance_sub.add_parser("retention", help="Show retention policies")
    retention_policy.set_defaults(func=cmd_retention_policy)

    exec_parser = subparsers.add_parser("exec", help="Safe execution wrappers")
    exec_sub = exec_parser.add_subparsers(dest="exec_cmd", help="Execution commands")

    exec_shell = exec_sub.add_parser("shell", help="Execute safe shell command")
    exec_shell.add_argument("command", help="Shell command to execute")
    exec_shell.add_argument("--execute", action="store_true", help="Actually execute (default is dry-run)")
    exec_shell.set_defaults(func=cmd_exec_shell)

    exec_git = exec_sub.add_parser("git", help="Execute safe git command")
    exec_git.add_argument("command", help="Git command to execute")
    exec_git.add_argument("--execute", action="store_true", help="Actually execute")
    exec_git.set_defaults(func=cmd_exec_git)

    exec_list_allowed = exec_sub.add_parser("allowed", help="List allowed commands")
    exec_list_allowed.add_argument("--type", choices=["shell", "git", "python"], default="shell", help="Type to list")
    exec_list_allowed.set_defaults(func=cmd_exec_allowed)

    roles_parser = subparsers.add_parser("roles", help="List/validate AgentOS agent roles")
    roles_parser.add_argument("--roles-dir", default=None, help="Override roles directory")
    roles_parser.add_argument("--list", action="store_true", help="List role ids")
    roles_parser.add_argument("--validate", action="store_true", help="Validate and print loaded roles")
    roles_parser.add_argument("--recommend", default=None, help="Recommend a role for the given task text")
    roles_parser.set_defaults(func=cmd_roles)

    approvals_parser = subparsers.add_parser("approvals", help="Approval queue (CLI-first)")
    approvals_sub = approvals_parser.add_subparsers(dest="approvals_cmd", help="Approval commands")

    approvals_list = approvals_sub.add_parser("list", help="List pending approvals")
    approvals_list.set_defaults(func=cmd_approvals)

    approvals_show = approvals_sub.add_parser("show", help="Show approvals for a task")
    approvals_show.add_argument("task_id", help="Task ID")
    approvals_show.set_defaults(func=cmd_approvals)

    approvals_approve = approvals_sub.add_parser("approve", help="Approve the next pending step for a task")
    approvals_approve.add_argument("task_id", help="Task ID")
    approvals_approve.add_argument("--by", default=None, help="Who approved (defaults to $USER)")
    approvals_approve.add_argument("--reason", default=None, help="Approval reason")
    approvals_approve.set_defaults(func=cmd_approvals)

    approvals_reject = approvals_sub.add_parser("reject", help="Reject the next pending step for a task")
    approvals_reject.add_argument("task_id", help="Task ID")
    approvals_reject.add_argument("--by", default=None, help="Who rejected (defaults to $USER)")
    approvals_reject.add_argument("--reason", default=None, help="Rejection reason")
    approvals_reject.set_defaults(func=cmd_approvals)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
