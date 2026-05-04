"""Shared configuration for the local agent backend."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "AgentOS Agent"
    ollama_url: str = "http://127.0.0.1:11434"
    default_model: str = "llama3.2"


settings = Settings()
