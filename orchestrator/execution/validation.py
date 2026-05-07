"""Safe code validation wrapper with comprehensive checks."""

import json
import subprocess
import yaml
from pathlib import Path
from typing import Any

from orchestrator.execution.base import ExecutionWrapper, ExecutionResult, ExecutionStatus, RiskLevel


class SafeValidation(ExecutionWrapper):
    """Safe code validation with multiple format support."""

    def __init__(self, dry_run: bool = True):
        super().__init__(dry_run)

    def validate_python_syntax(self, file_path: str) -> ExecutionResult:
        """Validate Python file syntax."""
        command = f"python_syntax: {file_path}"

        path_allowed, path_error = self._check_path(file_path)
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="File does not exist",
            )

        if file_path_obj.suffix != ".py":
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="Not a Python file",
            )

        try:
            result = subprocess.run(
                ["python3", "-m", "py_compile", str(file_path_obj)],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                exec_result = ExecutionResult(
                    status=ExecutionStatus.EXECUTED,
                    risk_level=RiskLevel.SAFE,
                    command=command,
                    output=f"Syntax valid: {file_path}",
                    audit_log=[f"Validated Python syntax: {file_path}"],
                )
            else:
                exec_result = ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    risk_level=RiskLevel.SAFE,
                    command=command,
                    error=result.stderr[:500],
                    audit_log=[f"Syntax error in: {file_path}"],
                )

            self._log_execution(exec_result)
            return exec_result

        except subprocess.TimeoutExpired:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                error="Validation timed out",
            )
            self._log_execution(result)
            return result

        except Exception as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                error=str(e),
            )
            self._log_execution(result)
            return result

    def validate_json_syntax(self, file_path: str) -> ExecutionResult:
        """Validate JSON file syntax."""
        command = f"json_syntax: {file_path}"

        path_allowed, path_error = self._check_path(file_path)
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="File does not exist",
            )

        try:
            with open(file_path_obj) as f:
                data = json.load(f)

            result = ExecutionResult(
                status=ExecutionStatus.EXECUTED,
                risk_level=RiskLevel.SAFE,
                command=command,
                output=f"JSON valid: {file_path} ({len(data)} keys)",
                audit_log=[f"Validated JSON: {file_path}"],
            )
            self._log_execution(result)
            return result

        except json.JSONDecodeError as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                error=f"JSON error: {e}",
                audit_log=[f"JSON error in: {file_path}"],
            )
            self._log_execution(result)
            return result

        except Exception as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                error=str(e),
            )
            self._log_execution(result)
            return result

    def validate_yaml_syntax(self, file_path: str) -> ExecutionResult:
        """Validate YAML file syntax."""
        command = f"yaml_syntax: {file_path}"

        path_allowed, path_error = self._check_path(file_path)
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="File does not exist",
            )

        try:
            with open(file_path_obj) as f:
                data = yaml.safe_load(f)

            result = ExecutionResult(
                status=ExecutionStatus.EXECUTED,
                risk_level=RiskLevel.SAFE,
                command=command,
                output=f"YAML valid: {file_path}",
                audit_log=[f"Validated YAML: {file_path}"],
            )
            self._log_execution(result)
            return result

        except yaml.YAMLError as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                error=f"YAML error: {e}",
                audit_log=[f"YAML error in: {file_path}"],
            )
            self._log_execution(result)
            return result

        except Exception as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                error=str(e),
            )
            self._log_execution(result)
            return result

    def validate_shell_syntax(self, file_path: str) -> ExecutionResult:
        """Validate shell script syntax."""
        command = f"shell_syntax: {file_path}"

        path_allowed, path_error = self._check_path(file_path)
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="File does not exist",
            )

        try:
            result = subprocess.run(
                ["bash", "-n", str(file_path_obj)],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                exec_result = ExecutionResult(
                    status=ExecutionStatus.EXECUTED,
                    risk_level=RiskLevel.SAFE,
                    command=command,
                    output=f"Shell syntax valid: {file_path}",
                    audit_log=[f"Validated shell syntax: {file_path}"],
                )
            else:
                exec_result = ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    risk_level=RiskLevel.SAFE,
                    command=command,
                    error=result.stderr[:500],
                    audit_log=[f"Shell syntax error in: {file_path}"],
                )

            self._log_execution(exec_result)
            return exec_result

        except Exception as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                error=str(e),
            )
            self._log_execution(result)
            return result

    def scan_for_secrets(self, file_path: str) -> ExecutionResult:
        """Scan file for potential secrets."""
        command = f"secret_scan: {file_path}"

        path_allowed, path_error = self._check_path(file_path)
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="File does not exist",
            )

        import re

        patterns = [
            (r"password\s*[=:]\s*[\"'][^\"']+[\"']", "potential password"),
            (r"api[_-]?key\s*[=:]\s*[\"'][^\"']+[\"']", "potential API key"),
            (r"secret\s*[=:]\s*[\"'][^\"']+[\"']", "potential secret"),
            (r"token\s*[=:]\s*[\"'][^\"']+[\"']", "potential token"),
            (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "private key"),
            (r"aws[_-]?access[_-]?key[_-]?id", "AWS access key"),
            (r"aws[_-]?secret[_-]?access[_-]?key", "AWS secret key"),
            (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API key"),
        ]

        content = file_path_obj.read_text()
        findings = []

        for pattern, description in patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                findings.append({
                    "type": description,
                    "match": match.group()[:50] + "..." if len(match.group()) > 50 else match.group(),
                })

        result = ExecutionResult(
            status=ExecutionStatus.EXECUTED,
            risk_level=RiskLevel.SAFE,
            command=command,
            output=f"Scanned {file_path}: {len(findings)} potential secrets" if findings else f"Scanned {file_path}: No secrets found",
            audit_log=[
                f"Secret scan: {file_path}",
                f"Findings: {len(findings)}",
            ],
        )
        self._log_execution(result)
        return result

    def validate_directory(self, dir_path: str, pattern: str = "*.py") -> ExecutionResult:
        """Validate all matching files in directory."""
        command = f"dir_validate: {dir_path}"

        path_allowed, path_error = self._check_path(dir_path)
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        dir_path_obj = Path(dir_path)

        if not dir_path_obj.exists() or not dir_path_obj.is_dir():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="Directory does not exist",
            )

        files = list(dir_path_obj.rglob(pattern))
        results = []

        for f in files[:50]:
            try:
                if f.suffix == ".py":
                    sub_result = subprocess.run(
                        ["python3", "-m", "py_compile", str(f)],
                        capture_output=True,
                        timeout=10,
                    )
                    results.append({
                        "file": str(f),
                        "valid": sub_result.returncode == 0,
                    })
            except Exception:
                results.append({
                    "file": str(f),
                    "valid": False,
                    "error": "timeout or exception",
                })

        valid_count = sum(1 for r in results if r.get("valid", False))
        failed = [r for r in results if not r.get("valid", False)]

        result = ExecutionResult(
            status=ExecutionStatus.EXECUTED if not failed else ExecutionStatus.FAILED,
            risk_level=RiskLevel.SAFE,
            command=command,
            output=f"Validated {len(files)} files: {valid_count} valid, {len(failed)} failed",
            error=f"Failed: {', '.join([r['file'] for r in failed[:5]])}" if failed else None,
            audit_log=[
                f"Directory validation: {dir_path}",
                f"Files: {len(files)}, Valid: {valid_count}, Failed: {len(failed)}",
            ],
        )
        self._log_execution(result)
        return result

    def batch_validate(self, file_paths: list[str]) -> dict[str, Any]:
        """Validate multiple files at once."""
        results = {}

        for file_path in file_paths:
            file_path_obj = Path(file_path)

            if not file_path_obj.exists():
                results[file_path] = {"status": "not_found"}
                continue

            suffix = file_path_obj.suffix

            if suffix == ".py":
                result = self.validate_python_syntax(file_path)
            elif suffix in [".json"]:
                result = self.validate_json_syntax(file_path)
            elif suffix in [".yaml", ".yml"]:
                result = self.validate_yaml_syntax(file_path)
            elif suffix in [".sh"]:
                result = self.validate_shell_syntax(file_path)
            else:
                results[file_path] = {"status": "unsupported"}
                continue

            results[file_path] = {
                "status": result.status.value,
                "risk": result.risk_level.value,
            }

        return results