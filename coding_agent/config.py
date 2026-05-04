"""Configuration for the isolated coding_agent service."""

from __future__ import annotations

from pathlib import Path


AGENTS_ROOT = Path("/home/agentzero/agents")
INCOMING_PATH = AGENTS_ROOT / "incoming"
STAGING_PATH = AGENTS_ROOT / "staging" / "coding-agent"
REPORTS_PATH = AGENTS_ROOT / "reports" / "coding-agent"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5-coder:7b"
