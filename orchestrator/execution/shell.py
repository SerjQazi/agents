"""Safe shell execution wrapper with enhanced security."""

import re
import shlex
import subprocess
from pathlib import Path

from orchestrator.execution.base import ExecutionWrapper, ExecutionResult, ExecutionStatus, RiskLevel


class SafeShell(ExecutionWrapper):
    """Safe shell execution with strict allowlist and security controls."""

    ALLOWED_COMMANDS = {
        "ls": ["ls", "ls -la", "ls -l", "ls -la --color=never"],
        "cat": ["cat", "head", "tail", "less", "more", "head -n", "tail -n"],
        "grep": ["grep", "rg", "ag", "fgrep", "egrep", "grep -i", "grep -n"],
        "find": ["find", "find -name", "find -type", "find -mtime"],
        "stat": ["stat", "file", "stat -c", "file -b"],
        "git": ["git status", "git diff", "git log", "git show", "git branch", "git rev-parse"],
        "python": ["python", "python3", "python3 -c", "python3 -m"],
        "pip": ["pip list", "pip show", "pip freeze", "pip list --format=freeze"],
        "npm": ["npm list", "npm view", "npm ls"],
        "which": ["which", "which -a"],
        "echo": ["echo", "echo -n", "printf"],
        "date": ["date", "date +%Y-%m-%d", "date +%s"],
        "whoami": ["whoami"],
        "pwd": ["pwd"],
        "mkdir": ["mkdir", "mkdir -p"],
        "touch": ["touch"],
        "chmod": ["chmod", "chmod -r", "chmod -w", "chmod -x"],
        # Phase 1: tar extraction is blocked to prevent path traversal writes.
        "tar": ["tar -tvf", "tar -cvf"],
        "sha256sum": ["sha256sum"],
        "md5sum": ["md5sum"],
        "wc": ["wc", "wc -l", "wc -c", "wc -w"],
        "sort": ["sort", "sort -u", "sort -n"],
        "uniq": ["uniq", "uniq -c"],
        "awk": ["awk", "awk -F"],
        "sed": ["sed", "sed -n", "sed -i"],
        "cut": ["cut", "cut -d", "cut -f"],
        "dirname": ["dirname"],
        "basename": ["basename"],
        "realpath": ["realpath"],
    }

    # Hard reject shell metacharacters even though we execute with shell=False.
    # This prevents accidental reliance on shell parsing and blocks common injection payloads.
    BLOCKED_METACHARS = [
        ";",
        "&&",
        "||",
        "|",
        "$",
        "`",
        "<",
        ">",
        "\\",
        "\n",
        "\r",
    ]

    BLOCKED_PATTERNS = [
        (r"rm\s+-rf\s+", "Recursive delete"),
        (r"rm\s+-r\s+", "Recursive delete"),
        (r"rm\s+-f\s+", "Force delete"),
        (r"curl\s+.*\|", "Pipe to shell (curl)"),
        (r"bash\s+.*\|", "Pipe to shell (bash)"),
        (r"sh\s+.*\|", "Pipe to shell (sh)"),
        (r"\|", "Shell pipe"),
        (r";", "Command chain"),
        (r"&&", "And chain"),
        (r"\|\|", "Or chain"),
        (r"sudo", "sudo execution"),
        (r"su\s+", "Switch user"),
        (r"chown", "Change ownership"),
        (r"chgrp", "Change group"),
        (r"wget\s+.*\|", "Pipe to shell (wget)"),
        (r"nc\s+-", "Netcat"),
        (r"/dev/tcp", "TCP device"),
        (r"base64\s+-d", "Base64 decode"),
        (r"eval\s+", "Eval execution"),
        (r"exec\s+", "Exec execution"),
        (r"&\s*$", "Background execution"),
        (r"nohup", "Background execution"),
        (r"setsid", "Background execution"),
        (r"expect", "Interactive shell"),
        (r"ssh\s+", "SSH remote"),
        (r"scp\s+", "SCP remote"),
        (r"ftp\s+", "FTP"),
        (r"telnet\s+", "Telnet"),
        (r"python\s+-m\s+http", "HTTP server"),
        (r"php\s+-S", "PHP server"),
        (r"ruby\s+-run", "Ruby server"),
    ]

    def __init__(self, dry_run: bool = True, timeout: int = 30, max_output: int = 10000):
        super().__init__(dry_run)
        self.timeout = timeout
        self.max_output = max_output

    def _normalize_command(self, command: str) -> str:
        """Normalize command for consistent processing."""
        command = command.strip()
        command = re.sub(r'\s+', ' ', command)
        return command

    def _contains_metachars(self, command: str) -> tuple[bool, str | None]:
        for token in self.BLOCKED_METACHARS:
            if token in command:
                return True, f"Shell metacharacter '{token}' is not allowed"
        return False, None

    def _is_path_like(self, arg: str) -> bool:
        if arg in (".", ".."):
            return True
        if arg.startswith(("./", "../", "/")):
            return True
        return "/" in arg

    def _validate_path_arg(self, arg: str, cwd: str) -> tuple[bool, str | None]:
        """Validate a path argument resolves within allowed base and is not a symlink escape."""
        try:
            p = Path(arg)
            if p.is_absolute():
                resolved = p.resolve()
                if not str(resolved).startswith(self.ALLOWED_BASE_PATH):
                    return False, "Absolute path outside allowed base"
            else:
                resolved = (Path(cwd) / p).resolve()
                if not str(resolved).startswith(self.ALLOWED_BASE_PATH):
                    return False, "Path traversal outside allowed base"

            # If the path exists, reject symlinks pointing outside the base.
            # Note: resolve() already follows symlinks; we still reject if the original
            # path is a symlink at the leaf.
            leaf = (Path(cwd) / p) if not p.is_absolute() else p
            if leaf.exists() and leaf.is_symlink():
                target = leaf.resolve()
                if not str(target).startswith(self.ALLOWED_BASE_PATH):
                    return False, "Symlink points outside allowed base"

            return True, None
        except Exception as e:
            return False, f"Path validation failed: {e}"

    def _is_command_allowed(self, command: str) -> tuple[bool, str | None]:
        """Check if command is in strict allowlist."""
        normalized = self._normalize_command(command)
        try:
            argv = shlex.split(normalized)
        except ValueError as e:
            return False, f"Command parse error: {e}"

        if not argv:
            return False, "Empty command"

        base_cmd = argv[0]

        if base_cmd not in self.ALLOWED_COMMANDS:
            return False, f"Command '{base_cmd}' not in allowlist"

        allowed_variants = self.ALLOWED_COMMANDS[base_cmd]
        for variant in allowed_variants:
            variant_argv = shlex.split(variant)
            if argv[: len(variant_argv)] != variant_argv:
                continue

            # Disallow additional flags beyond the known safe variant.
            extra = argv[len(variant_argv) :]
            for a in extra:
                if a.startswith("-"):
                    return False, f"Flag '{a}' not allowed for '{variant}'"
            return True, None

        return False, "Command does not match any allowed safe variant"

    def _contains_blocked_pattern(self, command: str) -> tuple[bool, str | None]:
        """Check for blocked patterns."""
        for pattern, description in self.BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True, description
        return False, None

    def _check_chaining(self, command: str) -> tuple[bool, str | None]:
        """Check for command chaining."""
        chaining_chars = [';', '&&', '||', '|']
        for char in chaining_chars:
            if char in command:
                return True, f"Command chaining with '{char}' is not allowed"
        return False, None

    def _check_background(self, command: str) -> tuple[bool, str | None]:
        """Check for background execution."""
        if command.strip().endswith('&'):
            return True, "Background execution is not allowed"
        return False, None

    def _truncate_output(self, output: str) -> str:
        """Truncate output to max size."""
        if len(output) > self.max_output:
            return output[:self.max_output] + f"\n... [truncated, {len(output) - self.max_output} more bytes]"
        return output

    def execute(
        self,
        command: str,
        cwd: str | None = None,
    ) -> ExecutionResult:
        """Execute a shell command safely with strict controls."""
        normalized = self._normalize_command(command)
        working_dir = cwd or "/home/agentzero/agents"

        meta, meta_desc = self._contains_metachars(normalized)
        if meta:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.CRITICAL,
                command=normalized,
                blocked_reason=meta_desc,
                audit_log=[f"BLOCKED: {normalized} - {meta_desc}"],
            )
            self._log_execution(result)
            return result

        try:
            argv = shlex.split(normalized)
        except ValueError as e:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=normalized,
                blocked_reason=f"Command parse error: {e}",
            )
            self._log_execution(result)
            return result

        path_allowed, path_error = self._check_path(working_dir)
        if not path_allowed:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.CRITICAL,
                command=normalized,
                blocked_reason=path_error,
                path_restricted=True,
            )
            self._log_execution(result)
            return result

        # Validate obvious path-like arguments resolve within the repo.
        for a in argv[1:]:
            if self._is_path_like(a):
                ok, err = self._validate_path_arg(a, working_dir)
                if not ok:
                    result = ExecutionResult(
                        status=ExecutionStatus.BLOCKED,
                        risk_level=RiskLevel.CRITICAL,
                        command=normalized,
                        blocked_reason=f"Path argument blocked: {err}",
                        path_restricted=True,
                    )
                    self._log_execution(result)
                    return result

        blocked_pattern, pattern_desc = self._contains_blocked_pattern(normalized)
        if blocked_pattern:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.CRITICAL,
                command=normalized,
                blocked_reason=f"Blocked pattern: {pattern_desc}",
                audit_log=[
                    f"BLOCKED: {normalized}",
                    f"Reason: {pattern_desc}",
                ],
            )
            self._log_execution(result)
            return result

        chaining, chaining_desc = self._check_chaining(normalized)
        if chaining:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=normalized,
                blocked_reason=chaining_desc,
                audit_log=[f"BLOCKED: {normalized} - {chaining_desc}"],
            )
            self._log_execution(result)
            return result

        background, background_desc = self._check_background(normalized)
        if background:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=normalized,
                blocked_reason=background_desc,
                audit_log=[f"BLOCKED: {normalized} - {background_desc}"],
            )
            self._log_execution(result)
            return result

        allowed, allowed_error = self._is_command_allowed(normalized)
        if not allowed:
            result = ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=normalized,
                blocked_reason=allowed_error,
                audit_log=[f"BLOCKED: {normalized} - {allowed_error}"],
            )
            self._log_execution(result)
            return result

        risk_level = RiskLevel.LOW if self.dry_run else RiskLevel.MEDIUM

        if self.dry_run:
            result = ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                risk_level=risk_level,
                command=normalized,
                dry_run=True,
                output=f"Would execute: {normalized}",
                audit_log=[
                    f"DRY-RUN: {normalized}",
                    f"Working directory: {working_dir}",
                ],
            )
            self._log_execution(result)
            return result

        try:
            result = subprocess.run(
                argv,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            status = ExecutionStatus.EXECUTED if result.returncode == 0 else ExecutionStatus.FAILED

            output = self._truncate_output(result.stdout)
            error = self._truncate_output(result.stderr) if result.stderr else None

            exec_result = ExecutionResult(
                status=status,
                risk_level=risk_level,
                command=normalized,
                output=output,
                error=error,
                audit_log=[
                    f"Executed: {normalized}",
                    f"Exit code: {result.returncode}",
                    f"Timeout: {self.timeout}s",
                ],
            )
            self._log_execution(exec_result)
            return exec_result

        except subprocess.TimeoutExpired:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=risk_level,
                command=normalized,
                error=f"Command timed out after {self.timeout} seconds",
                audit_log=[f"Timeout: {normalized}"],
            )
            self._log_execution(result)
            return result

        except Exception as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=risk_level,
                command=normalized,
                error=str(e),
                audit_log=[f"Error: {normalized} - {str(e)}"],
            )
            self._log_execution(result)
            return result

    def list_allowed_commands(self) -> dict[str, list[str]]:
        """Return list of allowed commands."""
        return self.ALLOWED_COMMANDS.copy()
