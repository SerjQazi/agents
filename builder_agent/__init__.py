"""Compatibility package for imports from builder_agent.*."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "builder_agent")]
