"""Compatibility package for imports from agent_core.*."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "core" / "agent_core")]

from .controller import AgentController

__all__ = ["AgentController"]
