"""Compatibility package for imports from coding_agent.*."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "coding_agent")]
