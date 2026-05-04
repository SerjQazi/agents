"""Configuration for the isolated Builder Agent service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuilderConfig:
    app_name: str = "Builder Agent"
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
        return self.agents_root / "reports" / "builder-agent"

    @property
    def staging_dir(self) -> Path:
        return self.agents_root / "staging" / "builder-agent"

    @property
    def logs_dir(self) -> Path:
        return self.agents_root / "logs" / "builder-agent"

    @property
    def memory_dir(self) -> Path:
        return self.agents_root / "memory"

    @property
    def database_path(self) -> Path:
        return self.memory_dir / "builder-agent-memory.sqlite"


settings = BuilderConfig()
