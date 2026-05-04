"""Read-only service and process inventory for the Planner Agent dashboard."""

from __future__ import annotations

import subprocess
import json
import urllib.error
import urllib.request
from typing import Any


KNOWN_AGENTS = [
    {"name": "AgentOS Dashboard", "service": "agentos.service", "keywords": ["agentos_agent.app:app", "uvicorn api:app"]},
    {
        "name": "Planner Agent",
        "service": "planner-agent.service",
        "keywords": ["apps.planner_agent.app:app", "planner_agent.app:app", "apps.builder_agent.app:app", "builder_agent.app:app"],
    },
    {
        "name": "Planner Agent legacy service",
        "service": "builder-agent.service",
        "keywords": ["apps.builder_agent.app:app", "builder_agent.app:app"],
    },
    {"name": "Bubbles bot", "service": "bubbles.service", "keywords": ["bots.bubbles_agent", "bubbles.py", "bubbles"]},
    {"name": "mailman / mail agent", "service": "mailman.service", "keywords": ["bots.mail_agent", "mailman.py", "mail-agent", "mailman"]},
    {"name": "system_agent", "service": "system-agent.service", "keywords": ["system_agent"]},
    {"name": "maintenance_agent", "service": "maintenance-agent.service", "keywords": ["maintenance_agent"]},
    {"name": "coding_agent", "service": "coding-agent.service", "keywords": ["coding_agent"], "health_url": "http://127.0.0.1:8020/health"},
    {"name": "self_healing_agent", "service": "self-healing-agent.service", "keywords": ["self_healing_agent"]},
    {"name": "Ollama", "service": "ollama.service", "keywords": ["ollama serve"]},
    {"name": "FiveM server", "service": "fivem.service", "keywords": ["FXServer", "txAdmin"]},
]

SERVICE_MATCHES = ("agent", "bubbles", "mail", "ollama", "fivem", "txadmin", "planner", "builder")
PROCESS_MATCHES = ("agent", "bubbles", "mailman", "ollama", "uvicorn", "fivem", "fxserver", "txadmin", "builder", "planner")


def collect_service_inventory() -> dict[str, Any]:
    service_units = _matching_systemd_units()
    process_lines = _matching_processes()
    agents = []
    for known in KNOWN_AGENTS:
        service = str(known["service"])
        keywords = [str(keyword).lower() for keyword in known["keywords"]]
        matching_processes = [
            line for line in process_lines
            if any(keyword in line.lower() for keyword in keywords)
        ]
        agents.append(
            {
                "name": known["name"],
                "service": service,
                "active": _systemctl_value("is-active", service),
                "enabled": _systemctl_value("is-enabled", service),
                "process": "running" if matching_processes else "not seen",
                "health": _health_status(str(known.get("health_url", ""))),
                "process_hint": _short_process(matching_processes[0]) if matching_processes else "",
            }
        )
    return {
        "agents": agents,
        "matching_services": service_units,
        "matching_processes": [_short_process(line) for line in process_lines[:12]],
    }


def _matching_systemd_units() -> list[dict[str, str]]:
    completed = _run(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain"])
    rows = []
    for line in completed.splitlines():
        lowered = line.lower()
        if not any(match in lowered for match in SERVICE_MATCHES):
            continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        rows.append(
            {
                "unit": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4] if len(parts) > 4 else "",
            }
        )
    return rows


def _matching_processes() -> list[str]:
    completed = _run(["ps", "aux"])
    rows = []
    for line in completed.splitlines():
        lowered = line.lower()
        if "grep -ei" in lowered:
            continue
        if any(match in lowered for match in PROCESS_MATCHES):
            rows.append(line)
    return rows


def _systemctl_value(command: str, service: str) -> str:
    completed = subprocess.run(
        ["systemctl", command, service],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    value = (completed.stdout or completed.stderr).strip().splitlines()
    return value[0] if value else "unknown"


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
    return completed.stdout


def _health_status(url: str) -> str:
    if not url:
        return "not checked"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            data = json.loads(response.read().decode("utf-8"))
        return "reachable" if data.get("status") == "ok" else "unhealthy"
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return "unreachable"


def _short_process(line: str) -> str:
    line = " ".join(line.split())
    return line if len(line) <= 180 else line[:177] + "..."
