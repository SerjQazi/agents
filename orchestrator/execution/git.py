"""Safe git execution wrapper with approval workflow and rollback support."""

import json
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.execution.base import ExecutionWrapper, ExecutionResult, ExecutionStatus, RiskLevel


class SafeGit(ExecutionWrapper):
    """Safe git operations with approval workflow and rollback support."""

    SAFE_GIT_COMMANDS = {
        # Commands are subcommands only (no leading "git ").
        "status": ["status", "status --porcelain", "status -s"],
        "diff": ["diff", "diff --staged", "diff HEAD", "diff --name-only"],
        "log": ["log", "log --oneline", "log -10", "log --graph --oneline", "log --format=%H"],
        "show": ["show", "show --stat", "show --name-only"],
        "branch": ["branch", "branch -a", "branch -v", "branch -vv"],
        "remote": ["remote -v", "remote show", "remote -vv"],
        "tag": ["tag", "tag -l", "tag -n"],
        "rev_parse": ["rev-parse", "rev-parse HEAD", "rev-parse --short HEAD"],
        "ls_files": ["ls-files", "ls-tree", "ls-files -s"],
        "clean": ["clean -n", "clean -fd -n", "clean -n -d"],
        "stash": ["stash list", "stash show", "stash show -p"],
        "difftool": ["difftool", "mergetool"],
    }

    BLOCKED_GIT_COMMANDS = [
        "push", "push --force", "push --force-with-lease", "push -f",
        "push origin", "push --all", "push --tags", "push --follow-tags",
        "commit", "commit -a", "commit --amend", "commit --no-verify",
        "commit --allow-empty", "commit --force",
        "rebase", "rebase --continue", "rebase --abort", "rebase --skip",
        "merge", "merge --squash", "merge --no-ff",
        "checkout -f", "checkout -B", "checkout --force",
        "reset --hard", "reset --merge", "reset --keep",
        "reflog expire", "reflog delete",
    ]

    def __init__(self, dry_run: bool = True, timeout: int = 30):
        super().__init__(dry_run)
        self.repo_path = Path("/home/agentzero/agents")
        self.timeout = timeout
        self.snapshot_dir = self.repo_path / "backups" / "git_snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _contains_metachars(command: str) -> tuple[bool, str | None]:
        blocked = [";", "&&", "||", "|", "$", "`", "<", ">", "\\", "\n", "\r", "&"]
        for b in blocked:
            if b in command:
                return True, f"Shell metacharacter '{b}' is not allowed"
        return False, None

    @staticmethod
    def _parse_command(command: str) -> tuple[list[str] | None, str | None]:
        try:
            argv = shlex.split(command.strip())
        except ValueError as e:
            return None, f"Command parse error: {e}"
        if not argv:
            return None, "Empty command"
        if argv[0] == "git":
            return None, "Commands must be git subcommands (do not start with 'git ')"
        return argv, None

    def _is_git_safe(self, command: str) -> tuple[bool, str | None]:
        """Check if git command is safe (read-only)."""
        cmd_lower = command.lower().strip()

        for safe_category, safe_commands in self.SAFE_GIT_COMMANDS.items():
            for safe_cmd in safe_commands:
                if cmd_lower.startswith(safe_cmd):
                    return True, None

        for blocked in self.BLOCKED_GIT_COMMANDS:
            if blocked in cmd_lower:
                return False, f"Git command '{blocked}' is blocked or requires approval"

        return False, "Git command not recognized as safe"

    def _requires_approval(self, command: str) -> bool:
        """Check if command requires explicit approval."""
        cmd_lower = command.lower().strip()

        requires_approval = [
            "push", "commit", "merge", "rebase",
            "checkout -", "checkout --force", "reset --hard",
        ]

        for req in requires_approval:
            if req in cmd_lower:
                return True
        return False

    def _create_rollback_snapshot(self, command: str) -> dict[str, Any]:
        """Create rollback snapshot before potentially dangerous operations."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            current_commit = result.stdout.strip() if result.returncode == 0 else "uncommitted"

            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            staged_changes = result.stdout.strip() if result.returncode == 0 else ""

            snapshot_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_file = self.snapshot_dir / f"snapshot_{snapshot_id}.json"

            snapshot = {
                "snapshot_id": snapshot_id,
                "timestamp": datetime.now().isoformat(),
                "command": command,
                "pre_state": {
                    "commit": current_commit,
                    "staged_changes": staged_changes[:5000] if staged_changes else "",
                },
                "can_rollback": True,
            }

            with open(snapshot_file, "w") as f:
                json.dump(snapshot, f, indent=2)

            return snapshot

        except Exception as e:
            return {"error": str(e), "can_rollback": False}

    def execute(
        self,
        command: str,
        require_approval: bool = False,
        force_approval: bool = False,
    ) -> ExecutionResult:
        """Execute a git command safely with approval workflow."""

        meta, meta_desc = self._contains_metachars(command)
        if meta:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.CRITICAL,
                command=command,
                blocked_reason=meta_desc,
                audit_log=[f"BLOCKED: git {command} - {meta_desc}"],
            )
            self._log_execution(result)
            return result

        argv, parse_err = self._parse_command(command)
        if argv is None:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=command,
                blocked_reason=parse_err,
            )
            self._log_execution(result)
            return result

        path_allowed, path_error = self._check_path(str(self.repo_path))
        if not path_allowed:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )
            self._log_execution(result)
            return result

        # Hard-block push in Phase 1.
        if argv and argv[0].lower() == "push":
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.CRITICAL,
                command=command,
                blocked_reason="git push is hard-blocked",
                approval_required=True,
                audit_log=[f"BLOCKED: git {command} - push is hard-blocked"],
            )
            self._log_execution(result)
            return result

        is_safe, safety_error = self._is_git_safe(command)
        if not is_safe:
            requires_approval = self._requires_approval(command) or require_approval

            # Phase 1: do not allow bypassing approvals via force_approval.
            if requires_approval:
                snapshot = self._create_rollback_snapshot(command)
                risk_level = RiskLevel.CRITICAL
                result = ExecutionResult(
                    status=ExecutionStatus.BLOCKED,
                    risk_level=risk_level,
                    command=command,
                    blocked_reason=f"Requires explicit approval: {safety_error}",
                    approval_required=True,
                    rollback_metadata={
                        "snapshot_id": snapshot.get("snapshot_id"),
                        "can_rollback": snapshot.get("can_rollback", False),
                        "pre_state": snapshot.get("pre_state", {}),
                    },
                    audit_log=[
                        f"BLOCKED: git {command}",
                        f"Reason: {safety_error}",
                        f"Approval required for: push/commit/merge/rebase",
                        f"Snapshot created: {snapshot.get('snapshot_id', 'none')}",
                    ],
                )
                self._log_execution(result)
                return result

        risk_level = RiskLevel.SAFE

        if self.dry_run:
            result = ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                risk_level=risk_level,
                command=command,
                dry_run=True,
                output=f"Would execute: git {command}",
                audit_log=[f"DRY-RUN: git {command}"],
            )
        else:
            result = self._execute_git_command(argv, risk_level)

        self._log_execution(result)
        return result

    def _execute_git_command(self, argv: list[str], risk_level: RiskLevel) -> ExecutionResult:
        """Execute git command and return result."""
        try:
            result = subprocess.run(
                ["git", *argv],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            status = ExecutionStatus.EXECUTED if result.returncode == 0 else ExecutionStatus.FAILED

            output = result.stdout[:10000]
            error = result.stderr[:5000] if result.stderr else None

            return ExecutionResult(
                status=status,
                risk_level=risk_level,
                command=" ".join(argv),
                output=output,
                error=error,
                audit_log=[
                    f"Executed: git {' '.join(argv)}",
                    f"Exit code: {result.returncode}",
                ],
            )

        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=risk_level,
                command=" ".join(argv),
                error=f"Git command timed out after {self.timeout} seconds",
                audit_log=[f"Timeout: git {' '.join(argv)}"],
            )

        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=risk_level,
                command=" ".join(argv),
                error=str(e),
                audit_log=[f"Error: git {' '.join(argv)} - {str(e)}"],
            )

    def get_diff_preview(self, staged: bool = False, context: int = 3) -> ExecutionResult:
        """Get diff preview without executing."""
        cmd = f"diff --staged -U{context}" if staged else f"diff -U{context}"
        return self.execute(cmd)

    def get_status(self) -> ExecutionResult:
        """Get git status safely."""
        return self.execute("status")

    def get_diff(self, staged: bool = False) -> ExecutionResult:
        """Get git diff safely."""
        cmd = "diff --staged" if staged else "diff"
        return self.execute(cmd)

    def get_log(self, limit: int = 10, format: str = "oneline") -> ExecutionResult:
        """Get git log safely."""
        return self.execute(f"log --{format} -n {limit}")

    def restore_snapshot(self, snapshot_id: str) -> ExecutionResult:
        """Restore git state from snapshot."""
        snapshot_file = self.snapshot_dir / f"snapshot_{snapshot_id}.json"

        if not snapshot_file.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=f"restore_snapshot:{snapshot_id}",
                blocked_reason=f"Snapshot {snapshot_id} not found",
            )

        try:
            with open(snapshot_file) as f:
                snapshot = json.load(f)

            pre_commit = snapshot.get("pre_state", {}).get("commit", "HEAD")

            result = subprocess.run(
                ["git", "reset", "--hard", str(pre_commit)],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )

            status = ExecutionStatus.EXECUTED if result.returncode == 0 else ExecutionStatus.FAILED

            return ExecutionResult(
                status=status,
                risk_level=RiskLevel.HIGH,
                command=f"restore_snapshot:{snapshot_id}",
                output=f"Restored to commit: {pre_commit}" if result.returncode == 0 else result.stderr,
                audit_log=[
                    f"Restored snapshot {snapshot_id}",
                    f"To commit: {pre_commit}",
                ],
            )

        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.HIGH,
                command=f"restore_snapshot:{snapshot_id}",
                error=str(e),
            )

    def list_snapshots(self) -> list[dict[str, Any]]:
        """List available rollback snapshots."""
        snapshots = []
        for f in self.snapshot_dir.glob("snapshot_*.json"):
            try:
                with open(f) as sf:
                    snapshots.append(json.load(sf))
            except (json.JSONDecodeError, IOError):
                continue
        return sorted(snapshots, key=lambda x: x.get("timestamp", ""), reverse=True)

    def list_allowed_operations(self) -> dict[str, list[str]]:
        """Return list of allowed git operations."""
        return self.SAFE_GIT_COMMANDS.copy()
