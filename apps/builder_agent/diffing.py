"""Diff helpers for Builder Agent staging output."""

from __future__ import annotations

import difflib
from pathlib import Path


def unified_diff_text(source_path: Path | None, staged_path: Path, label: str) -> str:
    if source_path and source_path.is_file():
        source_lines = source_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        source_name = str(source_path)
    else:
        source_lines = []
        source_name = f"{label} (new)"

    staged_lines = staged_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    diff = difflib.unified_diff(source_lines, staged_lines, fromfile=source_name, tofile=str(staged_path))
    return "".join(diff)

