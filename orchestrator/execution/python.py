"""Safe Python execution wrapper with strict security controls."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from orchestrator.execution.base import ExecutionWrapper, ExecutionResult, ExecutionStatus, RiskLevel


class SafePython(ExecutionWrapper):
    """Safe Python execution with strict restrictions."""

    BLOCKED_IMPORTS = {
        "os": ["os", "os.path", "os.system", "os.popen", "os.spawn", "os.exec"],
        "sys": ["sys", "sys.path", "sys.argv", "sys.modules"],
        "subprocess": ["subprocess", "subprocess.Popen", "subprocess.run"],
        "socket": ["socket", "socket.socket"],
        "urllib": ["urllib", "urllib.request", "urllib3", "requests"],
        "http": ["http", "http.client", "urllib2"],
        "ftplib": ["ftplib", "ftplib.FTP"],
        "smtplib": ["smtplib"],
        "telnetlib": ["telnetlib"],
        "poplib": ["poplib"],
        "imaplib": ["imaplib"],
        "pty": ["pty", "pty.spawn"],
        "tty": ["tty", "tty.setraw", "tty.setcbreak"],
        "termios": ["termios"],
        "resource": ["resource", "resource.setrlimit"],
        "signal": ["signal", "signal.alarm"],
        "importlib": ["importlib", "importlib.import_module"],
        "builtins": ["__import__"],
    }

    BLOCKED_PATTERNS = [
        (r"^import\s+os\s*$", "import os"),
        (r"^import\s+sys\s*$", "import sys"),
        (r"^import\s+subprocess", "import subprocess"),
        (r"^import\s+socket", "import socket"),
        (r"^import\s+urllib", "import urllib"),
        (r"^import\s+requests", "import requests"),
        (r"^import\s+http", "import http"),
        (r"^from\s+os\s+import", "from os import"),
        (r"^from\s+sys\s+import", "from sys import"),
        (r"^from\s+subprocess\s+import", "from subprocess import"),
        (r"^from\s+socket\s+import", "from socket import"),
        (r"__import__", "__import__"),
        (r"eval\s*\(", "eval()"),
        (r"exec\s*\(", "exec()"),
        (r"compile\s*\(", "compile()"),
        (r"open\s*\([^)]*\)\s*\.", "file operations"),
        (r"file\s*\(", "file()"),
        (r"raw_input\s*\(", "raw_input()"),
        (r"input\s*\(\s*\)", "input() with no args"),
        (r"charset\.encode", "charset encoding"),
    ]

    ALLOWED_BUILTINS = {
        "print", "len", "str", "int", "float", "bool", "list", "dict", "tuple", "set",
        "range", "enumerate", "zip", "map", "filter", "sorted", "reversed", "sum",
        "min", "max", "abs", "round", "divmod", "pow", "isinstance", "issubclass",
        "type", "id", "hash", "repr", "ascii", "format", "open", "abs", "any", "all",
    }

    def __init__(self, dry_run: bool = True, timeout: int = 10, max_output: int = 5000):
        super().__init__(dry_run)
        self.timeout = timeout
        self.max_output = max_output
        self.allowed_modules = {
            "json": "json",
            "pathlib": "pathlib",
            "re": "re",
            "datetime": "datetime",
            "collections": "collections",
            "itertools": "itertools",
            "functools": "functools",
            "typing": "typing",
            "hashlib": "hashlib",
            "base64": "base64",
            "math": "math",
            "statistics": "statistics",
            "random": "random (limited)",
            "copy": "copy",
            "io": "io (limited)",
        }

    def _check_imports(self, code: str) -> tuple[bool, str | None]:
        """Check for blocked imports."""
        import re
        lines = code.split("\n")

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            for category, blocked_list in self.BLOCKED_IMPORTS.items():
                for blocked in blocked_list:
                    if line == f"import {blocked}" or line.startswith(f"import {blocked}."):
                        return False, f"Blocked import: {blocked} (line {line_num})"
                    if line.startswith(f"from {blocked}"):
                        return False, f"Blocked import: from {blocked} (line {line_num})"

            for pattern, description in self.BLOCKED_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE | re.MULTILINE):
                    return False, f"Blocked pattern: {description} (line {line_num})"

        return True, None

    def _check_dangerous_builtins(self, code: str) -> tuple[bool, str | None]:
        """Check for dangerous built-in usage."""
        dangerous = ["__import__", "eval", "exec", "compile", "open", "input"]
        lines = code.split("\n")

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            for dangerous_builtin in dangerous:
                if dangerous_builtin in line:
                    if dangerous_builtin == "input" and "input(" in line:
                        return False, f"input() at line {line_num} - use safe input only"
                    return False, f"Dangerous builtin: {dangerous_builtin} (line {line_num})"

        return True, None

    def _truncate_output(self, output: str) -> str:
        """Truncate output to max size."""
        if len(output) > self.max_output:
            return output[:self.max_output] + f"\n... [truncated {len(output) - self.max_output} bytes]"
        return output

    def execute(
        self,
        code: str,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Execute Python code.

        Phase 1: disabled. String/regex blocking is not a safe sandbox.
        Use validation-only operations (syntax checks) instead.
        """
        command = "python: execution disabled"

        result = ExecutionResult(
            status=ExecutionStatus.BLOCKED,
            risk_level=RiskLevel.CRITICAL,
            command=command,
            blocked_reason="SafePython.execute is disabled (Phase 1). Use validate_syntax/py_compile instead.",
            audit_log=["BLOCKED: SafePython.execute disabled"],
        )
        self._log_execution(result)
        return result

    def validate_syntax(self, code: str) -> ExecutionResult:
        """Validate Python syntax without executing."""
        command = "python: syntax validation"

        try:
            compile(code, "<string>", "exec")
            result = ExecutionResult(
                status=ExecutionStatus.EXECUTED,
                risk_level=RiskLevel.SAFE,
                command=command,
                output="Syntax is valid",
                audit_log=["Validated Python syntax"],
            )
        except SyntaxError as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                error=f"Syntax error: {e}",
                audit_log=[f"Syntax validation failed: {e}"],
            )

        self._log_execution(result)
        return result

    def list_allowed_modules(self) -> dict[str, str]:
        """Return list of allowed modules."""
        return self.allowed_modules.copy()
