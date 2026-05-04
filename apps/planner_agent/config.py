"""Configuration for the isolated Planner Agent service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlannerConfig:
    app_name: str = "Planner Agent"
    host: str = "127.0.0.1"
    port: int = 8010
    model: str = "qwen2.5-coder:7b"
    ollama_url: str = "http://127.0.0.1:11434"
    agents_root: Path = Path("/home/agentzero/agents")
    server_resources: Path = Path("/home/agentzero/fivem-server/txData/QBCore_F16AC8.base/resources")

    @property
    def incoming_dir(self) -> Path:
        return self.agents_root / "incoming"

    @property
    def reports_dir(self) -> Path:
        return self.agents_root / "reports" / "planner-agent"

    @property
    def staging_dir(self) -> Path:
        return self.agents_root / "staging" / "planner-agent"

    @property
    def logs_dir(self) -> Path:
        return self.agents_root / "logs" / "planner-agent"

    @property
    def memory_dir(self) -> Path:
        return self.agents_root / "memory"

    @property
    def database_path(self) -> Path:
        return self.memory_dir / "planner-agent-memory.sqlite"


settings = PlannerConfig()
