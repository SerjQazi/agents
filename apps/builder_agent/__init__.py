"""Compatibility package for apps.planner_agent.* imports."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "planner_agent")]
