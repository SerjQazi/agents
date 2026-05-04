"""Storage stub for coding_agent."""

from __future__ import annotations

from pathlib import Path

from .config import REPORTS_PATH, STAGING_PATH


def ensure_directories() -> None:
    STAGING_PATH.mkdir(parents=True, exist_ok=True)
    REPORTS_PATH.mkdir(parents=True, exist_ok=True)
