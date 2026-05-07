"""Safe file edit wrapper with backup, diff, and rollback support."""

import difflib
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.execution.base import ExecutionWrapper, ExecutionResult, ExecutionStatus, RiskLevel


class SafeFileEdit(ExecutionWrapper):
    """Safe file editing with backup, diff, and rollback support."""

    def __init__(self, dry_run: bool = True):
        super().__init__(dry_run)
        self.backup_dir = Path("/home/agentzero/agents/backups/file_edits")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.diff_dir = Path("/home/agentzero/agents/backups/diffs")
        self.diff_dir.mkdir(parents=True, exist_ok=True)

    def _normalize_path(self, path: str) -> tuple[Path, str | None]:
        """Normalize and validate path, checking for symlink escapes."""
        try:
            path_obj = Path(path).resolve()

            original_path = Path(path)
            if original_path.is_symlink():
                real_target = original_path.resolve()
                if not str(real_target).startswith("/home/agentzero/agents"):
                    return None, "Symlink points outside allowed directory"

            return path_obj, None

        except Exception as e:
            return None, f"Path resolution failed: {e}"

    def _create_backup(self, file_path: Path) -> dict[str, Any]:
        """Create backup before edit."""
        backup_info = {
            "created": datetime.now().isoformat(),
            "backup_path": None,
            "original_hash": None,
            "original_path": str(file_path.resolve()),
            "metadata_path": None,
        }

        if not file_path.exists():
            return backup_info

        try:
            content = file_path.read_text()
            original_hash = hashlib.md5(content.encode()).hexdigest()

            backup_name = f"{file_path.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
            backup_path = self.backup_dir / backup_name
            shutil.copy2(file_path, backup_path)

            metadata_path = backup_path.with_suffix(".bak.json")
            metadata_path.write_text(
                json.dumps(
                    {
                        "original_path": str(file_path.resolve()),
                        "created": backup_info["created"],
                        "backup_path": str(backup_path),
                        "original_hash": original_hash,
                    },
                    indent=2,
                )
            )

            backup_info["backup_path"] = str(backup_path)
            backup_info["metadata_path"] = str(metadata_path)
            backup_info["original_hash"] = original_hash
            backup_info["original_size"] = len(content)

        except Exception as e:
            backup_info["error"] = str(e)

        return backup_info

    def _generate_unified_diff(
        self,
        original: str,
        new: str,
        original_path: str,
    ) -> str:
        """Generate unified diff."""
        original_lines = original.splitlines(keepends=True) if original else []
        new_lines = new.splitlines(keepends=True) if new else []

        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{original_path}",
            tofile=f"b/{original_path}",
            lineterm="",
        )

        diff_text = "".join(diff)
        if not diff_text:
            return "No changes detected"

        return diff_text

    def _save_diff(
        self,
        file_path: str,
        diff: str,
    ) -> str | None:
        """Save diff to file."""
        try:
            file_name = Path(file_path).name
            diff_name = f"{file_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.diff"
            diff_path = self.diff_dir / diff_name

            diff_path.write_text(diff)
            return str(diff_path)

        except Exception:
            return None

    def edit(
        self,
        file_path: str,
        content: str,
        create_if_missing: bool = False,
    ) -> ExecutionResult:
        """Edit a file safely with backup and diff generation."""
        command = f"file_edit: {file_path}"

        normalized_path, path_error = self._normalize_path(file_path)
        if not normalized_path:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.MEDIUM,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        path_allowed, path_error = self._check_path(str(normalized_path))
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.MEDIUM,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        original_content = ""
        backup_info = {}

        if normalized_path.exists():
            original_content = normalized_path.read_text()
            backup_info = self._create_backup(normalized_path)
            risk_level = RiskLevel.MEDIUM
        else:
            if not create_if_missing:
                return ExecutionResult(
                    status=ExecutionStatus.BLOCKED,
                    risk_level=RiskLevel.LOW,
                    command=command,
                    blocked_reason="File does not exist and create_if_missing=False",
                )
            risk_level = RiskLevel.LOW

        unified_diff = self._generate_unified_diff(
            original_content,
            content,
            str(normalized_path),
        )

        diff_path = None
        if unified_diff and unified_diff != "No changes detected":
            diff_path = self._save_diff(str(normalized_path), unified_diff)

        if self.dry_run:
            result = ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                risk_level=risk_level,
                command=command,
                dry_run=True,
                output=f"Would write {len(content)} chars to {file_path}",
                rollback_metadata={
                    "action": "file_write",
                    "path": str(normalized_path),
                    "original_hash": backup_info.get("original_hash", "new_file"),
                    "backup_created": backup_info.get("backup_path"),
                    "backup_metadata": backup_info.get("metadata_path"),
                    "original_path": backup_info.get("original_path"),
                    "diff_saved": diff_path,
                },
                audit_log=[
                    f"DRY-RUN: Would edit {normalized_path}",
                    f"Backup: {backup_info.get('backup_path', 'none')}",
                    f"Diff: {diff_path or 'none'}",
                ],
            )
            self._log_execution(result)
            return result

        try:
            normalized_path.parent.mkdir(parents=True, exist_ok=True)
            # Re-resolve immediately before write to reduce TOCTOU and refuse symlink targets.
            resolved_now = Path(file_path).resolve()
            path_allowed, path_error = self._check_path(str(resolved_now))
            if not path_allowed:
                result = ExecutionResult(
                    status=ExecutionStatus.BLOCKED,
                    risk_level=risk_level,
                    command=command,
                    blocked_reason=path_error,
                    path_restricted=True,
                )
                self._log_execution(result)
                return result

            if Path(file_path).exists() and Path(file_path).is_symlink():
                result = ExecutionResult(
                    status=ExecutionStatus.BLOCKED,
                    risk_level=RiskLevel.HIGH,
                    command=command,
                    blocked_reason="Refusing to write to symlink path",
                    path_restricted=True,
                )
                self._log_execution(result)
                return result

            resolved_now.write_text(content)

            result = ExecutionResult(
                status=ExecutionStatus.EXECUTED,
                risk_level=risk_level,
                command=command,
                output=f"Wrote {len(content)} chars to {file_path}",
                rollback_metadata={
                    "action": "file_write",
                    "path": str(resolved_now),
                    "original_hash": backup_info.get("original_hash", "new_file"),
                    "backup_path": backup_info.get("backup_path"),
                    "backup_metadata": backup_info.get("metadata_path"),
                    "original_path": backup_info.get("original_path"),
                    "original_size": backup_info.get("original_size", 0),
                    "new_size": len(content),
                    "diff_path": diff_path,
                },
                audit_log=[
                    f"Edited {normalized_path}",
                    f"Backup: {backup_info.get('backup_path', 'new file')}",
                    f"Diff: {diff_path or 'none'}",
                    f"Original hash: {backup_info.get('original_hash', 'new')}",
                ],
            )
            self._log_execution(result)
            return result

        except Exception as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=risk_level,
                command=command,
                error=str(e),
                audit_log=[f"Edit failed: {normalized_path} - {str(e)}"],
            )
            self._log_execution(result)
            return result

    def restore_from_backup(self, backup_path: str) -> ExecutionResult:
        """Restore file from backup."""
        command = f"restore_from_backup: {backup_path}"

        backup_file = Path(backup_path)
        if not backup_file.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=command,
                blocked_reason="Backup file not found",
            )

        if not backup_file.name.endswith(".bak"):
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=command,
                blocked_reason="Invalid backup file format",
            )

        metadata_file = backup_file.with_suffix(".bak.json")
        if not metadata_file.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=command,
                blocked_reason="Backup metadata missing; refusing restore",
            )

        try:
            metadata = json.loads(metadata_file.read_text())
            original_path = metadata.get("original_path")
            if not original_path:
                raise ValueError("original_path missing in metadata")
        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=command,
                blocked_reason=f"Invalid backup metadata: {e}",
            )

        target_path = Path(original_path).resolve()

        path_allowed, path_error = self._check_path(str(target_path))
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=command,
                blocked_reason=path_error,
            )

        if target_path.exists() and target_path.is_symlink():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                command=command,
                blocked_reason="Refusing to restore to symlink target",
                path_restricted=True,
            )

        if self.dry_run:
            result = ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                risk_level=RiskLevel.HIGH,
                command=command,
                dry_run=True,
                output=f"Would restore: {backup_path} to {target_path}",
                audit_log=[f"DRY-RUN: Would restore {backup_file.name}"],
            )
            self._log_execution(result)
            return result

        try:
            shutil.copy2(backup_file, target_path)

            result = ExecutionResult(
                status=ExecutionStatus.EXECUTED,
                risk_level=RiskLevel.HIGH,
                command=command,
                output=f"Restored {backup_file.name} to {target_path}",
                audit_log=[f"Restored from backup: {backup_file.name}"],
            )
            self._log_execution(result)
            return result

        except Exception as e:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.HIGH,
                command=command,
                error=str(e),
            )
            self._log_execution(result)
            return result

    def read(self, file_path: str) -> ExecutionResult:
        """Read a file safely."""
        command = f"file_read: {file_path}"

        normalized_path, path_error = self._normalize_path(file_path)
        if not normalized_path:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        path_allowed, path_error = self._check_path(str(normalized_path))
        if not path_allowed:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        if not normalized_path.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="File does not exist",
            )

        try:
            content = normalized_path.read_text()
            result = ExecutionResult(
                status=ExecutionStatus.EXECUTED,
                risk_level=RiskLevel.SAFE,
                command=command,
                output=f"Read {len(content)} chars from {file_path}",
                audit_log=[f"Read {normalized_path}"],
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

    def list_backups(self) -> list[dict[str, Any]]:
        """List available backups."""
        backups = []
        for f in self.backup_dir.glob("*.bak"):
            try:
                stat = f.stat()
                backups.append({
                    "name": f.name,
                    "path": str(f),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except OSError:
                continue
        return sorted(backups, key=lambda x: x["modified"], reverse=True)

    def validate_edit(
        self,
        file_path: str,
        expected_content: str,
    ) -> ExecutionResult:
        """Validate file content matches expected."""
        command = f"file_validate: {file_path}"

        normalized_path, path_error = self._normalize_path(file_path)
        if not normalized_path:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason=path_error,
                path_restricted=True,
            )

        if not normalized_path.exists():
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                risk_level=RiskLevel.SAFE,
                command=command,
                blocked_reason="File does not exist",
            )

        actual_content = normalized_path.read_text()

        if actual_content == expected_content:
            result = ExecutionResult(
                status=ExecutionStatus.EXECUTED,
                risk_level=RiskLevel.SAFE,
                command=command,
                output="Content matches expected",
                audit_log=[f"Validated {normalized_path} - OK"],
            )
        else:
            diff = self._generate_unified_diff(
                actual_content,
                expected_content,
                str(normalized_path),
            )
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                risk_level=RiskLevel.SAFE,
                command=command,
                output="Content does not match",
                error=f"Expected {len(expected_content)} chars, got {len(actual_content)} chars",
                audit_log=[f"Validated {normalized_path} - MISMATCH"],
            )

        self._log_execution(result)
        return result
