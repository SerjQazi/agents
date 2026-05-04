"""Validation for staging-only Builder Agent output."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def validate_staging(staging_path: Path) -> dict[str, Any]:
    results: dict[str, Any] = {"status": "passed", "checks": []}

    for path in sorted(staging_path.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".sql":
            _add(results, path, "sql_block", "failed", "SQL files are not allowed in staging apply output.")
        elif suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
                _add(results, path, "json_parse", "passed", "JSON parsed.")
            except json.JSONDecodeError as error:
                _add(results, path, "json_parse", "failed", str(error))
        elif suffix == ".js" and shutil.which("node"):
            _run(results, path, "node_check", ["node", "--check", str(path)])
        elif suffix == ".lua":
            luac = shutil.which("luac")
            lua = shutil.which("lua")
            if luac:
                _run(results, path, "lua_syntax", [luac, "-p", str(path)])
            elif lua:
                _run(results, path, "lua_syntax", [lua, "-e", "assert(loadfile(arg[1]))", str(path)])
            else:
                _add(results, path, "lua_syntax", "skipped", "Neither lua nor luac is installed.")

    if any(check["status"] == "failed" for check in results["checks"]):
        results["status"] = "failed"
    return results


def _run(results: dict[str, Any], path: Path, check: str, command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    status = "passed" if completed.returncode == 0 else "failed"
    message = (completed.stdout + completed.stderr).strip() or f"Exit code {completed.returncode}"
    _add(results, path, check, status, message)


def _add(results: dict[str, Any], path: Path, check: str, status: str, message: str) -> None:
    results["checks"].append(
        {
            "file": str(path),
            "check": check,
            "status": status,
            "message": message,
        }
    )

