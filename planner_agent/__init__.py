"""Compatibility package for imports from planner_agent.*."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "planner_agent")]
