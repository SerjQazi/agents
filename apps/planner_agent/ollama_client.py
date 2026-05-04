"""Small Ollama API client using only the Python standard library."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class OllamaResult:
    ok: bool
    content: str
    error: str = ""


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, prompt: str, model: str | None = None) -> OllamaResult:
        payload = {
            "model": model or self.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Planner Agent, a plan-only FiveM script adaptation assistant. "
                        "Never claim changes were applied. Produce concise, practical plans."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            return OllamaResult(ok=False, content="", error=str(error))

        message = data.get("message", {})
        content = str(message.get("content", "")).strip()
        return OllamaResult(ok=True, content=content)

