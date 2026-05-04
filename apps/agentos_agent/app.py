"""FastAPI backend for the local multi-agent dashboard."""

import html
import json
import re
import shutil
import socket
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.agent_core.config import settings
from core.agent_core.controller import AgentController
from core.agent_core.self_healing_agent import SelfHealingAgent
from core.agent_core.system_watcher import SystemWatcher
from apps.shared_layout import layout_css, render_layout


app = FastAPI(title=settings.app_name)
controller = AgentController()
system_watcher = SystemWatcher()
self_healing_agent = SelfHealingAgent()
BASE_DIR = Path(__file__).resolve().parents[2]
GIT_HELPER = BASE_DIR / "scripts" / "git_helper.sh"
BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9/_\.-]+$")
DANGEROUS_MESSAGE_CHARS = re.compile(r"[;&|$`<>\"'\\\n\r]")


class CommandRequest(BaseModel):
    input: str = ""


class CommandApprovalRequest(BaseModel):
    action: str
    args: dict[str, Any] = {}


class SelfHealApprovalRequest(BaseModel):
    action: str


@app.on_event("startup")
async def start_background_agents() -> None:
    await system_watcher.start()
    await self_healing_agent.start()


@app.on_event("shutdown")
async def stop_background_agents() -> None:
    await self_healing_agent.stop()
    await system_watcher.stop()


def run_command(args: list[str]) -> dict:
    try:
        result = subprocess.run(
            args,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "stdout": error.stdout or "",
            "stderr": (error.stderr or "") + "\nCommand timed out.",
            "exit_code": 124,
        }
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }


def sanitize_commit_message(message: str) -> str:
    cleaned = DANGEROUS_MESSAGE_CHARS.sub("", message).strip()
    return cleaned[:120] or "Agent update"


def validate_branch_name(branch_name: str) -> str:
    branch = branch_name.strip()
    blocked_tokens = [";", "&&", "||", "$", "`"]
    if (
        not branch
        or any(token in branch for token in blocked_tokens)
        or any(char.isspace() for char in branch)
        or not BRANCH_NAME_RE.fullmatch(branch)
        or branch.startswith("-")
    ):
        raise ValueError("Invalid branch name. Use letters, numbers, slash, dash, underscore, or dot only.")
    return branch


def system_health_summary() -> dict:
    stats = controller.system_agent.stats()
    return {
        "agent": controller.system_agent.name,
        "response": "System health summary generated.",
        "health": {
            "hostname": stats.get("hostname"),
            "cpu_percent": stats.get("cpu_percent"),
            "memory_percent": stats.get("memory_percent"),
            "disk_percent": stats.get("disk_percent"),
            "uptime": stats.get("uptime"),
            "load_avg": stats.get("load_avg"),
            "current_time": stats.get("current_time"),
        },
    }


def unknown_command_response(command: str) -> dict:
    return {
        "agent": "command_center",
        "response": f"Unknown command: {command or '(empty)'}.",
        "examples": [
            "/system health",
            "/git status",
            "/git push update dashboard controls",
            "/git branch feature/control-panel",
            "/code plan improve dashboard",
        ],
    }


def route_slash_command(raw_input: str) -> dict:
    command = raw_input.strip()
    if not command:
        return unknown_command_response(command)

    if command == "/system health":
        return system_health_summary()

    if command == "/git status":
        result = run_command([str(GIT_HELPER), "status"])
        return {
            "agent": "command_center",
            "response": "Git status completed.",
            "command": "./scripts/git_helper.sh status",
            **result,
        }

    if command == "/git push" or command.startswith("/git push "):
        message = sanitize_commit_message(command.removeprefix("/git push"))
        return {
            "requires_approval": True,
            "action": "git_push",
            "args": {"message": message},
            "command_preview": f'./scripts/git_helper.sh push "{message}"',
            "risk": "Pushes committed/local changes to GitHub.",
        }

    if command.startswith("/git branch "):
        try:
            branch_name = validate_branch_name(command.removeprefix("/git branch "))
        except ValueError as error:
            return {
                "agent": "command_center",
                "response": str(error),
                "examples": ["/git branch feature/test", "/git branch fix/login-state"],
            }
        return {
            "requires_approval": True,
            "action": "git_branch",
            "args": {"branch_name": branch_name},
            "command_preview": f"./scripts/git_helper.sh branch {branch_name}",
            "risk": "Creates or switches git branch.",
        }

    if command.startswith("/code plan "):
        request = command.removeprefix("/code plan ").strip()
        if not request:
            return {
                "agent": "command_center",
                "response": "Provide a planning request after /code plan.",
                "examples": ["/code plan improve dashboard"],
            }
        return controller.local_coding_agent.handle(request)

    return unknown_command_response(command)


def approve_command(action: str, args: dict[str, Any]) -> dict:
    if action == "git_push":
        message = sanitize_commit_message(str(args.get("message", "")))
        result = run_command([str(GIT_HELPER), "push", message])
        return {
            "agent": "command_center",
            "action": action,
            "command": f'./scripts/git_helper.sh push "{message}"',
            **result,
        }

    if action == "git_branch":
        try:
            branch_name = validate_branch_name(str(args.get("branch_name", "")))
        except ValueError as error:
            return {
                "agent": "command_center",
                "action": action,
                "response": str(error),
                "exit_code": 2,
                "stdout": "",
                "stderr": str(error),
            }
        result = run_command([str(GIT_HELPER), "branch", branch_name])
        return {
            "agent": "command_center",
            "action": action,
            "command": f"./scripts/git_helper.sh branch {branch_name}",
            **result,
        }

    return {
        "agent": "command_center",
        "response": "Unsupported approval action.",
        "exit_code": 2,
        "stdout": "",
        "stderr": f"Unsupported action: {action}",
    }


def service_status(service_name: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"

    state = result.stdout.strip()
    if result.returncode == 0 and state == "active":
        return "running"
    if state in {"inactive", "failed", "deactivating", "dead"}:
        return "stopped"
    return "unknown"


AGENT_REGISTRY = [
    {
        "display_name": "AgentOS Agent / Dashboard",
        "group": "Dashboards / Control",
        "order": 10,
        "type": "dashboard",
        "service_name": "agentos",
        "process_keywords": ["apps.agentos_agent.app:app", "uvicorn agentos_app:app", "uvicorn api:app"],
        "url": "http://100.68.10.125:8080",
        "path": "/home/agentzero/agents/apps/agentos_agent/app.py",
        "description": "Main AgentOS dashboard, command center, service monitor, and launchpad.",
        "icon": "🧭",
    },
    {
        "display_name": "Planner Agent",
        "group": "Dashboards / Control",
        "order": 20,
        "type": "dashboard",
        "service_name": "builder-agent",
        "process_keywords": ["apps.builder_agent.app:app", "uvicorn builder_agent.app:app"],
        "url": "/planner",
        "path": "/home/agentzero/agents/apps/builder_agent",
        "description": "Plan-only FiveM script analysis, staging previews, validation, and compatibility reports.",
        "icon": "🛠️",
    },
    {
        "display_name": "Coding Agent",
        "group": "Coding / Build Workers",
        "order": 10,
        "type": "dashboard",
        "service_name": "coding-agent",
        "process_keywords": ["apps.coding_agent.app:app", "uvicorn coding_agent.app:app"],
        "url": "/coding",
        "path": "/home/agentzero/agents/apps/coding_agent",
        "description": "Local coding planning and repo-context helper.",
        "icon": "💻",
    },
    {
        "display_name": "FiveM Agent CLI",
        "group": "Coding / Build Workers",
        "order": 20,
        "type": "cli",
        "service_name": "",
        "process_keywords": [],
        "url": "",
        "path": "/home/agentzero/agents/fivem-agent",
        "description": "FiveM integration/profile/scan/apply command wrapper.",
        "icon": "🎮",
    },
    {
        "display_name": "Bubbles Agent / Telegram bot",
        "group": "Assistant / Notification Agents",
        "order": 10,
        "type": "bot",
        "service_name": "",
        "process_keywords": ["bots.bubbles_agent", "bubbles.py"],
        "url": "",
        "path": "/home/agentzero/agents/bots/bubbles_agent/app.py",
        "description": "Legacy Telegram bot prototype kept for reference.",
        "icon": "💬",
    },
    {
        "display_name": "Mail Agent / mailman",
        "group": "Assistant / Notification Agents",
        "order": 20,
        "type": "bot",
        "service_name": "",
        "process_keywords": ["bots.mail_agent", "mailman.py"],
        "url": "",
        "path": "/home/agentzero/agents/bots/mail_agent/app.py",
        "description": "Legacy mail agent prototype kept for reference.",
        "icon": "✉️",
    },
    {
        "display_name": "System Agent",
        "group": "System / Silent Agents",
        "order": 10,
        "type": "worker",
        "service_name": "",
        "process_keywords": [],
        "url": "",
        "path": "/home/agentzero/agents/core/agent_core/system_agent.py",
        "description": "Internal AgentOS worker for host stats and system health summaries.",
        "icon": "📊",
    },
    {
        "display_name": "Maintenance Agent",
        "group": "System / Silent Agents",
        "order": 20,
        "type": "worker",
        "service_name": "",
        "process_keywords": [],
        "url": "",
        "path": "/home/agentzero/agents/core/agent_core/maintenance_agent.py",
        "description": "Internal maintenance helper for safe system suggestions.",
        "icon": "🧰",
    },
    {
        "display_name": "Self-Healing Agent",
        "group": "System / Silent Agents",
        "order": 30,
        "type": "worker",
        "service_name": "",
        "process_keywords": [],
        "url": "",
        "path": "/home/agentzero/agents/core/agent_core/self_healing_agent.py",
        "description": "Internal monitor that suggests approved recovery actions for AgentOS and dependencies.",
        "icon": "🩺",
    },
    {
        "display_name": "Ollama",
        "group": "Core Services",
        "order": 10,
        "type": "service",
        "service_name": "ollama",
        "process_keywords": ["ollama"],
        "url": "http://127.0.0.1:11434",
        "path": "",
        "description": "Local model runtime used by planning agents when available.",
        "icon": "🧠",
    },
    {
        "display_name": "FiveM Server",
        "group": "Core Services",
        "order": 20,
        "type": "service",
        "service_name": "",
        "process_keywords": ["FXServer", "fivem", "txAdmin"],
        "url": "",
        "path": "/home/agentzero/fivem-server/txData/QBCore_F16AC8.base",
        "description": "Local FiveM/QBCore server workspace and runtime.",
        "icon": "🚦",
    },
]


AGENT_GROUP_ORDER = [
    "Dashboards / Control",
    "Coding / Build Workers",
    "Assistant / Notification Agents",
    "System / Silent Agents",
    "Core Services",
]


def url_is_reachable(url: str, timeout: float = 0.5) -> bool:
    match = re.match(r"^https?://([^/:]+):(\d+)", url)
    if not match:
        return False
    host, port = match.group(1), int(match.group(2))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def process_is_running(keywords: list[str]) -> bool:
    if not keywords:
        return False
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    haystack = result.stdout.lower()
    return any(keyword.lower() in haystack for keyword in keywords)


def detect_agent_entry(agent: dict[str, Any]) -> dict[str, Any]:
    entry = dict(agent)
    agent_type = str(entry.get("type", "worker"))
    service_name = str(entry.get("service_name", ""))
    url = str(entry.get("url", ""))
    path = str(entry.get("path", ""))
    process_keywords = list(entry.get("process_keywords", []))

    service_state = service_status(service_name) if service_name else "no service"
    url_reachable = bool(url and url_is_reachable(url))
    process_running = process_is_running(process_keywords)
    path_exists = bool(path and Path(path).exists())

    if agent_type == "planned":
        status = "planned"
    elif url_reachable:
        status = "online"
    elif service_state == "running" or process_running:
        status = "online"
    elif service_name and service_state == "stopped":
        status = "inactive"
    elif service_name and service_state == "unknown":
        status = "unknown"
    elif agent_type == "cli" and path_exists:
        status = "cli only"
    elif path_exists:
        status = "no service"
    else:
        status = "not installed"

    badges = []
    if status == "online":
        badges.append("Online")
    elif status == "planned":
        badges.append("Planned")
    elif status in {"not installed", "unknown"} and service_name:
        badges.append("Service missing")
    elif status == "cli only":
        badges.append("CLI")
    elif status == "no service":
        badges.append("No UI")
    elif status == "inactive":
        badges.append("Offline")

    if agent_type == "cli" and "CLI" not in badges:
        badges.append("CLI")
    if not url:
        badges.append("No UI")
    elif "127.0.0.1" in url or "localhost" in url:
        badges.append("Local only")

    badges = list(dict.fromkeys(badges))

    if url:
        suggested_action = "Open dashboard" if url_reachable else "Check service or use local host access."
    elif agent_type == "cli":
        suggested_action = f"Run from shell: {path}"
    elif agent_type == "planned":
        suggested_action = "Planned; no runtime action yet."
    elif service_name:
        suggested_action = f"Check service: systemctl status {service_name}"
    else:
        suggested_action = "Internal AgentOS worker; managed by AgentOS."

    entry.update(
        {
            "status": status,
            "badges": badges,
            "service_state": service_state,
            "url_reachable": url_reachable,
            "process_running": process_running,
            "path_exists": path_exists,
            "suggested_action": suggested_action,
        }
    )
    return entry


def agent_registry_snapshot() -> list[dict[str, Any]]:
    group_index = {group: index for index, group in enumerate(AGENT_GROUP_ORDER)}
    return sorted(
        [detect_agent_entry(agent) for agent in AGENT_REGISTRY],
        key=lambda agent: (
            group_index.get(str(agent.get("group", "")), len(group_index)),
            int(agent.get("order", 999)),
            str(agent.get("display_name", "")),
        ),
    )


def render_agent_badges(agent: dict[str, Any], max_badges: int | None = None) -> str:
    badges = list(agent.get("badges", []))
    if max_badges is not None:
        badges = badges[:max_badges]
    return "".join(
        f'<span class="agent-status {esc(str(badge).lower().replace(" ", "-"))}">{esc(badge)}</span>'
        for badge in badges
    )


def render_agent_links_section() -> str:
    grouped: dict[str, list[str]] = {group: [] for group in AGENT_GROUP_ORDER}
    for agent in agent_registry_snapshot():
        target = str(agent.get("url") or "/agents")
        clickable = bool(agent.get("url"))
        tag = "a" if clickable else "div"
        external = target.startswith("http://") or target.startswith("https://")
        target_attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
        attrs = f'class="agent-link" href="{esc(target)}"{target_attrs}' if clickable else 'class="agent-link static"'
        link_html = (
            '<{tag} {attrs}>'
            '<span class="agent-link-icon" aria-hidden="true">{icon}</span>'
            '<span class="agent-link-main"><span class="agent-link-name">{name}</span>'
            '<span class="agent-link-url">{meta}</span></span>'
            '<span class="agent-link-badges">{badges}</span>'
            '</{tag}>'.format(
                tag=tag,
                attrs=attrs,
                icon=esc(agent.get("icon", "")),
                name=esc(agent.get("display_name", "")),
                meta=esc(agent.get("url") or agent.get("type") or "agent"),
                badges=render_agent_badges(agent, max_badges=2),
            )
        )
        grouped.setdefault(str(agent.get("group", "Other")), []).append(link_html)

    group_sections = []
    for group in AGENT_GROUP_ORDER:
        entries = grouped.get(group, [])
        if not entries:
            continue
        group_sections.append(
            '<div class="agent-group">'
            f'<div class="agent-group-title">{esc(group)}</div>'
            + "".join(entries)
            + "</div>"
        )
    return (
        '<details class="sidebar-section" open>'
        '<summary><span>Agents</span><a href="/agents">View all</a></summary>'
        '<div class="agent-links">'
        + "".join(group_sections)
        + "</div></details>"
    )


OPS_CATEGORY_FILTERS = [
    ("all", "All"),
    ("services", "Services"),
    ("logs", "Logs"),
    ("health", "Health Checks"),
    ("git", "Git"),
    ("agents", "Agents"),
    ("fivem", "FiveM"),
    ("recovery", "Recovery"),
]


OPS_COMMAND_GROUPS = [
    {
        "title": "Quick Paths",
        "description": "Common local paths used by AgentOS and FiveM support work.",
        "commands": [
            {
                "title": "Agents repo",
                "description": "Jump to the AgentOS code and workflow repo.",
                "command": "cd /home/agentzero/agents",
                "tags": ["agents"],
            },
            {
                "title": "FiveM resources repo",
                "description": "Jump to the Git repo for live FiveM resources.",
                "command": "cd /home/agentzero/fivem-server/txData/QBCore_F16AC8.base/resources",
                "tags": ["fivem"],
                "note": "Review changes before editing live resources.",
            },
            {
                "title": "Incoming scripts",
                "description": "Third-party scripts waiting for compatibility review.",
                "command": "cd /home/agentzero/agents/incoming",
                "tags": ["fivem", "agents"],
            },
            {
                "title": "Reports folder",
                "description": "Compatibility, coding, builder, and deploy reports.",
                "command": "cd /home/agentzero/agents/reports",
                "tags": ["agents", "logs"],
            },
        ],
    },
    {
        "title": "Service Control",
        "description": "Check local service state without changing runtime behavior.",
        "commands": [
            {
                "title": "AgentOS service status",
                "description": "Show whether the AgentOS API service is active.",
                "command": "systemctl is-active agentos.service\nsystemctl status agentos.service --no-pager",
                "tags": ["services", "health"],
            },
            {
                "title": "Builder Agent service status",
                "description": "Inspect the Builder Agent service without restarting it.",
                "command": "systemctl is-active builder-agent.service\nsystemctl status builder-agent.service --no-pager",
                "tags": ["services", "agents", "health"],
            },
            {
                "title": "List agent services",
                "description": "Find loaded systemd units related to AgentOS or Builder Agent.",
                "command": "systemctl list-units --type=service --all | rg -i 'agent|builder|uvicorn'",
                "tags": ["services", "discovery"],
            },
        ],
    },
    {
        "title": "Logs & Health Checks",
        "description": "Fast checks for logs, ports, local health, and process state.",
        "commands": [
            {
                "title": "AgentOS journal",
                "description": "Follow recent AgentOS service logs.",
                "command": "journalctl -u agentos.service -n 100 -f",
                "tags": ["logs", "services"],
            },
            {
                "title": "Planner Agent journal",
                "description": "Follow recent Planner Agent service logs.",
                "command": "journalctl -u planner-agent.service -n 100 -f",
                "tags": ["logs", "agents", "services"],
            },
            {
                "title": "AgentOS API health",
                "description": "Check local API health endpoints from the shell.",
                "command": "curl http://127.0.0.1:8000/health\ncurl http://127.0.0.1:8000/system",
                "tags": ["health", "agents"],
            },
            {
                "title": "Planner page through AgentOS",
                "description": "Check whether the Planner page renders through AgentOS navigation.",
                "command": "curl http://100.68.10.125:8080/planner",
                "tags": ["health", "agents"],
            },
            {
                "title": "Listening ports",
                "description": "Confirm local services are bound to expected ports.",
                "command": "ss -ltnp",
                "tags": ["health", "discovery"],
            },
            {
                "title": "Agent processes",
                "description": "Find running Python, uvicorn, Ollama, and agent processes.",
                "command": "ps aux | rg -i 'uvicorn|agent|ollama|python'",
                "tags": ["health", "agents", "discovery"],
            },
        ],
    },
    {
        "title": "Manual App Runs",
        "description": "Run local apps directly during development or service troubleshooting.",
        "commands": [
            {
                "title": "Run AgentOS manually",
                "description": "Start the AgentOS Dashboard on localhost.",
                "command": "cd /home/agentzero/agents\nuvicorn apps.agentos_agent.app:app --host 0.0.0.0 --port 8000",
                "tags": ["agents", "services"],
                "note": "Use a different port if the service is already running.",
            },
            {
                "title": "Run Planner Agent manually",
                "description": "Start the Planner Agent dashboard/API on localhost.",
                "command": "cd /home/agentzero/agents\nuvicorn apps.planner_agent.app:app --host 127.0.0.1 --port 8010",
                "tags": ["agents", "services"],
                "note": "Do not run this over the active service unless you intend to debug a separate local process.",
            },
            {
                "title": "Run Coding Agent manually",
                "description": "Start the local coding agent API.",
                "command": "cd /home/agentzero/agents\nuvicorn apps.coding_agent.app:app --host 127.0.0.1 --port 8020",
                "tags": ["agents", "services"],
            },
        ],
    },
    {
        "title": "Git & Push Workflow",
        "description": "Existing safe helpers for status, branch, commit, and push work.",
        "commands": [
            {
                "title": "Agents repo status",
                "description": "Use the existing Git helper for the current repo state.",
                "command": "cd /home/agentzero/agents\n./scripts/git_helper.sh status",
                "tags": ["git", "agents"],
            },
            {
                "title": "Push agents repo",
                "description": "Commit and push AgentOS changes with the existing push script.",
                "command": "cd /home/agentzero/agents\n./scripts/push-to-git.sh",
                "tags": ["git", "agents"],
                "note": "The script refuses likely secret/env/venv paths before committing.",
            },
            {
                "title": "Push FiveM resources repo",
                "description": "Commit and push the FiveM resources repo with the existing server script.",
                "command": "cd /home/agentzero/agents\n./scripts/push-to-server.sh",
                "tags": ["git", "fivem"],
                "note": "Review live resource changes before running.",
            },
            {
                "title": "Create or switch branch",
                "description": "Use the repo helper to create or check out a branch safely.",
                "command": "cd /home/agentzero/agents\n./scripts/git_helper.sh branch feature/name",
                "tags": ["git", "agents"],
            },
            {
                "title": "Raw Git status",
                "description": "Inspect branch tracking and short changes directly.",
                "command": "git status --short --branch",
                "tags": ["git", "health"],
            },
        ],
    },
    {
        "title": "Agents",
        "description": "AgentOS, Planner Agent, and local planning endpoints.",
        "commands": [
            {
                "title": "Command Center health",
                "description": "Ask the dashboard command router for system health.",
                "command": "curl -X POST http://127.0.0.1:8000/command \\\n  -H \"Content-Type: application/json\" \\\n  -d '{\"input\":\"/system health\"}'",
                "tags": ["agents", "health"],
            },
            {
                "title": "Coding plan request",
                "description": "Request a plan-only coding analysis from the local coding agent.",
                "command": "curl \"http://127.0.0.1:8000/coding/plan?request=improve%20dashboard\"",
                "tags": ["agents"],
            },
            {
                "title": "Planner task example",
                "description": "Create a plan-only Planner task through AgentOS for an incoming script.",
                "command": "Open http://100.68.10.125:8080/planner and use the New Task form with script_path incoming/qb-inventory-new",
                "tags": ["agents", "fivem"],
                "note": "Planner Agent planning does not modify live FiveM resources.",
            },
        ],
    },
    {
        "title": "FiveM",
        "description": "Read-only profiling and deployment review commands for FiveM work.",
        "commands": [
            {
                "title": "FiveM agent status",
                "description": "Show status for incoming, staging, reports, and resources.",
                "command": "cd /home/agentzero/agents\n./fivem-agent status",
                "tags": ["fivem", "agents", "health"],
            },
            {
                "title": "Profile FiveM server",
                "description": "Generate a server compatibility profile report.",
                "command": "cd /home/agentzero/agents\n./fivem-agent profile",
                "tags": ["fivem", "agents", "health"],
            },
            {
                "title": "Scan incoming script",
                "description": "Inspect a third-party script before adapting it.",
                "command": "cd /home/agentzero/agents\n./fivem-agent scan incoming/script-folder",
                "tags": ["fivem", "agents"],
            },
            {
                "title": "Deploy dry run",
                "description": "Validate pending repo changes and write a deploy report without committing or pushing.",
                "command": "cd /home/agentzero/agents\n./fivem-agent deploy --dry-run",
                "tags": ["fivem", "recovery", "git"],
                "note": "Dry run only; it does not restart FiveM or run SQL.",
            },
        ],
    },
    {
        "title": "Recovery",
        "description": "Non-destructive commands for finding rollback context and service history.",
        "commands": [
            {
                "title": "Recent deploy reports",
                "description": "List the newest deploy and integration reports.",
                "command": "find /home/agentzero/agents/reports -maxdepth 2 -type f | sort | tail -40",
                "tags": ["recovery", "logs", "fivem"],
            },
            {
                "title": "Recent backups",
                "description": "List backup folders created by FiveM workflows.",
                "command": "find /home/agentzero/agents/backups -maxdepth 1 -mindepth 1 -type d | sort | tail -25",
                "tags": ["recovery", "fivem"],
            },
            {
                "title": "Show latest commits",
                "description": "Review recent Git history before deciding on rollback steps.",
                "command": "git log --oneline --decorate -10",
                "tags": ["recovery", "git"],
            },
            {
                "title": "Check file changes",
                "description": "Review unstaged and staged diffs before commit or recovery.",
                "command": "git diff --check\ngit diff --stat\ngit diff --cached --stat",
                "tags": ["recovery", "git", "health"],
            },
        ],
    },
    {
        "title": "Useful Discovery Commands",
        "description": "Fast search commands used often during local troubleshooting.",
        "commands": [
            {
                "title": "Find files quickly",
                "description": "List files in the current repo using ripgrep.",
                "command": "rg --files",
                "tags": ["discovery"],
            },
            {
                "title": "Search text",
                "description": "Search for routes, services, commands, or configuration.",
                "command": "rg -n \"search text\" /home/agentzero/agents",
                "tags": ["discovery", "agents"],
            },
            {
                "title": "Find README and workflow notes",
                "description": "Locate docs and agent workflow instructions.",
                "command": "rg --files -g 'AGENTS.md' -g 'README*'",
                "tags": ["discovery", "agents"],
            },
            {
                "title": "Show public Tailscale IPv4",
                "description": "Print the local Tailscale IPv4 address if Tailscale is configured.",
                "command": "tailscale ip -4",
                "tags": ["discovery", "health"],
            },
        ],
    },
]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def ops_command_flags(command: dict[str, Any]) -> dict[str, bool]:
    text = f"{command.get('title', '')} {command.get('command', '')}".lower()
    tags = set(command.get("tags", []))
    is_restart = "systemctl restart" in text or " restart " in f" {text} "
    is_git_push = "push-to-git.sh" in text or "push-to-server.sh" in text or "git_helper.sh push" in text
    changes_state = (
        is_restart
        or is_git_push
        or "git_helper.sh branch" in text
        or "\nuvicorn " in text
        or text.startswith("uvicorn ")
        or "fivem-agent profile" in text
        or "fivem-agent scan" in text
        or "fivem-agent deploy" in text
        or "curl -x post" in text
        or "curl -X POST" in str(command.get("command", ""))
    )
    return {
        "restart": is_restart,
        "git_push": is_git_push,
        "git": "git" in tags or "git " in text or "push-to-" in text,
        "service": "services" in tags or "systemctl" in text or "journalctl" in text or "uvicorn" in text,
        "read_only": not changes_state,
        "risky": is_restart or is_git_push,
    }


def ops_badges_html(command: dict[str, Any]) -> str:
    flags = ops_command_flags(command)
    badges = []
    if flags["read_only"]:
        badges.extend([("Read-only", "safe"), ("Safe", "safe")])
    elif not flags["risky"]:
        badges.append(("Safe", "safe"))
    if flags["restart"]:
        badges.append(("Restart", "warn"))
    if flags["git"]:
        badges.append(("Git", "git"))
    if flags["service"]:
        badges.append(("Service", "service"))
    if flags["risky"]:
        badges.append(("Risky", "risk"))
    return "".join(f'<span class="ops-badge {kind}">{esc(label)}</span>' for label, kind in badges)


def ops_icon_svg(command: dict[str, Any]) -> str:
    tags = set(command.get("tags", []))
    flags = ops_command_flags(command)
    if flags["git"]:
        return '<path d="M6 3v7"></path><path d="M18 14v7"></path><path d="M6 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"></path><path d="M18 20a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"></path><path d="M6 10c0 4 12 0 12 4"></path>'
    if "logs" in tags:
        return '<path d="M5 5h14v14H5z"></path><path d="M8 9h8"></path><path d="M8 13h8"></path><path d="M8 17h5"></path>'
    if "health" in tags:
        return '<path d="M20 13c0 5-3.5 8-8 8s-8-3-8-8 3.5-8 8-8 8 3 8 8z"></path><path d="M8 13h2l1.5-4 2 8 1.5-4h2"></path>'
    if "fivem" in tags:
        return '<path d="M6 8h12l2 4v5H4v-5l2-4z"></path><path d="M7 17v2"></path><path d="M17 17v2"></path><path d="M8 12h8"></path>'
    if flags["service"]:
        return '<path d="M12 3v18"></path><path d="M5 8h14"></path><path d="M5 16h14"></path><path d="M7 5h10v14H7z"></path>'
    return '<path d="M4 7h16"></path><path d="M7 12h10"></path><path d="M10 17h4"></path>'


def ops_detail_text(command: dict[str, Any]) -> dict[str, str]:
    flags = ops_command_flags(command)
    tags = set(command.get("tags", []))
    title = str(command.get("title", "this command")).lower()

    if flags["git_push"]:
        affects = "Creates a commit when changes are staged by the script, then pushes the current branch."
        safety = "Changes Git history on the remote branch. Review status before running."
    elif flags["restart"]:
        affects = "Restarts a running service and can interrupt active users or background work."
        safety = "Use only when you intentionally want a service restart."
    elif flags["read_only"]:
        affects = "Only prints information or changes the current shell context."
        safety = "Safe reference command; it does not modify services, databases, or FiveM resources."
    elif "uvicorn" in str(command.get("command", "")).lower():
        affects = "Starts a local foreground app process in your terminal."
        safety = "Use a free port and stop the manual process when done."
    elif "fivem" in tags:
        affects = "Writes local reports or staging context under the agents workspace."
        safety = "Does not run SQL or restart FiveM."
    elif flags["git"]:
        affects = "Changes local Git branch or repository state."
        safety = "Check the target repo and branch before running."
    else:
        affects = "Runs in your shell against the paths shown in the command."
        safety = "Review the command before running."

    return {
        "when": f"Use this when you need to {title}.",
        "affects": affects,
        "safety": safety,
    }


def render_ops_command_card(command: dict[str, Any]) -> str:
    tags = " ".join(str(tag) for tag in command.get("tags", []))
    search_text = " ".join(
        [
            str(command.get("title", "")),
            str(command.get("description", "")),
            str(command.get("command", "")),
            tags,
            str(command.get("note", "")),
        ]
    ).lower()
    flags = ops_command_flags(command)
    details = ops_detail_text(command)
    note = ""
    warnings = []
    if flags["restart"]:
        warnings.append("This restarts a running service.")
    if flags["git_push"]:
        warnings.append("Commits and pushes current repo changes.")
    if command.get("note"):
        warnings.append(str(command["note"]))
    if warnings:
        note = "".join(f'<div class="ops-note">{esc(warning)}</div>' for warning in warnings)
    return f"""
      <article class="ops-card" data-tags="{esc(tags)}" data-search="{esc(search_text)}">
        <div class="ops-card-top">
          <span class="ops-type-icon"><svg viewBox="0 0 24 24">{ops_icon_svg(command)}</svg></span>
          <div>
            <h3>{esc(command["title"])}</h3>
            <p>{esc(command["description"])}</p>
          </div>
        </div>
        <div class="ops-badges">{ops_badges_html(command)}</div>
        <pre><code>{esc(command["command"])}</code></pre>
        <div class="ops-card-actions">
          <button class="copy-button" type="button" aria-label="Copy command">Copy</button>
        </div>
        {note}
        <details class="ops-details">
          <summary>Why use this?</summary>
          <dl>
            <div><dt>When to use it</dt><dd>{esc(details["when"])}</dd></div>
            <div><dt>What it affects</dt><dd>{esc(details["affects"])}</dd></div>
            <div><dt>Safety</dt><dd>{esc(details["safety"])}</dd></div>
          </dl>
        </details>
      </article>
    """


def render_ops_group(group: dict[str, Any]) -> str:
    cards = "".join(render_ops_command_card(command) for command in group["commands"])
    return f"""
      <section class="ops-group" data-group>
        <div class="ops-group-header">
          <h2>{esc(group["title"])}</h2>
          <p>{esc(group["description"])}</p>
        </div>
        <div class="ops-grid">
          {cards}
        </div>
      </section>
    """


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>AgentOS Dashboard</title>
        <style>
          """ + layout_css() + """
          """ + layout_css() + """
          :root {
            color-scheme: dark;
            --bg: #050914;
            --panel: rgba(12, 21, 37, 0.74);
            --panel-strong: rgba(15, 27, 47, 0.9);
            --panel-soft: rgba(8, 16, 31, 0.62);
            --border: rgba(125, 211, 252, 0.2);
            --border-strong: rgba(125, 211, 252, 0.42);
            --text: #eef7ff;
            --muted: #a8b7cc;
            --soft: #6f8098;
            --cyan: #00d4ff;
            --blue: #6ecbff;
            --purple: #ff4fd8;
            --green: #37d67a;
            --track: #142238;
            --danger: #ff6370;
          }

          * {
            box-sizing: border-box;
          }

          body {
            margin: 0;
            min-height: 100vh;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
              radial-gradient(circle at 12% 8%, rgba(64, 224, 208, 0.17), transparent 31%),
              radial-gradient(circle at 88% 4%, rgba(106, 167, 255, 0.18), transparent 30%),
              linear-gradient(145deg, #050914 0%, #08111f 52%, #0d1728 100%);
            color: var(--text);
          }

          button,
          input {
            font: inherit;
          }

          .app-shell {
            display: grid;
            grid-template-columns: var(--ao-sidebar-width, 292px) minmax(0, 1fr);
            min-height: 100vh;
          }

          .sidebar {
            position: sticky;
            top: 0;
            height: 100vh;
            padding: 18px 12px;
            border-right: 1px solid rgba(110, 203, 255, 0.16);
            background:
              linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.018)),
              rgba(5, 9, 20, 0.76);
            box-shadow: 12px 0 36px rgba(0, 0, 0, 0.18);
            backdrop-filter: blur(18px);
          }

          .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 10px 18px;
            color: var(--text);
            font-size: 18px;
            font-weight: 600;
            letter-spacing: 0;
          }

          .brand-mark {
            display: inline-grid;
            place-items: center;
            width: 34px;
            height: 34px;
            border: 1px solid rgba(0, 212, 255, 0.34);
            border-radius: 10px;
            background: rgba(0, 212, 255, 0.12);
            box-shadow: 0 0 22px rgba(0, 212, 255, 0.14);
          }

          .side-nav {
            display: grid;
            gap: 5px;
          }

          .nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            min-height: 40px;
            padding: 9px 10px;
            border: 1px solid transparent;
            border-radius: 10px;
            color: var(--muted);
            text-decoration: none;
            font-size: 14px;
            font-weight: 450;
          }

          .nav-item svg {
            width: 17px;
            height: 17px;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.9;
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .nav-item.active,
          .nav-item:hover {
            border-color: rgba(0, 212, 255, 0.24);
            background: rgba(0, 212, 255, 0.09);
            color: var(--text);
          }

          .sidebar-section {
            margin-top: 14px;
            border-top: 1px solid rgba(110, 203, 255, 0.14);
            padding-top: 12px;
          }

          .sidebar-section summary {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            list-style: none;
            cursor: pointer;
            padding: 0 10px 8px;
            color: var(--soft);
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
          }

          .sidebar-section summary a {
            color: var(--blue);
            font-size: 10px;
            letter-spacing: 0;
            text-decoration: none;
            text-transform: none;
          }

          .sidebar-section summary::-webkit-details-marker { display: none; }

          .agent-links {
            display: grid;
            gap: 12px;
            max-height: 58vh;
            overflow: auto;
            padding-right: 3px;
          }

          .agent-group {
            display: grid;
            gap: 7px;
          }

          .agent-group-title {
            padding: 0 3px;
            color: var(--soft);
            font-size: 10px;
            font-weight: 850;
            letter-spacing: 0.06em;
            text-transform: uppercase;
          }

          .agent-link {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: 7px;
            align-items: center;
            min-height: 44px;
            border: 1px solid rgba(125, 211, 252, 0.16);
            border-radius: 10px;
            padding: 8px 10px;
            color: var(--muted);
            background: rgba(2, 6, 23, 0.18);
            text-decoration: none;
          }

          .agent-link:hover {
            border-color: rgba(0, 212, 255, 0.28);
            background: rgba(0, 212, 255, 0.08);
            color: var(--text);
          }

          .agent-link-icon {
            font-size: 16px;
            line-height: 1;
          }

          .agent-link-main {
            display: grid;
            gap: 2px;
            min-width: 0;
          }

          .agent-link-name {
            color: var(--text);
            font-size: 12px;
            font-weight: 700;
          }

          .agent-link-url {
            overflow: hidden;
            color: var(--soft);
            font-size: 9px;
            text-overflow: ellipsis;
            white-space: nowrap;
          }

          .agent-link-badges {
            grid-column: 1 / -1;
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
          }

          .agent-status {
            justify-self: start;
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 999px;
            padding: 2px 7px;
            color: var(--soft);
            font-size: 10px;
            font-weight: 800;
          }

          .agent-status.online {
            border-color: rgba(55, 214, 122, 0.32);
            color: var(--green);
            background: rgba(21, 128, 61, 0.12);
          }

          .agent-status.local-only,
          .agent-status.cli,
          .agent-status.no-ui {
            border-color: rgba(125, 211, 252, 0.28);
            color: var(--blue);
            background: rgba(14, 165, 233, 0.1);
          }

          .agent-status.offline,
          .agent-status.service-missing {
            border-color: rgba(255, 99, 112, 0.3);
            color: var(--danger);
            background: rgba(127, 29, 29, 0.12);
          }

          .shell {
            width: min(1240px, 100%);
            margin: 0 auto;
            padding: 16px;
          }

          .main-panel {
            min-width: 0;
          }

          .topbar {
            position: sticky;
            top: 0;
            z-index: 8;
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 14px;
            align-items: center;
            margin-bottom: 14px;
            padding: 10px 12px;
            border: 1px solid rgba(110, 203, 255, 0.16);
            border-radius: 16px;
            background: rgba(5, 9, 20, 0.72);
            box-shadow: 0 10px 32px rgba(0, 0, 0, 0.18);
            backdrop-filter: blur(18px);
          }

          .top-command {
            width: min(620px, 100%);
            justify-self: center;
          }

          .input,
          .command-input {
            width: 100%;
            min-height: 44px;
            border: 1px solid rgba(110, 203, 255, 0.2);
            border-radius: 12px;
            padding: 0 13px;
            background: rgba(2, 6, 23, 0.48);
            color: var(--text);
            outline: none;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
          }

          .input:focus,
          .command-input:focus {
            border-color: rgba(0, 212, 255, 0.58);
            box-shadow: 0 0 0 3px rgba(0, 212, 255, 0.1);
          }

          .glass {
            position: relative;
            overflow: hidden;
            border: 1px solid var(--border);
            border-radius: 17px;
            background:
              linear-gradient(180deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.025)),
              var(--panel);
            box-shadow: 0 14px 36px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.07);
            backdrop-filter: blur(18px);
            transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
          }

          .glass:hover {
            border-color: var(--border-strong);
            transform: translateY(-2px);
            box-shadow: 0 18px 46px rgba(0, 0, 0, 0.3), 0 0 24px rgba(64, 224, 208, 0.06);
          }

          .hero {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            min-height: 118px;
            margin-bottom: 14px;
            padding: 18px 20px;
            background:
              linear-gradient(180deg, rgba(255, 255, 255, 0.065), rgba(255, 255, 255, 0.018)),
              rgba(8, 17, 31, 0.78);
          }

          .hero::before {
            content: "";
            position: absolute;
            inset: 0;
            background:
              linear-gradient(90deg, rgba(125, 211, 252, 0.05) 1px, transparent 1px),
              linear-gradient(0deg, rgba(125, 211, 252, 0.04) 1px, transparent 1px),
              radial-gradient(circle at 78% 30%, rgba(64, 224, 208, 0.16), transparent 34%);
            background-size: 28px 28px, 28px 28px, 100% 100%;
            opacity: 0.55;
            pointer-events: none;
          }

          .hero::after {
            content: "";
            position: absolute;
            inset: 0;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 620 150'%3E%3Cdefs%3E%3ClinearGradient id='w' x1='0' x2='1' y1='0' y2='0'%3E%3Cstop offset='0' stop-color='%236aa7ff' stop-opacity='0'/%3E%3Cstop offset='.45' stop-color='%2340e0d0' stop-opacity='.62'/%3E%3Cstop offset='1' stop-color='%236aa7ff' stop-opacity='.12'/%3E%3C/linearGradient%3E%3C/defs%3E%3Cg fill='none' stroke-linecap='round'%3E%3Cpath d='M210 108 C270 42 340 40 406 74 S516 116 612 44' stroke='url(%23w)' stroke-width='2.3'/%3E%3Cpath d='M178 82 C262 20 336 28 414 58 S520 96 618 26' stroke='%236aa7ff' stroke-width='1.55' opacity='.42'/%3E%3Cpath d='M240 132 C312 80 368 88 438 114 S548 130 620 86' stroke='%23a8eaff' stroke-width='1.25' opacity='.3'/%3E%3Cpath d='M286 28 C346 54 410 28 464 48 S552 78 620 36' stroke='%2340e0d0' stroke-width='1.1' opacity='.22'/%3E%3C/g%3E%3Cg fill='%237dd3fc'%3E%3Ccircle cx='402' cy='24' r='1.1' opacity='.38'/%3E%3Ccircle cx='432' cy='48' r='1.3' opacity='.5'/%3E%3Ccircle cx='468' cy='28' r='1' opacity='.36'/%3E%3Ccircle cx='500' cy='60' r='1.2' opacity='.48'/%3E%3Ccircle cx='538' cy='36' r='1.1' opacity='.4'/%3E%3Ccircle cx='584' cy='64' r='1.2' opacity='.46'/%3E%3Ccircle cx='606' cy='104' r='1' opacity='.34'/%3E%3Ccircle cx='456' cy='110' r='1' opacity='.3'/%3E%3Ccircle cx='526' cy='124' r='1.15' opacity='.38'/%3E%3Ccircle cx='588' cy='18' r='1' opacity='.34'/%3E%3C/g%3E%3C/svg%3E");
            background-position: right center;
            background-repeat: no-repeat;
            background-size: min(78%, 620px) 100%;
            opacity: 0.82;
            mask-image: linear-gradient(90deg, transparent 0%, black 28%, black 100%);
            pointer-events: none;
          }

          .hero > * {
            position: relative;
            z-index: 1;
          }

          h1 {
            margin: 0;
            font-size: clamp(36px, 9vw, 54px);
            line-height: 0.95;
            letter-spacing: 0;
            font-weight: 700;
          }

          .subtitle {
            margin: 10px 0 0;
            color: var(--muted);
            font-size: 17px;
          }

          .hostname {
            margin: 8px 0 0;
            color: var(--soft);
            font-size: 14px;
            overflow-wrap: anywhere;
          }


          .hero-actions {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: flex-end;
          }

          .hero-actions .button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
          }

          .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            align-self: flex-start;
            min-height: 34px;
            padding: 7px 12px;
            border: 1px solid rgba(55, 214, 122, 0.35);
            border-radius: 999px;
            background: rgba(21, 128, 61, 0.16);
            color: #d9ffe9;
            font-size: 13px;
            font-weight: 600;
            white-space: nowrap;
          }

          .status-pill.offline {
            border-color: rgba(255, 99, 112, 0.4);
            background: rgba(127, 29, 29, 0.2);
            color: #ffd6da;
          }

          .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 16px rgba(55, 214, 122, 0.75);
          }

          .status-pill.offline .dot {
            background: var(--danger);
            box-shadow: 0 0 16px rgba(255, 99, 112, 0.75);
          }

          .dashboard-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 14px;
          }

          .card {
            min-height: 236px;
            padding: 16px;
          }

          .command-card,
          .logs-panel {
            margin-bottom: 14px;
            padding: 16px;
          }

          .command-card {
            min-height: 0;
          }

          .command-form {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 10px;
            align-items: center;
          }

          .button {
            min-height: 44px;
            border: 1px solid rgba(0, 212, 255, 0.38);
            border-radius: 12px;
            padding: 0 16px;
            background:
              linear-gradient(135deg, rgba(0, 212, 255, 0.28), rgba(255, 79, 216, 0.18)),
              rgba(2, 6, 23, 0.52);
            color: var(--text);
            cursor: pointer;
            font-weight: 550;
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.11);
          }

          .button:hover {
            border-color: rgba(255, 79, 216, 0.45);
          }

          .button.secondary {
            min-height: 34px;
            padding: 0 12px;
            border-color: rgba(110, 203, 255, 0.22);
            background: rgba(2, 6, 23, 0.34);
            color: var(--muted);
            font-size: 13px;
          }

          .command-output {
            display: none;
            margin-top: 12px;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 12px;
            background: rgba(2, 6, 23, 0.36);
            color: var(--muted);
            font-size: 13px;
            line-height: 1.45;
            white-space: pre-wrap;
          }

          .command-output.visible {
            display: block;
          }

          .card-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 14px;
            color: var(--muted);
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
          }

          .icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border: 1px solid rgba(125, 211, 252, 0.24);
            border-radius: 8px;
            background: rgba(96, 165, 250, 0.11);
            color: #9bdcff;
            flex: 0 0 auto;
          }

          .icon svg {
            width: 16px;
            height: 16px;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.9;
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .gauge-wrap {
            display: grid;
            place-items: center;
            min-height: 174px;
            overflow: visible;
          }

          .gauge {
            width: 174px;
            height: 174px;
            overflow: visible;
          }

          .gauge-track,
          .gauge-progress {
            fill: none;
            stroke-width: 12;
            transform: rotate(-90deg);
            transform-origin: 80px 80px;
          }

          .gauge-track {
            stroke: var(--track);
          }

          .gauge-progress {
            stroke: var(--cyan);
            stroke-linecap: round;
            stroke-dasharray: 364.42;
            stroke-dashoffset: 364.42;
            filter: drop-shadow(0 0 8px rgba(64, 224, 208, 0.38));
            transition: stroke-dashoffset 520ms ease;
          }

          .ram-gauge .gauge-progress {
            stroke: url(#ramGradient);
            filter: drop-shadow(0 0 8px rgba(167, 139, 250, 0.38));
          }

          .disk-gauge .gauge-progress {
            stroke: url(#diskGradient);
          }

          .gauge-dot {
            fill: #e7fff9;
            filter: drop-shadow(0 0 7px rgba(64, 224, 208, 0.9));
            transform-origin: 80px 80px;
            transition: transform 520ms ease;
          }

          .gauge-content {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            width: 100%;
            height: 100%;
            color: var(--text);
            line-height: 1.05;
            text-align: center;
          }

          .gauge-main {
            font-size: 23px;
            font-weight: 600;
            white-space: nowrap;
          }

          .gauge-sub {
            margin-top: 3px;
            color: var(--muted);
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
          }

          .gauge-label {
            margin-top: 2px;
            color: var(--soft);
            font-size: 12px;
          }

          .below-note {
            margin: 10px 0 0;
            color: var(--muted);
            font-size: 14px;
            text-align: center;
          }

          .stat-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 9px;
            margin-top: 14px;
          }

          .stat {
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 10px;
            padding: 9px;
            background: rgba(2, 6, 23, 0.28);
          }

          .stat-label {
            display: block;
            color: var(--soft);
            font-size: 11px;
            letter-spacing: 0.05em;
            text-transform: uppercase;
          }

          .stat-value {
            display: block;
            margin-top: 4px;
            color: var(--text);
            font-size: 15px;
            font-weight: 600;
          }

          .disk-body {
            display: grid;
            grid-template-columns: 145px 1fr;
            gap: 18px;
            align-items: center;
          }

          .disk-body .gauge {
            width: 134px;
            height: 134px;
          }

          .disk-body .gauge-main {
            font-size: 21px;
          }

          .disk-stats {
            display: grid;
            gap: 9px;
          }

          .disk-row {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
            border-bottom: 1px solid rgba(148, 163, 184, 0.12);
            padding-bottom: 7px;
          }

          .disk-row span:first-child {
            color: var(--muted);
            font-size: 13px;
          }

          .disk-row span:last-child {
            color: var(--text);
            font-size: 16px;
            font-weight: 600;
          }

          .bar {
            height: 8px;
            margin-top: 16px;
            overflow: hidden;
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 999px;
            background: rgba(3, 7, 18, 0.72);
          }

          .fill {
            width: 0%;
            height: 100%;
            border-radius: inherit;
            background: linear-gradient(90deg, var(--green), var(--cyan));
            box-shadow: 0 0 16px rgba(64, 224, 208, 0.45);
            transition: width 520ms ease;
          }

          .uptime-main,
          .time-main,
          .date-main {
            margin: 0;
            color: var(--text);
            font-size: clamp(30px, 7vw, 42px);
            line-height: 1.05;
            font-weight: 600;
            overflow-wrap: anywhere;
          }

          .time-card,
          .date-card {
            min-height: 150px;
          }

          .time-card,
          .date-card {
            display: flex;
            flex-direction: column;
          }

          .time-card .card-header,
          .date-card .card-header {
            margin-bottom: 12px;
          }

          .time-date-body {
            display: flex;
            align-items: center;
            justify-content: flex-start;
            gap: 18px;
            flex: 1;
            width: 100%;
          }

          .time-date-text {
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-width: 0;
          }

          .time-support,
          .date-support {
            display: grid;
            gap: 5px;
            margin-top: 10px;
            color: var(--muted);
            font-size: 13px;
          }

          .time-support span,
          .date-support span {
            color: var(--soft);
          }

          .clock-accent {
            position: relative;
            width: 78px;
            height: 78px;
            border: 1px solid rgba(125, 211, 252, 0.18);
            border-radius: 50%;
            background:
              radial-gradient(circle at center, rgba(64, 224, 208, 0.12), transparent 54%),
              rgba(2, 6, 23, 0.22);
            box-shadow: inset 0 0 22px rgba(64, 224, 208, 0.08);
            opacity: 0.9;
          }

          .clock-accent::before,
          .clock-accent::after {
            content: "";
            position: absolute;
            left: 50%;
            top: 50%;
            width: 2px;
            border-radius: 99px;
            background: rgba(157, 220, 255, 0.72);
            transform-origin: bottom center;
          }

          .clock-accent::before {
            height: 23px;
            transform: translate(-50%, -100%) rotate(35deg);
          }

          .clock-accent::after {
            height: 17px;
            transform: translate(-50%, -100%) rotate(118deg);
          }

          .calendar-accent {
            width: 78px;
            border: 1px solid rgba(125, 211, 252, 0.18);
            border-radius: 12px;
            overflow: hidden;
            background: rgba(2, 6, 23, 0.26);
            box-shadow: inset 0 0 22px rgba(64, 224, 208, 0.07);
            opacity: 0.92;
          }

          .calendar-accent .cal-top {
            height: 20px;
            background: linear-gradient(90deg, rgba(64, 224, 208, 0.26), rgba(106, 167, 255, 0.22));
          }

          .calendar-accent .cal-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 5px;
            padding: 10px;
          }

          .calendar-accent .cal-grid span {
            width: 10px;
            height: 10px;
            border-radius: 3px;
            background: rgba(125, 211, 252, 0.18);
          }

          .date-main {
            font-size: clamp(25px, 6vw, 34px);
          }

          .meta-list {
            display: grid;
            gap: 10px;
            margin-top: 18px;
          }

          .meta-line {
            display: flex;
            align-items: center;
            gap: 9px;
            color: var(--muted);
            font-size: 14px;
          }

          .mini-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 24px;
            height: 24px;
            border-radius: 7px;
            background: rgba(96, 165, 250, 0.1);
            color: #9bdcff;
          }

          .mini-icon svg {
            width: 14px;
            height: 14px;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.9;
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .agents-panel {
            margin-top: 14px;
            padding: 18px;
          }

          .agents-title {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 0 0 14px;
            color: var(--text);
            font-size: 17px;
            font-weight: 600;
            letter-spacing: 0;
          }

          .agent-list {
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
            margin: 0;
            padding: 0;
            list-style: none;
          }

          .agent-list li {
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 10px;
            align-items: center;
            min-height: 76px;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.15);
            border-radius: 12px;
            background: rgba(2, 6, 23, 0.3);
          }

          .agent-meta {
            min-width: 0;
          }

          .agent-name {
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--text);
            font-size: 15px;
            font-weight: 550;
          }

          .agent-description {
            display: block;
            margin-top: 4px;
            color: var(--muted);
            font-size: 13px;
            line-height: 1.35;
          }

          .agent-status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 14px rgba(55, 214, 122, 0.7);
            flex: 0 0 auto;
          }

          .logs-panel {
            margin-top: 14px;
          }

          .log-stream {
            display: grid;
            gap: 8px;
            max-height: 220px;
            overflow: auto;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 12px;
            background: rgba(2, 6, 23, 0.34);
            color: var(--muted);
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 12px;
            line-height: 1.45;
          }

          .log-line {
            display: grid;
            grid-template-columns: 84px 124px 1fr;
            gap: 10px;
            align-items: baseline;
          }

          .log-line.is-new {
            animation: logFadeIn 260ms ease-out;
          }

          .log-time {
            color: var(--soft);
          }

          .log-source {
            color: var(--blue);
          }

          .log-message {
            color: var(--muted);
          }

          .log-line.warning .log-message,
          .log-line.warning .log-level {
            color: #facc15;
          }

          .log-line.error .log-message,
          .log-line.error .log-level {
            color: var(--danger);
          }

          .log-level {
            display: inline-block;
            min-width: 48px;
            margin-right: 7px;
            color: var(--soft);
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.06em;
          }

          @keyframes logFadeIn {
            from {
              opacity: 0;
            }
            to {
              opacity: 1;
            }
          }

          footer {
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 14px 2px 2px;
            color: var(--muted);
            font-size: 13px;
          }

          .connection {
            color: var(--soft);
          }

          @media (min-width: 760px) {
            .shell {
              padding: 22px;
            }

            .dashboard-grid {
              grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .agent-list {
              grid-template-columns: repeat(3, minmax(0, 1fr));
            }

            footer {
              flex-direction: row;
              justify-content: space-between;
              align-items: center;
            }
          }

          @media (max-width: 860px) {
            .app-shell {
              grid-template-columns: 1fr;
            }

            .sidebar {
              position: sticky;
              top: 0;
              z-index: 9;
              display: flex;
              align-items: center;
              gap: 10px;
              height: auto;
              padding: 10px;
              overflow-x: auto;
              border-right: 0;
              border-bottom: 1px solid rgba(110, 203, 255, 0.16);
            }

            .brand {
              padding: 0 8px 0 0;
              white-space: nowrap;
            }

            .side-nav {
              display: flex;
              gap: 6px;
            }

            .nav-item {
              white-space: nowrap;
            }

            .sidebar-section {
              flex: 0 0 auto;
              margin-top: 0;
              border-top: 0;
              padding-top: 0;
            }

            .sidebar-section summary {
              padding: 9px 8px;
            }

            .agent-links {
              display: flex;
              gap: 10px;
              max-height: none;
              overflow: visible;
            }

            .agent-group {
              display: flex;
              align-items: stretch;
              gap: 6px;
            }

            .agent-group-title {
              align-self: center;
              white-space: nowrap;
            }

            .agent-link {
              min-width: 196px;
            }

            .topbar {
              position: static;
              grid-template-columns: 1fr;
            }

            .top-command {
              justify-self: stretch;
            }
          }

          @media (max-width: 520px) {
            .hero {
              min-height: 118px;
              padding: 16px;
            }

            .topbar .status-pill {
              position: static;
              justify-self: start;
            }

            .disk-body {
              grid-template-columns: 1fr;
              justify-items: center;
              gap: 12px;
            }

            .disk-stats {
              width: 100%;
            }

            .command-form {
              grid-template-columns: 1fr;
            }

            .agent-list li {
              grid-template-columns: auto 1fr;
            }

            .agent-list .button {
              grid-column: 1 / -1;
              width: 100%;
            }

            .log-line {
              grid-template-columns: 1fr;
              gap: 2px;
            }
          }

          @media (hover: none) {
            .glass:hover {
              transform: none;
            }
          }
        </style>
      </head>
      <body>
        <div class="app-shell">
          """ + app_sidebar("dashboard") + """
          <main class="shell main-panel">
          <header class="hero glass">
            <div>
              <h1>AgentOS Dashboard</h1>
              <p class="subtitle">AgentOS Agent control and system monitor</p>
              <p class="hostname">Host: <span id="hero-hostname">--</span></p>
            </div>
            <div class="hero-actions">
              <a class="button" href="/control">Open Control Panel</a>
              <div class="status-pill"><span class="dot"></span><span id="server-status">Online</span></div>
            </div>
          </header>

          <section class="dashboard-grid" aria-label="Server dashboard">
            <article class="card glass">
              <div class="card-header">
                <span class="icon"><svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="2"></rect><path d="M4 9h3M4 15h3M17 9h3M17 15h3M9 4v3M15 4v3M9 17v3M15 17v3"></path></svg></span>
                CPU Usage
              </div>
              <div class="gauge-wrap">
                <svg class="gauge" viewBox="0 0 160 160" aria-hidden="true">
                  <defs>
                    <linearGradient id="cpuGradient" x1="0" x2="1" y1="0" y2="1">
                      <stop offset="0%" stop-color="#37d67a"></stop>
                      <stop offset="100%" stop-color="#00d4ff"></stop>
                    </linearGradient>
                  </defs>
                  <circle class="gauge-track" cx="80" cy="80" r="58"></circle>
                  <circle class="gauge-progress" id="cpu-gauge" cx="80" cy="80" r="58" stroke="url(#cpuGradient)"></circle>
                  <circle class="gauge-dot" id="cpu-dot" cx="80" cy="22" r="4"></circle>
                  <foreignObject x="36" y="50" width="88" height="62">
                    <div class="gauge-content" xmlns="http://www.w3.org/1999/xhtml">
                      <div class="gauge-main"><span id="cpu-value">--</span>%</div>
                      <div class="gauge-sub"><span id="cpu-active-cores-value">--</span> / <span id="cpu-total-cores-value">--</span></div>
                      <div class="gauge-label">cores active</div>
                    </div>
                  </foreignObject>
                </svg>
              </div>
              <p class="below-note"><span id="cpu-total-note">--</span> Total Cores</p>
            </article>

            <article class="card glass">
              <div class="card-header">
                <span class="icon"><svg viewBox="0 0 24 24"><rect x="5" y="7" width="14" height="10" rx="2"></rect><path d="M8 3v4M12 3v4M16 3v4M8 17v4M12 17v4M16 17v4"></path></svg></span>
                RAM Usage
              </div>
              <div class="gauge-wrap">
                <svg class="gauge ram-gauge" viewBox="0 0 160 160" aria-hidden="true">
                  <defs>
                    <linearGradient id="ramGradient" x1="0" x2="1" y1="0" y2="1">
                      <stop offset="0%" stop-color="#6ecbff"></stop>
                      <stop offset="100%" stop-color="#ff4fd8"></stop>
                    </linearGradient>
                  </defs>
                  <circle class="gauge-track" cx="80" cy="80" r="58"></circle>
                  <circle class="gauge-progress" id="memory-gauge" cx="80" cy="80" r="58"></circle>
                  <circle class="gauge-dot" id="memory-dot" cx="80" cy="22" r="4"></circle>
                  <foreignObject x="36" y="50" width="88" height="62">
                    <div class="gauge-content" xmlns="http://www.w3.org/1999/xhtml">
                      <div class="gauge-main"><span id="memory-value">--</span>%</div>
                      <div class="gauge-sub"><span id="memory-used-center">--</span> GB</div>
                      <div class="gauge-label">used</div>
                    </div>
                  </foreignObject>
                </svg>
              </div>
              <div class="stat-grid">
                <div class="stat"><span class="stat-label">Used</span><span class="stat-value"><span id="memory-used-value">--</span> GB</span></div>
                <div class="stat"><span class="stat-label">Free</span><span class="stat-value"><span id="memory-free-value">--</span> GB</span></div>
                <div class="stat"><span class="stat-label">Total</span><span class="stat-value"><span id="memory-total-value">--</span> GB</span></div>
              </div>
            </article>

            <article class="card glass">
              <div class="card-header">
                <span class="icon"><svg viewBox="0 0 24 24"><ellipse cx="12" cy="6" rx="7" ry="3"></ellipse><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6"></path><path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"></path></svg></span>
                Disk Usage
              </div>
              <div class="disk-body">
                <svg class="gauge disk-gauge" viewBox="0 0 160 160" aria-hidden="true">
                  <defs>
                    <linearGradient id="diskGradient" x1="0" x2="1" y1="0" y2="1">
                      <stop offset="0%" stop-color="#37d67a"></stop>
                      <stop offset="100%" stop-color="#00d4ff"></stop>
                    </linearGradient>
                  </defs>
                  <circle class="gauge-track" cx="80" cy="80" r="58"></circle>
                  <circle class="gauge-progress" id="disk-gauge" cx="80" cy="80" r="58"></circle>
                  <circle class="gauge-dot" id="disk-dot" cx="80" cy="22" r="4"></circle>
                  <foreignObject x="36" y="58" width="88" height="44">
                    <div class="gauge-content" xmlns="http://www.w3.org/1999/xhtml">
                      <div class="gauge-main"><span id="disk-value">--</span>%</div>
                    </div>
                  </foreignObject>
                </svg>
                <div class="disk-stats">
                  <div class="disk-row"><span>Used</span><span><span id="disk-used-value">--</span> GB</span></div>
                  <div class="disk-row"><span>Free</span><span><span id="disk-free-value">--</span> GB</span></div>
                  <div class="disk-row"><span>Total</span><span><span id="disk-total-value">--</span> GB</span></div>
                </div>
              </div>
              <div class="bar"><div class="fill" id="disk-bar"></div></div>
            </article>

            <article class="card glass">
              <div class="card-header">
                <span class="icon"><svg viewBox="0 0 24 24"><path d="M12 7v5l3 2"></path><circle cx="12" cy="12" r="8"></circle><path d="M12 2v3"></path></svg></span>
                Uptime
              </div>
              <p class="uptime-main" id="uptime-value">--</p>
              <div class="meta-list">
                <div class="meta-line"><span class="mini-icon"><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 8-8v4l5-5-5-5v4A10 10 0 1 0 22 12"></path></svg></span>Booted: <span id="boot-time-value">--</span></div>
                <div class="meta-line"><span class="mini-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"></circle><path d="M12 8v4l3 2"></path></svg></span>Updated: <span id="uptime-updated-value">--</span></div>
                <div class="meta-line"><span class="mini-icon"><svg viewBox="0 0 24 24"><path d="M4 16l4-4 3 3 5-7 4 5"></path></svg></span>Load: <span id="load-average-value">--</span></div>
              </div>
            </article>

            <article class="card glass time-card">
              <div class="card-header">
                <span class="icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"></circle><path d="M12 8v4l3 2"></path></svg></span>
                Current Time
              </div>
              <div class="time-date-body">
                <div class="clock-accent" aria-hidden="true"></div>
                <div class="time-date-text">
                  <p class="time-main" id="time-value">--</p>
                  <div class="time-support">
                    <div>Server time</div>
                    <div>Seconds: <span id="time-seconds-value">--</span></div>
                  </div>
                </div>
              </div>
            </article>

            <article class="card glass date-card">
              <div class="card-header">
                <span class="icon"><svg viewBox="0 0 24 24"><rect x="5" y="6" width="14" height="13" rx="2"></rect><path d="M8 3v4M16 3v4M5 10h14"></path></svg></span>
                Current Date
              </div>
              <div class="time-date-body">
                <div class="calendar-accent" aria-hidden="true">
                  <div class="cal-top"></div>
                  <div class="cal-grid">
                    <span></span><span></span><span></span>
                    <span></span><span></span><span></span>
                  </div>
                </div>
                <div class="time-date-text">
                  <p class="date-main" id="date-value">--</p>
                  <div class="date-support">
                    <div id="weekday-value">--</div>
                    <div><span id="month-year-value">--</span> · Day <span id="day-year-value">--</span></div>
                  </div>
                </div>
              </div>
            </article>
          </section>

          <section class="agents-panel glass" id="agents" aria-label="Available agents">
            <h2 class="agents-title"><span class="icon"><svg viewBox="0 0 24 24"><path d="M12 3l7 4v6c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"></path><path d="M9 12h6M12 9v6"></path></svg></span>Available Agents</h2>
            <ul class="agent-list" id="agents-list">
              <li><span class="agent-meta"><span class="agent-description">Loading available agents...</span></span></li>
            </ul>
          </section>

          <footer>
            <span id="last-updated">Last updated: never</span>
            <span class="connection">Connection: <span id="connection-status">checking</span></span>
          </footer>

        </main>
        </div>

        <script>
          const CIRCUMFERENCE = 364.42;

          const els = {
            serverStatus: document.getElementById("server-status"),
            statusPill: document.querySelector(".status-pill"),
            heroHostname: document.getElementById("hero-hostname"),
            cpuValue: document.getElementById("cpu-value"),
            cpuActiveCoresValue: document.getElementById("cpu-active-cores-value"),
            cpuTotalCoresValue: document.getElementById("cpu-total-cores-value"),
            cpuTotalNote: document.getElementById("cpu-total-note"),
            cpuGauge: document.getElementById("cpu-gauge"),
            cpuDot: document.getElementById("cpu-dot"),
            memoryValue: document.getElementById("memory-value"),
            memoryUsedCenter: document.getElementById("memory-used-center"),
            memoryUsedValue: document.getElementById("memory-used-value"),
            memoryFreeValue: document.getElementById("memory-free-value"),
            memoryTotalValue: document.getElementById("memory-total-value"),
            memoryGauge: document.getElementById("memory-gauge"),
            memoryDot: document.getElementById("memory-dot"),
            diskValue: document.getElementById("disk-value"),
            diskUsedValue: document.getElementById("disk-used-value"),
            diskTotalValue: document.getElementById("disk-total-value"),
            diskFreeValue: document.getElementById("disk-free-value"),
            diskGauge: document.getElementById("disk-gauge"),
            diskDot: document.getElementById("disk-dot"),
            diskBar: document.getElementById("disk-bar"),
            uptimeValue: document.getElementById("uptime-value"),
            bootTimeValue: document.getElementById("boot-time-value"),
            uptimeUpdatedValue: document.getElementById("uptime-updated-value"),
            loadAverageValue: document.getElementById("load-average-value"),
            timeValue: document.getElementById("time-value"),
            timeSecondsValue: document.getElementById("time-seconds-value"),
            dateValue: document.getElementById("date-value"),
            weekdayValue: document.getElementById("weekday-value"),
            monthYearValue: document.getElementById("month-year-value"),
            dayYearValue: document.getElementById("day-year-value"),
            agentsList: document.getElementById("agents-list"),
            lastUpdated: document.getElementById("last-updated"),
            connectionStatus: document.getElementById("connection-status"),
          };

          function formatPercent(value) {
            const number = Number(value);
            return Number.isFinite(number) ? number.toFixed(1) : "--";
          }

          function formatGb(value, decimals = 0) {
            const number = Number(value);
            return Number.isFinite(number) ? number.toFixed(decimals) : "--";
          }

          function setGauge(gauge, dot, value) {
            const number = Math.max(0, Math.min(100, Number(value) || 0));
            gauge.style.strokeDashoffset = CIRCUMFERENCE - (number / 100) * CIRCUMFERENCE;
            dot.style.transform = "rotate(" + (number * 3.6) + "deg)";
          }

          function setBar(element, value) {
            const number = Math.max(0, Math.min(100, Number(value) || 0));
            element.style.width = number + "%";
          }

          function formatBootTime(value) {
            if (!value) {
              return "--";
            }
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) {
              return "--";
            }
            return date.toLocaleString([], {
              month: "short",
              day: "numeric",
              year: "numeric",
              hour: "numeric",
              minute: "2-digit",
            });
          }

          function formatLoad(loadAvg) {
            if (!loadAvg) {
              return "--";
            }
            const one = Number(loadAvg["1m"]);
            const five = Number(loadAvg["5m"]);
            const fifteen = Number(loadAvg["15m"]);
            if (![one, five, fifteen].every(Number.isFinite)) {
              return "--";
            }
            return one.toFixed(2) + " / " + five.toFixed(2) + " / " + fifteen.toFixed(2);
          }

          function dayOfYear(date) {
            const start = new Date(date.getFullYear(), 0, 0);
            const diff = date - start + (start.getTimezoneOffset() - date.getTimezoneOffset()) * 60000;
            return Math.floor(diff / 86400000);
          }

          function setAgents(agents) {
            els.agentsList.innerHTML = "";
            if (!Array.isArray(agents) || agents.length === 0) {
              els.agentsList.innerHTML = '<li><span class="agent-meta"><span class="agent-description">Unable to load available agents.</span></span></li>';
              return;
            }
            for (const agent of agents) {
              if (!agent || !agent.name) {
                continue;
              }
              els.agentsList.insertAdjacentHTML(
                "beforeend",
                agentCardHtml(agent.name, agent.description || "Local agent available")
              );
            }
          }

          function agentCardHtml(name, description) {
            return '<li><span class="icon">' + agentIcon(name) + '</span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>' + escapeHtml(name) + '</span><span class="agent-description">' + escapeHtml(description) + '</span></span></li>';
          }

          function escapeHtml(value) {
            return String(value)
              .replaceAll("&", "&amp;")
              .replaceAll("<", "&lt;")
              .replaceAll(">", "&gt;")
              .replaceAll('"', "&quot;")
              .replaceAll("'", "&#039;");
          }

          function agentIcon(name) {
            if (name === "system_agent") {
              return '<svg viewBox="0 0 24 24"><rect x="5" y="6" width="14" height="10" rx="2"></rect><path d="M8 20h8M12 16v4"></path></svg>';
            }
            if (name === "maintenance_agent") {
              return '<svg viewBox="0 0 24 24"><path d="M14 6l4 4-8 8H6v-4l8-8z"></path><path d="M16 4l4 4"></path></svg>';
            }
            if (name === "coding_agent") {
              return '<svg viewBox="0 0 24 24"><path d="M8 9l-4 3 4 3M16 9l4 3-4 3M14 5l-4 14"></path></svg>';
            }
            return '<svg viewBox="0 0 24 24"><path d="M12 3l7 4v6c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"></path></svg>';
          }

          async function refreshDashboard() {
            try {
              const [systemResponse, agentsResponse] = await Promise.all([
                fetch("/system", { cache: "no-store" }),
                fetch("/agents/data", { cache: "no-store" }),
              ]);

              if (!systemResponse.ok || !agentsResponse.ok) {
                throw new Error("Dashboard request failed");
              }

              const system = await systemResponse.json();
              const agents = await agentsResponse.json();
              const now = new Date();

              els.serverStatus.textContent = "Online";
              els.statusPill.classList.remove("offline");
              els.connectionStatus.textContent = "online";
              els.heroHostname.textContent = system.hostname || "--";

              els.cpuValue.textContent = formatPercent(system.cpu_percent);
              els.cpuActiveCoresValue.textContent = system.cpu_cores_active ?? "--";
              els.cpuTotalCoresValue.textContent = system.cpu_cores_total ?? "--";
              els.cpuTotalNote.textContent = system.cpu_cores_total ?? "--";
              setGauge(els.cpuGauge, els.cpuDot, system.cpu_percent);

              els.memoryValue.textContent = formatPercent(system.memory_percent);
              els.memoryUsedCenter.textContent = formatGb(system.memory_used_gb, 1);
              els.memoryUsedValue.textContent = formatGb(system.memory_used_gb, 1);
              els.memoryFreeValue.textContent = formatGb(system.memory_free_gb, 1);
              els.memoryTotalValue.textContent = formatGb(system.memory_total_gb, 1);
              setGauge(els.memoryGauge, els.memoryDot, system.memory_percent);

              els.diskValue.textContent = formatPercent(system.disk_percent);
              els.diskUsedValue.textContent = formatGb(system.disk_used_gb);
              els.diskTotalValue.textContent = formatGb(system.disk_total_gb);
              els.diskFreeValue.textContent = formatGb(system.disk_free_gb);
              setGauge(els.diskGauge, els.diskDot, system.disk_percent);
              setBar(els.diskBar, system.disk_percent);

              els.uptimeValue.textContent = system.uptime || "--";
              els.bootTimeValue.textContent = formatBootTime(system.boot_time);
              els.uptimeUpdatedValue.textContent = now.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              });
              els.loadAverageValue.textContent = formatLoad(system.load_avg);

              if (system.current_time) {
                const serverDate = new Date(system.current_time);
                els.timeValue.textContent = serverDate.toLocaleTimeString([], {
                  hour: "numeric",
                  minute: "2-digit",
                });
                els.timeSecondsValue.textContent = serverDate.toLocaleTimeString([], {
                  second: "2-digit",
                });
                els.dateValue.textContent = serverDate.toLocaleDateString([], {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                });
                els.weekdayValue.textContent = serverDate.toLocaleDateString([], {
                  weekday: "long",
                });
                els.monthYearValue.textContent = serverDate.toLocaleDateString([], {
                  month: "long",
                  year: "numeric",
                });
                els.dayYearValue.textContent = dayOfYear(serverDate);
              } else {
                els.timeValue.textContent = "--";
                els.timeSecondsValue.textContent = "--";
                els.dateValue.textContent = "--";
                els.weekdayValue.textContent = "--";
                els.monthYearValue.textContent = "--";
                els.dayYearValue.textContent = "--";
              }

              setAgents(agents.agents);
              els.lastUpdated.textContent = "Last updated: " + now.toLocaleTimeString();
            } catch (error) {
              els.serverStatus.textContent = "Offline";
              els.statusPill.classList.add("offline");
              els.connectionStatus.textContent = "offline";
              els.lastUpdated.textContent = "Last updated: failed at " + new Date().toLocaleTimeString();
              els.agentsList.innerHTML = '<li><span class="agent-meta"><span class="agent-description">Unable to load available agents.</span></span></li>';
            }
          }

          refreshDashboard();
          setInterval(refreshDashboard, 5000);
        </script>

      </body>
    </html>
    """


@app.get("/control", response_class=HTMLResponse)
def control_panel() -> str:
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>AgentOS Control Panel</title>
        <style>
          """ + layout_css() + """
          :root {
            color-scheme: dark;
            --bg: #050914;
            --panel: rgba(12, 21, 37, 0.74);
            --panel-strong: rgba(15, 27, 47, 0.9);
            --panel-soft: rgba(8, 16, 31, 0.62);
            --border: rgba(125, 211, 252, 0.2);
            --border-strong: rgba(125, 211, 252, 0.42);
            --text: #eef7ff;
            --muted: #a8b7cc;
            --soft: #6f8098;
            --cyan: #00d4ff;
            --blue: #6ecbff;
            --purple: #ff4fd8;
            --green: #37d67a;
            --track: #142238;
            --danger: #ff6370;
          }

          * {
            box-sizing: border-box;
          }

          body {
            margin: 0;
            min-height: 100vh;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
              radial-gradient(circle at 12% 8%, rgba(64, 224, 208, 0.17), transparent 31%),
              radial-gradient(circle at 88% 4%, rgba(106, 167, 255, 0.18), transparent 30%),
              linear-gradient(145deg, #050914 0%, #08111f 52%, #0d1728 100%);
            color: var(--text);
          }

          button,
          input {
            font: inherit;
          }

          .app-shell {
            display: grid;
            grid-template-columns: var(--ao-sidebar-width, 292px) minmax(0, 1fr);
            min-height: 100vh;
          }

          .sidebar {
            position: sticky;
            top: 0;
            height: 100vh;
            padding: 18px 12px;
            border-right: 1px solid rgba(110, 203, 255, 0.16);
            background:
              linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.018)),
              rgba(5, 9, 20, 0.76);
            box-shadow: 12px 0 36px rgba(0, 0, 0, 0.18);
            backdrop-filter: blur(18px);
          }

          .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 10px 18px;
            color: var(--text);
            font-size: 18px;
            font-weight: 600;
            letter-spacing: 0;
          }

          .brand-mark {
            display: inline-grid;
            place-items: center;
            width: 34px;
            height: 34px;
            border: 1px solid rgba(0, 212, 255, 0.34);
            border-radius: 10px;
            background: rgba(0, 212, 255, 0.12);
            box-shadow: 0 0 22px rgba(0, 212, 255, 0.14);
          }

          .side-nav {
            display: grid;
            gap: 5px;
          }

          .nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            min-height: 40px;
            padding: 9px 10px;
            border: 1px solid transparent;
            border-radius: 10px;
            color: var(--muted);
            text-decoration: none;
            font-size: 14px;
            font-weight: 450;
          }

          .nav-item svg {
            width: 17px;
            height: 17px;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.9;
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .nav-item.active,
          .nav-item:hover {
            border-color: rgba(0, 212, 255, 0.24);
            background: rgba(0, 212, 255, 0.09);
            color: var(--text);
          }

          .sidebar-section {
            margin-top: 14px;
            border-top: 1px solid rgba(110, 203, 255, 0.14);
            padding-top: 12px;
          }

          .sidebar-section summary {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            list-style: none;
            cursor: pointer;
            padding: 0 10px 8px;
            color: var(--soft);
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
          }

          .sidebar-section summary a {
            color: var(--blue);
            font-size: 10px;
            letter-spacing: 0;
            text-decoration: none;
            text-transform: none;
          }

          .sidebar-section summary::-webkit-details-marker { display: none; }

          .agent-links {
            display: grid;
            gap: 12px;
            max-height: 58vh;
            overflow: auto;
            padding-right: 3px;
          }

          .agent-group {
            display: grid;
            gap: 7px;
          }

          .agent-group-title {
            padding: 0 3px;
            color: var(--soft);
            font-size: 10px;
            font-weight: 850;
            letter-spacing: 0.06em;
            text-transform: uppercase;
          }

          .agent-link {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: 7px;
            align-items: center;
            min-height: 44px;
            border: 1px solid rgba(125, 211, 252, 0.16);
            border-radius: 10px;
            padding: 8px 10px;
            color: var(--muted);
            background: rgba(2, 6, 23, 0.18);
            text-decoration: none;
          }

          .agent-link:hover {
            border-color: rgba(0, 212, 255, 0.28);
            background: rgba(0, 212, 255, 0.08);
            color: var(--text);
          }

          .agent-link-icon {
            font-size: 16px;
            line-height: 1;
          }

          .agent-link-main {
            display: grid;
            gap: 2px;
            min-width: 0;
          }

          .agent-link-name {
            color: var(--text);
            font-size: 12px;
            font-weight: 700;
          }

          .agent-link-url {
            overflow: hidden;
            color: var(--soft);
            font-size: 9px;
            text-overflow: ellipsis;
            white-space: nowrap;
          }

          .agent-link-badges {
            grid-column: 1 / -1;
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
          }

          .agent-status {
            justify-self: start;
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 999px;
            padding: 2px 7px;
            color: var(--soft);
            font-size: 10px;
            font-weight: 800;
          }

          .agent-status.online {
            border-color: rgba(55, 214, 122, 0.32);
            color: var(--green);
            background: rgba(21, 128, 61, 0.12);
          }

          .agent-status.local-only,
          .agent-status.cli,
          .agent-status.no-ui {
            border-color: rgba(125, 211, 252, 0.28);
            color: var(--blue);
            background: rgba(14, 165, 233, 0.1);
          }

          .agent-status.offline,
          .agent-status.service-missing {
            border-color: rgba(255, 99, 112, 0.3);
            color: var(--danger);
            background: rgba(127, 29, 29, 0.12);
          }

          .shell {
            width: min(1240px, 100%);
            margin: 0 auto;
            padding: 16px;
          }

          .main-panel {
            min-width: 0;
          }

          .topbar {
            position: sticky;
            top: 0;
            z-index: 8;
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 14px;
            align-items: center;
            margin-bottom: 14px;
            padding: 10px 12px;
            border: 1px solid rgba(110, 203, 255, 0.16);
            border-radius: 16px;
            background: rgba(5, 9, 20, 0.72);
            box-shadow: 0 10px 32px rgba(0, 0, 0, 0.18);
            backdrop-filter: blur(18px);
          }

          .top-command {
            width: min(620px, 100%);
            justify-self: center;
          }

          .input,
          .command-input {
            width: 100%;
            min-height: 44px;
            border: 1px solid rgba(110, 203, 255, 0.2);
            border-radius: 12px;
            padding: 0 13px;
            background: rgba(2, 6, 23, 0.48);
            color: var(--text);
            outline: none;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
          }

          .input:focus,
          .command-input:focus {
            border-color: rgba(0, 212, 255, 0.58);
            box-shadow: 0 0 0 3px rgba(0, 212, 255, 0.1);
          }

          .glass {
            position: relative;
            overflow: hidden;
            border: 1px solid var(--border);
            border-radius: 17px;
            background:
              linear-gradient(180deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.025)),
              var(--panel);
            box-shadow: 0 14px 36px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.07);
            backdrop-filter: blur(18px);
            transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
          }

          .glass:hover {
            border-color: var(--border-strong);
            transform: translateY(-2px);
            box-shadow: 0 18px 46px rgba(0, 0, 0, 0.3), 0 0 24px rgba(64, 224, 208, 0.06);
          }

          .hero {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            min-height: 118px;
            margin-bottom: 14px;
            padding: 18px 20px;
            background:
              linear-gradient(180deg, rgba(255, 255, 255, 0.065), rgba(255, 255, 255, 0.018)),
              rgba(8, 17, 31, 0.78);
          }

          .hero::before {
            content: "";
            position: absolute;
            inset: 0;
            background:
              linear-gradient(90deg, rgba(125, 211, 252, 0.05) 1px, transparent 1px),
              linear-gradient(0deg, rgba(125, 211, 252, 0.04) 1px, transparent 1px),
              radial-gradient(circle at 78% 30%, rgba(64, 224, 208, 0.16), transparent 34%);
            background-size: 28px 28px, 28px 28px, 100% 100%;
            opacity: 0.55;
            pointer-events: none;
          }

          .hero::after {
            content: "";
            position: absolute;
            inset: 0;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 620 150'%3E%3Cdefs%3E%3ClinearGradient id='w' x1='0' x2='1' y1='0' y2='0'%3E%3Cstop offset='0' stop-color='%236aa7ff' stop-opacity='0'/%3E%3Cstop offset='.45' stop-color='%2340e0d0' stop-opacity='.62'/%3E%3Cstop offset='1' stop-color='%236aa7ff' stop-opacity='.12'/%3E%3C/linearGradient%3E%3C/defs%3E%3Cg fill='none' stroke-linecap='round'%3E%3Cpath d='M210 108 C270 42 340 40 406 74 S516 116 612 44' stroke='url(%23w)' stroke-width='2.3'/%3E%3Cpath d='M178 82 C262 20 336 28 414 58 S520 96 618 26' stroke='%236aa7ff' stroke-width='1.55' opacity='.42'/%3E%3Cpath d='M240 132 C312 80 368 88 438 114 S548 130 620 86' stroke='%23a8eaff' stroke-width='1.25' opacity='.3'/%3E%3Cpath d='M286 28 C346 54 410 28 464 48 S552 78 620 36' stroke='%2340e0d0' stroke-width='1.1' opacity='.22'/%3E%3C/g%3E%3Cg fill='%237dd3fc'%3E%3Ccircle cx='402' cy='24' r='1.1' opacity='.38'/%3E%3Ccircle cx='432' cy='48' r='1.3' opacity='.5'/%3E%3Ccircle cx='468' cy='28' r='1' opacity='.36'/%3E%3Ccircle cx='500' cy='60' r='1.2' opacity='.48'/%3E%3Ccircle cx='538' cy='36' r='1.1' opacity='.4'/%3E%3Ccircle cx='584' cy='64' r='1.2' opacity='.46'/%3E%3Ccircle cx='606' cy='104' r='1' opacity='.34'/%3E%3Ccircle cx='456' cy='110' r='1' opacity='.3'/%3E%3Ccircle cx='526' cy='124' r='1.15' opacity='.38'/%3E%3Ccircle cx='588' cy='18' r='1' opacity='.34'/%3E%3C/g%3E%3C/svg%3E");
            background-position: right center;
            background-repeat: no-repeat;
            background-size: min(78%, 620px) 100%;
            opacity: 0.82;
            mask-image: linear-gradient(90deg, transparent 0%, black 28%, black 100%);
            pointer-events: none;
          }

          .hero > * {
            position: relative;
            z-index: 1;
          }

          h1 {
            margin: 0;
            font-size: clamp(36px, 9vw, 54px);
            line-height: 0.95;
            letter-spacing: 0;
            font-weight: 700;
          }

          .subtitle {
            margin: 10px 0 0;
            color: var(--muted);
            font-size: 17px;
          }

          .hostname {
            margin: 8px 0 0;
            color: var(--soft);
            font-size: 14px;
            overflow-wrap: anywhere;
          }


          .hero-actions {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: flex-end;
          }

          .hero-actions .button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
          }

          .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            align-self: flex-start;
            min-height: 34px;
            padding: 7px 12px;
            border: 1px solid rgba(55, 214, 122, 0.35);
            border-radius: 999px;
            background: rgba(21, 128, 61, 0.16);
            color: #d9ffe9;
            font-size: 13px;
            font-weight: 600;
            white-space: nowrap;
          }

          .status-pill.offline {
            border-color: rgba(255, 99, 112, 0.4);
            background: rgba(127, 29, 29, 0.2);
            color: #ffd6da;
          }

          .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 16px rgba(55, 214, 122, 0.75);
          }

          .status-pill.offline .dot {
            background: var(--danger);
            box-shadow: 0 0 16px rgba(255, 99, 112, 0.75);
          }

          .dashboard-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 14px;
          }

          .card {
            min-height: 236px;
            padding: 16px;
          }

          .command-card,
          .logs-panel {
            margin-bottom: 14px;
            padding: 16px;
          }

          .command-card {
            min-height: 0;
          }

          .command-form {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 10px;
            align-items: center;
          }

          .button {
            min-height: 44px;
            border: 1px solid rgba(0, 212, 255, 0.38);
            border-radius: 12px;
            padding: 0 16px;
            background:
              linear-gradient(135deg, rgba(0, 212, 255, 0.28), rgba(255, 79, 216, 0.18)),
              rgba(2, 6, 23, 0.52);
            color: var(--text);
            cursor: pointer;
            font-weight: 550;
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.11);
          }

          .button:hover {
            border-color: rgba(255, 79, 216, 0.45);
          }

          .button.secondary {
            min-height: 34px;
            padding: 0 12px;
            border-color: rgba(110, 203, 255, 0.22);
            background: rgba(2, 6, 23, 0.34);
            color: var(--muted);
            font-size: 13px;
          }

          .command-output {
            display: none;
            margin-top: 12px;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 12px;
            background: rgba(2, 6, 23, 0.36);
            color: var(--muted);
            font-size: 13px;
            line-height: 1.45;
            white-space: pre-wrap;
          }

          .command-output.visible {
            display: block;
          }

          .card-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 14px;
            color: var(--muted);
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
          }

          .icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border: 1px solid rgba(125, 211, 252, 0.24);
            border-radius: 8px;
            background: rgba(96, 165, 250, 0.11);
            color: #9bdcff;
            flex: 0 0 auto;
          }

          .icon svg {
            width: 16px;
            height: 16px;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.9;
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .gauge-wrap {
            display: grid;
            place-items: center;
            min-height: 174px;
            overflow: visible;
          }

          .gauge {
            width: 174px;
            height: 174px;
            overflow: visible;
          }

          .gauge-track,
          .gauge-progress {
            fill: none;
            stroke-width: 12;
            transform: rotate(-90deg);
            transform-origin: 80px 80px;
          }

          .gauge-track {
            stroke: var(--track);
          }

          .gauge-progress {
            stroke: var(--cyan);
            stroke-linecap: round;
            stroke-dasharray: 364.42;
            stroke-dashoffset: 364.42;
            filter: drop-shadow(0 0 8px rgba(64, 224, 208, 0.38));
            transition: stroke-dashoffset 520ms ease;
          }

          .ram-gauge .gauge-progress {
            stroke: url(#ramGradient);
            filter: drop-shadow(0 0 8px rgba(167, 139, 250, 0.38));
          }

          .disk-gauge .gauge-progress {
            stroke: url(#diskGradient);
          }

          .gauge-dot {
            fill: #e7fff9;
            filter: drop-shadow(0 0 7px rgba(64, 224, 208, 0.9));
            transform-origin: 80px 80px;
            transition: transform 520ms ease;
          }

          .gauge-content {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            width: 100%;
            height: 100%;
            color: var(--text);
            line-height: 1.05;
            text-align: center;
          }

          .gauge-main {
            font-size: 23px;
            font-weight: 600;
            white-space: nowrap;
          }

          .gauge-sub {
            margin-top: 3px;
            color: var(--muted);
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
          }

          .gauge-label {
            margin-top: 2px;
            color: var(--soft);
            font-size: 12px;
          }

          .below-note {
            margin: 10px 0 0;
            color: var(--muted);
            font-size: 14px;
            text-align: center;
          }

          .stat-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 9px;
            margin-top: 14px;
          }

          .stat {
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 10px;
            padding: 9px;
            background: rgba(2, 6, 23, 0.28);
          }

          .stat-label {
            display: block;
            color: var(--soft);
            font-size: 11px;
            letter-spacing: 0.05em;
            text-transform: uppercase;
          }

          .stat-value {
            display: block;
            margin-top: 4px;
            color: var(--text);
            font-size: 15px;
            font-weight: 600;
          }

          .disk-body {
            display: grid;
            grid-template-columns: 145px 1fr;
            gap: 18px;
            align-items: center;
          }

          .disk-body .gauge {
            width: 134px;
            height: 134px;
          }

          .disk-body .gauge-main {
            font-size: 21px;
          }

          .disk-stats {
            display: grid;
            gap: 9px;
          }

          .disk-row {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
            border-bottom: 1px solid rgba(148, 163, 184, 0.12);
            padding-bottom: 7px;
          }

          .disk-row span:first-child {
            color: var(--muted);
            font-size: 13px;
          }

          .disk-row span:last-child {
            color: var(--text);
            font-size: 16px;
            font-weight: 600;
          }

          .bar {
            height: 8px;
            margin-top: 16px;
            overflow: hidden;
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 999px;
            background: rgba(3, 7, 18, 0.72);
          }

          .fill {
            width: 0%;
            height: 100%;
            border-radius: inherit;
            background: linear-gradient(90deg, var(--green), var(--cyan));
            box-shadow: 0 0 16px rgba(64, 224, 208, 0.45);
            transition: width 520ms ease;
          }

          .uptime-main,
          .time-main,
          .date-main {
            margin: 0;
            color: var(--text);
            font-size: clamp(30px, 7vw, 42px);
            line-height: 1.05;
            font-weight: 600;
            overflow-wrap: anywhere;
          }

          .time-card,
          .date-card {
            min-height: 150px;
          }

          .time-card,
          .date-card {
            display: flex;
            flex-direction: column;
          }

          .time-card .card-header,
          .date-card .card-header {
            margin-bottom: 12px;
          }

          .time-date-body {
            display: flex;
            align-items: center;
            justify-content: flex-start;
            gap: 18px;
            flex: 1;
            width: 100%;
          }

          .time-date-text {
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-width: 0;
          }

          .time-support,
          .date-support {
            display: grid;
            gap: 5px;
            margin-top: 10px;
            color: var(--muted);
            font-size: 13px;
          }

          .time-support span,
          .date-support span {
            color: var(--soft);
          }

          .clock-accent {
            position: relative;
            width: 78px;
            height: 78px;
            border: 1px solid rgba(125, 211, 252, 0.18);
            border-radius: 50%;
            background:
              radial-gradient(circle at center, rgba(64, 224, 208, 0.12), transparent 54%),
              rgba(2, 6, 23, 0.22);
            box-shadow: inset 0 0 22px rgba(64, 224, 208, 0.08);
            opacity: 0.9;
          }

          .clock-accent::before,
          .clock-accent::after {
            content: "";
            position: absolute;
            left: 50%;
            top: 50%;
            width: 2px;
            border-radius: 99px;
            background: rgba(157, 220, 255, 0.72);
            transform-origin: bottom center;
          }

          .clock-accent::before {
            height: 23px;
            transform: translate(-50%, -100%) rotate(35deg);
          }

          .clock-accent::after {
            height: 17px;
            transform: translate(-50%, -100%) rotate(118deg);
          }

          .calendar-accent {
            width: 78px;
            border: 1px solid rgba(125, 211, 252, 0.18);
            border-radius: 12px;
            overflow: hidden;
            background: rgba(2, 6, 23, 0.26);
            box-shadow: inset 0 0 22px rgba(64, 224, 208, 0.07);
            opacity: 0.92;
          }

          .calendar-accent .cal-top {
            height: 20px;
            background: linear-gradient(90deg, rgba(64, 224, 208, 0.26), rgba(106, 167, 255, 0.22));
          }

          .calendar-accent .cal-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 5px;
            padding: 10px;
          }

          .calendar-accent .cal-grid span {
            width: 10px;
            height: 10px;
            border-radius: 3px;
            background: rgba(125, 211, 252, 0.18);
          }

          .date-main {
            font-size: clamp(25px, 6vw, 34px);
          }

          .meta-list {
            display: grid;
            gap: 10px;
            margin-top: 18px;
          }

          .meta-line {
            display: flex;
            align-items: center;
            gap: 9px;
            color: var(--muted);
            font-size: 14px;
          }

          .mini-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 24px;
            height: 24px;
            border-radius: 7px;
            background: rgba(96, 165, 250, 0.1);
            color: #9bdcff;
          }

          .mini-icon svg {
            width: 14px;
            height: 14px;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.9;
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .agents-panel {
            margin-top: 14px;
            padding: 18px;
          }

          .agents-title {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 0 0 14px;
            color: var(--text);
            font-size: 17px;
            font-weight: 600;
            letter-spacing: 0;
          }

          .agent-list {
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
            margin: 0;
            padding: 0;
            list-style: none;
          }

          .agent-list li {
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 10px;
            align-items: center;
            min-height: 76px;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.15);
            border-radius: 12px;
            background: rgba(2, 6, 23, 0.3);
          }

          .agent-meta {
            min-width: 0;
          }

          .agent-name {
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--text);
            font-size: 15px;
            font-weight: 550;
          }

          .agent-description {
            display: block;
            margin-top: 4px;
            color: var(--muted);
            font-size: 13px;
            line-height: 1.35;
          }

          .agent-status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 14px rgba(55, 214, 122, 0.7);
            flex: 0 0 auto;
          }

          .logs-panel {
            margin-top: 14px;
          }

          .log-stream {
            display: grid;
            gap: 8px;
            max-height: 220px;
            overflow: auto;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 12px;
            background: rgba(2, 6, 23, 0.34);
            color: var(--muted);
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 12px;
            line-height: 1.45;
          }

          .log-line {
            display: grid;
            grid-template-columns: 84px 124px 1fr;
            gap: 10px;
            align-items: baseline;
          }

          .log-time {
            color: var(--soft);
          }

          .log-source {
            color: var(--blue);
          }

          .log-message {
            color: var(--muted);
          }

          footer {
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 14px 2px 2px;
            color: var(--muted);
            font-size: 13px;
          }

          .connection {
            color: var(--soft);
          }

          @media (min-width: 760px) {
            .shell {
              padding: 22px;
            }

            .dashboard-grid {
              grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .agent-list {
              grid-template-columns: repeat(3, minmax(0, 1fr));
            }

            footer {
              flex-direction: row;
              justify-content: space-between;
              align-items: center;
            }
          }

          @media (max-width: 860px) {
            .app-shell {
              grid-template-columns: 1fr;
            }

            .sidebar {
              position: sticky;
              top: 0;
              z-index: 9;
              display: flex;
              align-items: center;
              gap: 10px;
              height: auto;
              padding: 10px;
              overflow-x: auto;
              border-right: 0;
              border-bottom: 1px solid rgba(110, 203, 255, 0.16);
            }

            .brand {
              padding: 0 8px 0 0;
              white-space: nowrap;
            }

            .side-nav {
              display: flex;
              gap: 6px;
            }

            .nav-item {
              white-space: nowrap;
            }

            .sidebar-section {
              flex: 0 0 auto;
              margin-top: 0;
              border-top: 0;
              padding-top: 0;
            }

            .sidebar-section summary {
              padding: 9px 8px;
            }

            .agent-links {
              display: flex;
              gap: 10px;
              max-height: none;
              overflow: visible;
            }

            .agent-group {
              display: flex;
              align-items: stretch;
              gap: 6px;
            }

            .agent-group-title {
              align-self: center;
              white-space: nowrap;
            }

            .agent-link {
              min-width: 196px;
            }

            .topbar {
              position: static;
              grid-template-columns: 1fr;
            }

            .top-command {
              justify-self: stretch;
            }
          }

          @media (max-width: 520px) {
            .hero {
              min-height: 118px;
              padding: 16px;
            }

            .topbar .status-pill {
              position: static;
              justify-self: start;
            }

            .disk-body {
              grid-template-columns: 1fr;
              justify-items: center;
              gap: 12px;
            }

            .disk-stats {
              width: 100%;
            }

            .command-form {
              grid-template-columns: 1fr;
            }

            .agent-list li {
              grid-template-columns: auto 1fr;
            }

            .agent-list .button {
              grid-column: 1 / -1;
              width: 100%;
            }

            .log-line {
              grid-template-columns: 1fr;
              gap: 2px;
            }
          }

          @media (hover: none) {
            .glass:hover {
              transform: none;
            }
          }
        </style>
      </head>
      <body>
        <div class="app-shell">
          """ + app_sidebar("control") + """

          <main class="shell main-panel">
          <section class="agents-panel glass" id="services" aria-label="System services">
            <h2 class="agents-title"><span class="icon"><svg viewBox="0 0 24 24"><path d="M5 12h14"></path><path d="M12 5v14"></path></svg></span>System Services</h2>
            <ul class="agent-list" id="services-list">
              <li><span class="icon"><svg viewBox="0 0 24 24"><path d="M12 3l7 4v6c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"></path></svg></span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>Loading</span><span class="agent-description">Checking local services</span></span><button class="button secondary" type="button">--</button></li>
            </ul>
          </section>

          <section class="agents-panel glass" id="agents" aria-label="Available agents">
            <h2 class="agents-title"><span class="icon"><svg viewBox="0 0 24 24"><path d="M12 3l7 4v6c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"></path><path d="M9 12h6M12 9v6"></path></svg></span>Available Agents</h2>
            <ul class="agent-list" id="agents-list">
              <li><span class="agent-meta"><span class="agent-description">Loading available agents...</span></span></li>
            </ul>
            <ul class="agent-list" id="self-heal-status-list">
              <li><span class="icon"><svg viewBox="0 0 24 24"><path d="M12 3l7 4v6c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"></path></svg></span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>self_healing_agent</span><span class="agent-description">Status: checking · Last check: -- · Suggestions: --</span></span></li>
            </ul>
          </section>

          <section class="command-card glass" id="control-panel" aria-label="Command center">
            <div class="card-header">
              <span class="icon"><svg viewBox="0 0 24 24"><path d="M4 7h16M7 7v10M17 7v10M4 17h16"></path></svg></span>
              Command Center
            </div>
            <form class="command-form" id="command-form">
              <input class="command-input" id="command-input" type="text" placeholder="Type a command..." autocomplete="off">
              <button class="button" type="submit">Run</button>
            </form>
            <div class="command-output" id="command-output" aria-live="polite"></div>
          </section>

          <section class="logs-panel glass" id="logs" aria-label="System logs">
            <div class="card-header">
              <span class="icon"><svg viewBox="0 0 24 24"><path d="M5 5h14v14H5z"></path><path d="M8 9h8M8 13h8M8 17h5"></path></svg></span>
              System Logs
            </div>
            <div class="log-stream" id="log-stream" role="log" aria-live="polite"></div>
            <ul class="agent-list" id="self-heal-suggestions">
              <li><span class="icon"><svg viewBox="0 0 24 24"><path d="M12 3l7 4v6c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"></path></svg></span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>System healthy</span><span class="agent-description">System healthy. No actions required.</span></span></li>
            </ul>
          </section>

          <footer>
            <span id="last-updated">Last updated: never</span>
            <span class="connection">Connection: <span id="connection-status">checking</span></span>
          </footer>

        </main>
        </div>

        <script>
          const els = {
            serverStatus: document.getElementById("server-status"),
            statusPill: document.querySelector(".status-pill"),
            agentsList: document.getElementById("agents-list"),
            commandForm: document.getElementById("command-form"),
            commandInput: document.getElementById("command-input"),
            commandOutput: document.getElementById("command-output"),
            logStream: document.getElementById("log-stream"),
            selfHealStatusList: document.getElementById("self-heal-status-list"),
            selfHealSuggestions: document.getElementById("self-heal-suggestions"),
            servicesList: document.getElementById("services-list"),
            lastUpdated: document.getElementById("last-updated"),
            connectionStatus: document.getElementById("connection-status"),
          };

          const logs = [
            { source: "system_agent", message: "Agent controls ready." },
            { source: "coding_agent", message: "Command endpoint ready." },
          ];
          const agentStates = {};
          let pendingApproval = null;
          const seenLogKeys = new Set();

          function setAgents(agents) {
            els.agentsList.innerHTML = "";
            if (!Array.isArray(agents) || agents.length === 0) {
              els.agentsList.innerHTML = '<li><span class="agent-meta"><span class="agent-description">Unable to load available agents.</span></span></li>';
              return;
            }
            for (const agent of agents) {
              if (!agent || !agent.name) {
                continue;
              }
              els.agentsList.insertAdjacentHTML(
                "beforeend",
                agentCardHtml(agent.name, agent.description || "Local agent available")
              );
            }
          }

          function agentCardHtml(name, description) {
            const label = agentStates[name] ? "Stop" : "Start";
            return '<li><span class="icon">' + agentIcon(name) + '</span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>' + escapeHtml(name) + '</span><span class="agent-description">' + escapeHtml(description) + '</span></span><button class="button secondary agent-toggle" type="button" data-agent="' + escapeHtml(name) + '">' + label + '</button></li>';
          }

          function escapeHtml(value) {
            return String(value)
              .replaceAll("&", "&amp;")
              .replaceAll("<", "&lt;")
              .replaceAll(">", "&gt;")
              .replaceAll('"', "&quot;")
              .replaceAll("'", "&#039;");
          }

          function agentIcon(name) {
            if (name === "system_agent") {
              return '<svg viewBox="0 0 24 24"><rect x="5" y="6" width="14" height="10" rx="2"></rect><path d="M8 20h8M12 16v4"></path></svg>';
            }
            if (name === "maintenance_agent") {
              return '<svg viewBox="0 0 24 24"><path d="M14 6l4 4-8 8H6v-4l8-8z"></path><path d="M16 4l4 4"></path></svg>';
            }
            if (name === "coding_agent") {
              return '<svg viewBox="0 0 24 24"><path d="M8 9l-4 3 4 3M16 9l4 3-4 3M14 5l-4 14"></path></svg>';
            }
            return '<svg viewBox="0 0 24 24"><path d="M12 3l7 4v6c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"></path></svg>';
          }

          function serviceDotClass(status) {
            if (status === "running") {
              return "";
            }
            if (status === "stopped") {
              return ' style="background: var(--danger); box-shadow: 0 0 14px rgba(255, 99, 112, 0.7);"';
            }
            return ' style="background: #facc15; box-shadow: 0 0 14px rgba(250, 204, 21, 0.55);"';
          }

          function serviceActionButton(service) {
            if (service.key === "ollama") {
              return '<button class="button secondary service-action" type="button" data-action="restart_ollama">Restart</button>';
            }
            if (service.key === "agentos") {
              return '<button class="button secondary service-action" type="button" data-action="restart_agentos">Restart</button>';
            }
            return '<button class="button secondary" type="button" disabled>Not installed</button>';
          }

          function renderServices(services) {
            const items = Array.isArray(services) ? services : [];
            if (items.length === 0) {
              els.servicesList.innerHTML = '<li><span class="icon">' + agentIcon("system_agent") + '</span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>No services</span><span class="agent-description">No service status returned</span></span><button class="button secondary" type="button" disabled>--</button></li>';
              return;
            }

            els.servicesList.innerHTML = items.map((service) => {
              const status = service.status || "unknown";
              return '<li><span class="icon">' + agentIcon("system_agent") + '</span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"' + serviceDotClass(status) + '></span>' + escapeHtml(service.name || service.key || "Service") + '</span><span class="agent-description">Status: ' + escapeHtml(status) + '</span></span>' + serviceActionButton(service) + '</li>';
            }).join("");
          }

          async function refreshServices() {
            try {
              const response = await fetch("/system/services", { cache: "no-store" });
              if (!response.ok) {
                throw new Error("Service request failed");
              }
              const data = await response.json();
              renderServices(data.services);
            } catch (error) {
              appendLog("system_agent", "Service status refresh failed.", "error");
            }
          }

          function appendLog(source, message, level = "info") {
            logs.push({ source, message, level, time: new Date() });
            if (logs.length > 50) {
              logs.shift();
            }
            renderLogs();
          }

          function normalizeLogLevel(entry) {
            const level = String(entry.level || "").toLowerCase();
            if (level === "warning" || String(entry.message || "").startsWith("WARNING:")) {
              return "warning";
            }
            if (level === "error" || String(entry.message || "").startsWith("ERROR:")) {
              return "error";
            }
            return "info";
          }

          function formatLogTime(entry) {
            const date = entry.time || (entry.timestamp ? new Date(entry.timestamp) : new Date());
            if (Number.isNaN(date.getTime())) {
              return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
            }
            return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
          }

          function logKey(entry) {
            return [entry.timestamp || "", entry.source || "", entry.level || "", entry.message || ""].join("|");
          }

          function renderLogs() {
            els.logStream.innerHTML = logs.map((entry) => {
              const level = normalizeLogLevel(entry);
              const key = logKey(entry);
              const isNew = !seenLogKeys.has(key);
              seenLogKeys.add(key);
              return '<div class="log-line ' + level + (isNew ? ' is-new' : '') + '"><span class="log-time">' + escapeHtml(formatLogTime(entry)) + '</span><span class="log-source"><span class="log-level">' + level.toUpperCase() + '</span>' + escapeHtml(entry.source) + '</span><span class="log-message">' + escapeHtml(entry.message) + '</span></div>';
            }).join("");
            els.logStream.scrollTop = els.logStream.scrollHeight;
          }

          function setWatcherLogs(agentLogs) {
            if (!Array.isArray(agentLogs)) {
              return;
            }
            logs.length = 0;
            for (const entry of agentLogs.slice(-50)) {
              logs.push({
                source: entry.source || "system_watcher",
                level: normalizeLogLevel(entry),
                message: entry.message || "",
                timestamp: entry.timestamp,
              });
            }
            renderLogs();
          }

          function formatSelfHealTime(value) {
            if (!value) {
              return "--";
            }
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) {
              return "--";
            }
            return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
          }

          function renderSelfHealStatus(status) {
            const running = Boolean(status && status.running);
            const state = running ? "running" : "stopped";
            const lastCheck = formatSelfHealTime(status && status.last_check);
            const suggestionCount = status && Number.isFinite(Number(status.suggestion_count)) ? Number(status.suggestion_count) : 0;
            els.selfHealStatusList.innerHTML =
              '<li><span class="icon">' + agentIcon("self_healing_agent") + '</span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>self_healing_agent</span><span class="agent-description">Status: ' + escapeHtml(state) + ' · Last check: ' + escapeHtml(lastCheck) + ' · Suggestions: ' + suggestionCount + '</span></span></li>';
          }

          function renderSelfHealSuggestions(suggestions) {
            const items = Array.isArray(suggestions) ? suggestions : [];
            if (items.length === 0) {
              els.selfHealSuggestions.innerHTML =
                '<li><span class="icon">' + agentIcon("self_healing_agent") + '</span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>System healthy</span><span class="agent-description">System healthy. No actions required.</span></span></li>';
              return;
            }

            els.selfHealSuggestions.innerHTML = items.map((suggestion) => {
              const action = suggestion.suggested_action || "";
              const actionText = action || suggestion.detail || "Review manually";
              const approveButton = action ? '<button class="button secondary self-heal-approve" type="button" data-action="' + escapeHtml(action) + '">Approve</button>' : '';
              return '<li><span class="icon">' + agentIcon("self_healing_agent") + '</span><span class="agent-meta"><span class="agent-name"><span class="agent-status-dot"></span>' + escapeHtml(suggestion.message || "Self-healing suggestion") + '</span><span class="agent-description">Recommended action: ' + escapeHtml(actionText) + '</span></span>' + approveButton + '</li>';
            }).join("");
          }

          async function refreshLogs() {
            try {
              const response = await fetch("/agent-logs", { cache: "no-store" });
              if (!response.ok) {
                throw new Error("Log request failed");
              }
              const agentLogs = await response.json();
              setWatcherLogs(agentLogs.logs);
            } catch (error) {
              appendLog("system_agent", "Log refresh failed.", "error");
            }
          }

          async function refreshSelfHealing() {
            try {
              const [statusResponse, suggestionsResponse] = await Promise.all([
                fetch("/self-heal/status", { cache: "no-store" }),
                fetch("/self-heal/suggestions", { cache: "no-store" }),
              ]);

              if (!statusResponse.ok || !suggestionsResponse.ok) {
                throw new Error("Self-heal request failed");
              }

              const status = await statusResponse.json();
              const suggestions = await suggestionsResponse.json();
              renderSelfHealStatus(status);
              renderSelfHealSuggestions(suggestions.suggestions);
            } catch (error) {
              appendLog("self_healing_agent", "Self-healing refresh failed.", "error");
            }
          }

          async function approveSelfHealAction(action) {
            appendLog("self_healing_agent", "Approving self-heal action: " + action);
            try {
              const response = await fetch("/self-heal/approve", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action }),
              });

              if (!response.ok) {
                throw new Error("Self-heal approval failed");
              }

              const result = await response.json();
              appendLog("self_healing_agent", "Self-heal action " + action + " exited with code " + result.exit_code + ".", result.exit_code === 0 ? "info" : "error");
              refreshLogs();
              refreshSelfHealing();
            } catch (error) {
              appendLog("self_healing_agent", "Self-heal approval failed.", "error");
            }
          }

          function renderCommandResult(data) {
            if (data && data.requires_approval) {
              pendingApproval = {
                action: data.action,
                args: data.args || {},
              };
              els.commandOutput.innerHTML =
                '<div><strong>Approval required</strong></div>' +
                '<div>Command: ' + escapeHtml(data.command_preview || "") + '</div>' +
                '<div>Risk: ' + escapeHtml(data.risk || "Review before running.") + '</div>' +
                '<div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;">' +
                '<button class="button secondary" type="button" data-command-action="approve">Approve</button>' +
                '<button class="button secondary" type="button" data-command-action="cancel">Cancel</button>' +
                '</div>';
              return;
            }

            pendingApproval = null;
            els.commandOutput.textContent = JSON.stringify(data, null, 2);
          }

          async function approvePendingCommand() {
            if (!pendingApproval) {
              return;
            }

            els.commandOutput.textContent = "Running approved command...";
            appendLog("command_center", "Approved action: " + pendingApproval.action);

            try {
              const response = await fetch("/command/approve", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(pendingApproval),
              });

              if (!response.ok) {
                throw new Error("Approval request failed");
              }

              const data = await response.json();
              pendingApproval = null;
              els.commandOutput.textContent = JSON.stringify(data, null, 2);
              appendLog(data.agent || "command_center", "Approved command finished with exit code " + data.exit_code + ".");
            } catch (error) {
              pendingApproval = null;
              els.commandOutput.textContent = "Approved command failed. Check server logs for details.";
              appendLog("command_center", "Approved command failed.");
            }
          }

          async function submitCommand(input) {
            const command = input.trim();
            if (!command) {
              return;
            }

            els.commandOutput.classList.add("visible");
            els.commandOutput.textContent = "Running command...";
            appendLog("coding_agent", "Command submitted: " + command);

            try {
              const response = await fetch("/command", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ input: command }),
              });

              if (!response.ok) {
                throw new Error("Command request failed");
              }

              const data = await response.json();
              renderCommandResult(data);
              appendLog(data.agent || "coding_agent", data.response || "Command completed.");
            } catch (error) {
              pendingApproval = null;
              els.commandOutput.textContent = "Command failed. Check server logs for details.";
              appendLog("coding_agent", "Command failed.");
            }
          }

          async function refreshControl() {
            try {
              const [systemResponse, agentsResponse, logsResponse] = await Promise.all([
                fetch("/system", { cache: "no-store" }),
                fetch("/agents/data", { cache: "no-store" }),
                fetch("/agent-logs", { cache: "no-store" }),
              ]);

              if (!systemResponse.ok || !agentsResponse.ok || !logsResponse.ok) {
                throw new Error("Control request failed");
              }

              const system = await systemResponse.json();
              const agents = await agentsResponse.json();
              const agentLogs = await logsResponse.json();
              const now = new Date();

              els.serverStatus.textContent = "Online";
              els.statusPill.classList.remove("offline");
              els.connectionStatus.textContent = "online";
              agentStates.system_agent = Boolean(agentLogs.status && agentLogs.status.running);
              setAgents(agents.agents);
              setWatcherLogs(agentLogs.logs);
              els.lastUpdated.textContent = "Last updated: " + now.toLocaleTimeString();
            } catch (error) {
              els.serverStatus.textContent = "Offline";
              els.statusPill.classList.add("offline");
              els.connectionStatus.textContent = "offline";
              els.lastUpdated.textContent = "Last updated: failed at " + new Date().toLocaleTimeString();
              els.agentsList.innerHTML = '<li><span class="agent-meta"><span class="agent-description">Unable to load available agents.</span></span></li>';
              appendLog("system_agent", "Control refresh failed.");
            }
          }

          els.commandForm.addEventListener("submit", (event) => {
            event.preventDefault();
            submitCommand(els.commandInput.value);
          });

          els.commandOutput.addEventListener("click", (event) => {
            const action = event.target.dataset.commandAction;
            if (action === "approve") {
              approvePendingCommand();
            }
            if (action === "cancel") {
              pendingApproval = null;
              els.commandOutput.textContent = "Command approval canceled.";
              appendLog("command_center", "Command approval canceled.");
            }
          });

          els.selfHealSuggestions.addEventListener("click", (event) => {
            const button = event.target.closest(".self-heal-approve");
            if (!button) {
              return;
            }
            approveSelfHealAction(button.dataset.action);
          });

          els.servicesList.addEventListener("click", (event) => {
            const button = event.target.closest(".service-action");
            if (!button) {
              return;
            }
            approveSelfHealAction(button.dataset.action);
          });

          els.agentsList.addEventListener("click", async (event) => {
            const button = event.target.closest(".agent-toggle");
            if (!button) {
              return;
            }
            const agentName = button.dataset.agent;
            if (agentName === "system_agent") {
              const nextAction = agentStates.system_agent ? "stop" : "start";
              button.disabled = true;
              try {
                const response = await fetch("/agents/system_watcher/" + nextAction, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                });
                if (!response.ok) {
                  throw new Error("Watcher request failed");
                }
                const status = await response.json();
                agentStates.system_agent = Boolean(status.running);
                button.textContent = agentStates.system_agent ? "Stop" : "Start";
                appendLog("system_watcher", "system_watcher " + (agentStates.system_agent ? "started" : "stopped") + ".");
              } catch (error) {
                appendLog("system_watcher", "system_watcher control request failed.");
              } finally {
                button.disabled = false;
              }
              return;
            }
            agentStates[agentName] = !agentStates[agentName];
            button.textContent = agentStates[agentName] ? "Stop" : "Start";
            appendLog("system_agent", agentName + " " + (agentStates[agentName] ? "started" : "stopped") + ".");
          });

          renderLogs();
          refreshControl();
          refreshSelfHealing();
          refreshServices();
          setInterval(refreshLogs, 3000);
          setInterval(refreshSelfHealing, 3000);
          setInterval(refreshServices, 5000);
          setInterval(refreshControl, 5000);
        </script>

      </body>
    </html>
    """

def app_sidebar(active: str) -> str:
    from apps.shared_layout import sidebar_html

    return sidebar_html(active)


def app_view_html(title: str, active: str, content: str, script: str = "") -> str:
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>""" + title + """</title>
        <style>
          :root {
            color-scheme: dark;
            --bg: #050914;
            --panel: rgba(12, 21, 37, 0.74);
            --border: rgba(125, 211, 252, 0.2);
            --border-strong: rgba(125, 211, 252, 0.42);
            --text: #eef7ff;
            --muted: #a8b7cc;
            --soft: #6f8098;
            --cyan: #00d4ff;
            --blue: #6ecbff;
            --green: #37d67a;
            --danger: #ff6370;
          }

          * { box-sizing: border-box; }

          body {
            margin: 0;
            min-height: 100vh;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
              radial-gradient(circle at 12% 8%, rgba(64, 224, 208, 0.17), transparent 31%),
              radial-gradient(circle at 88% 4%, rgba(106, 167, 255, 0.18), transparent 30%),
              linear-gradient(145deg, #050914 0%, #08111f 52%, #0d1728 100%);
            color: var(--text);
          }

          button,
          input { font: inherit; }

          .app-shell {
            display: grid;
            grid-template-columns: var(--ao-sidebar-width, 292px) minmax(0, 1fr);
            min-height: 100vh;
          }

          .sidebar {
            position: sticky;
            top: 0;
            height: 100vh;
            padding: 18px 12px;
            border-right: 1px solid rgba(110, 203, 255, 0.16);
            background:
              linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.018)),
              rgba(5, 9, 20, 0.76);
            box-shadow: 12px 0 36px rgba(0, 0, 0, 0.18);
            backdrop-filter: blur(18px);
          }

          .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 10px 18px;
            color: var(--text);
            font-size: 18px;
            font-weight: 600;
          }

          .brand-mark {
            display: inline-grid;
            place-items: center;
            width: 34px;
            height: 34px;
            border: 1px solid rgba(0, 212, 255, 0.34);
            border-radius: 10px;
            background: rgba(0, 212, 255, 0.12);
            box-shadow: 0 0 22px rgba(0, 212, 255, 0.14);
          }

          .side-nav {
            display: grid;
            gap: 5px;
          }

          .nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            min-height: 40px;
            padding: 9px 10px;
            border: 1px solid transparent;
            border-radius: 10px;
            color: var(--muted);
            text-decoration: none;
            font-size: 14px;
            font-weight: 450;
          }

          .nav-item svg {
            width: 17px;
            height: 17px;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.9;
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .nav-item.active,
          .nav-item:hover {
            border-color: rgba(0, 212, 255, 0.24);
            background: rgba(0, 212, 255, 0.09);
            color: var(--text);
          }

          .sidebar-section {
            margin-top: 14px;
            border-top: 1px solid rgba(110, 203, 255, 0.14);
            padding-top: 12px;
          }

          .sidebar-section summary {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            list-style: none;
            cursor: pointer;
            padding: 0 10px 8px;
            color: var(--soft);
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
          }

          .sidebar-section summary a {
            color: var(--blue);
            font-size: 10px;
            letter-spacing: 0;
            text-decoration: none;
            text-transform: none;
          }

          .sidebar-section summary::-webkit-details-marker { display: none; }

          .agent-links {
            display: grid;
            gap: 12px;
            max-height: 58vh;
            overflow: auto;
            padding-right: 3px;
          }

          .agent-group {
            display: grid;
            gap: 7px;
          }

          .agent-group-title {
            padding: 0 3px;
            color: var(--soft);
            font-size: 10px;
            font-weight: 850;
            letter-spacing: 0.06em;
            text-transform: uppercase;
          }

          .agent-link {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: 7px;
            align-items: center;
            min-height: 44px;
            border: 1px solid rgba(125, 211, 252, 0.16);
            border-radius: 10px;
            padding: 8px 10px;
            color: var(--muted);
            background: rgba(2, 6, 23, 0.18);
            text-decoration: none;
          }

          .agent-link:hover {
            border-color: rgba(0, 212, 255, 0.28);
            background: rgba(0, 212, 255, 0.08);
            color: var(--text);
          }

          .agent-link-icon {
            font-size: 16px;
            line-height: 1;
          }

          .agent-link-main {
            display: grid;
            gap: 2px;
            min-width: 0;
          }

          .agent-link-name {
            color: var(--text);
            font-size: 12px;
            font-weight: 700;
          }

          .agent-link-url {
            overflow: hidden;
            color: var(--soft);
            font-size: 9px;
            text-overflow: ellipsis;
            white-space: nowrap;
          }

          .agent-link-badges {
            grid-column: 1 / -1;
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
          }

          .agent-status {
            justify-self: start;
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 999px;
            padding: 2px 7px;
            color: var(--soft);
            font-size: 10px;
            font-weight: 800;
          }

          .agent-status.online {
            border-color: rgba(55, 214, 122, 0.32);
            color: var(--green);
            background: rgba(21, 128, 61, 0.12);
          }

          .agent-status.local-only,
          .agent-status.cli,
          .agent-status.no-ui {
            border-color: rgba(125, 211, 252, 0.28);
            color: var(--blue);
            background: rgba(14, 165, 233, 0.1);
          }

          .agent-status.offline,
          .agent-status.service-missing {
            border-color: rgba(255, 99, 112, 0.3);
            color: var(--danger);
            background: rgba(127, 29, 29, 0.12);
          }

          .shell {
            width: min(1240px, 100%);
            margin: 0 auto;
            padding: 22px;
            min-width: 0;
          }

          .glass {
            position: relative;
            overflow: hidden;
            border: 1px solid var(--border);
            border-radius: 17px;
            background:
              linear-gradient(180deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.025)),
              var(--panel);
            box-shadow: 0 14px 36px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.07);
            backdrop-filter: blur(18px);
          }

          .command-card,
          .logs-panel {
            margin-bottom: 14px;
            padding: 16px;
          }

          .card-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 14px;
            color: var(--muted);
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
          }

          .icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border: 1px solid rgba(125, 211, 252, 0.24);
            border-radius: 8px;
            background: rgba(96, 165, 250, 0.11);
            color: #9bdcff;
            flex: 0 0 auto;
          }

          .icon svg {
            width: 16px;
            height: 16px;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.9;
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .command-form {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 10px;
            align-items: center;
          }

          .command-input {
            width: 100%;
            min-height: 52px;
            border: 1px solid rgba(110, 203, 255, 0.2);
            border-radius: 12px;
            padding: 0 14px;
            background: rgba(2, 6, 23, 0.48);
            color: var(--text);
            outline: none;
          }

          .button {
            min-height: 44px;
            border: 1px solid rgba(0, 212, 255, 0.38);
            border-radius: 12px;
            padding: 0 16px;
            background:
              linear-gradient(135deg, rgba(0, 212, 255, 0.28), rgba(255, 79, 216, 0.18)),
              rgba(2, 6, 23, 0.52);
            color: var(--text);
            cursor: pointer;
            font-weight: 550;
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.11);
          }

          .button.secondary {
            min-height: 34px;
            padding: 0 12px;
            border-color: rgba(110, 203, 255, 0.22);
            background: rgba(2, 6, 23, 0.34);
            color: var(--muted);
            font-size: 13px;
          }

          .command-output,
          .examples {
            margin-top: 12px;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 12px;
            background: rgba(2, 6, 23, 0.36);
            color: var(--muted);
            font-size: 13px;
            line-height: 1.45;
            white-space: pre-wrap;
          }

          .log-stream {
            display: grid;
            gap: 8px;
            max-height: calc(100vh - 145px);
            overflow: auto;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 12px;
            background: rgba(2, 6, 23, 0.34);
            color: var(--muted);
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 12px;
            line-height: 1.55;
          }

          .log-line {
            display: grid;
            grid-template-columns: 96px 150px 86px 1fr;
            gap: 12px;
            align-items: baseline;
          }

          .log-time { color: var(--soft); }
          .log-source { color: var(--blue); }
          .log-level { color: var(--soft); font-weight: 700; }
          .log-line.warning .log-level,
          .log-line.warning .log-message { color: #facc15; }
          .log-line.error .log-level,
          .log-line.error .log-message { color: var(--danger); }

          @media (max-width: 860px) {
            .app-shell { grid-template-columns: 1fr; }
            .sidebar {
              position: sticky;
              top: 0;
              z-index: 9;
              display: flex;
              align-items: center;
              gap: 10px;
              height: auto;
              padding: 10px;
              overflow-x: auto;
              border-right: 0;
              border-bottom: 1px solid rgba(110, 203, 255, 0.16);
            }
            .brand { padding: 0 8px 0 0; white-space: nowrap; }
            .side-nav { display: flex; gap: 6px; }
            .nav-item { white-space: nowrap; }
            .sidebar-section {
              flex: 0 0 auto;
              margin-top: 0;
              border-top: 0;
              padding-top: 0;
            }
            .sidebar-section summary { padding: 9px 8px; }
            .agent-links { display: flex; gap: 10px; max-height: none; overflow: visible; }
            .agent-group { display: flex; align-items: stretch; gap: 6px; }
            .agent-group-title { align-self: center; white-space: nowrap; }
            .agent-link { min-width: 196px; }
          }

          @media (max-width: 520px) {
            .command-form,
            .log-line { grid-template-columns: 1fr; }
            .shell { padding: 16px; }
          }
        </style>
      </head>
      <body>
        <div class="app-shell">
          """ + app_sidebar(active) + """
          <main class="shell">
            """ + content + """
          </main>
        </div>
        """ + script + """
      </body>
    </html>
    """


@app.get("/commands", response_class=HTMLResponse)
def commands_page() -> str:
    content = """
      <section class="command-card glass" aria-label="Command workspace">
        <div class="card-header">
          <span class="icon"><svg viewBox="0 0 24 24"><path d="M4 7h16M7 7v10M17 7v10M4 17h16"></path></svg></span>
          Commands
        </div>
        <form class="command-form" id="command-form">
          <input class="command-input" id="command-input" type="text" placeholder="Type a command..." autocomplete="off">
          <button class="button" type="submit">Run</button>
        </form>
        <div class="examples" id="command-examples"><button class="button secondary" type="button" data-command="/system health">/system health</button> <button class="button secondary" type="button" data-command="/git status">/git status</button> <button class="button secondary" type="button" data-command="/git push message">/git push message</button> <button class="button secondary" type="button" data-command="/git branch feature/name">/git branch feature/name</button> <button class="button secondary" type="button" data-command="/code plan request">/code plan request</button></div>
        <div class="command-output" id="command-output" aria-live="polite">Command response will appear here.</div>
      </section>
    """
    script = """
      <script>
        const commandForm = document.getElementById("command-form");
        const commandInput = document.getElementById("command-input");
        const commandOutput = document.getElementById("command-output");
        const commandExamples = document.getElementById("command-examples");
        let pendingApproval = null;

        function escapeHtml(value) {
          return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
        }

        function renderCommandResult(data) {
          if (data && data.requires_approval) {
            pendingApproval = { action: data.action, args: data.args || {} };
            commandOutput.innerHTML =
              '<div><strong>Approval required</strong></div>' +
              '<div>Command: ' + escapeHtml(data.command_preview || "") + '</div>' +
              '<div>Risk: ' + escapeHtml(data.risk || "Review before running.") + '</div>' +
              '<div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;">' +
              '<button class="button secondary" type="button" data-command-action="approve">Approve</button>' +
              '<button class="button secondary" type="button" data-command-action="cancel">Cancel</button>' +
              '</div>';
            return;
          }
          pendingApproval = null;
          const agent = data && data.agent ? data.agent : "command_center";
          const summary = data && data.response ? data.response : "Command completed.";
          const status = data && Object.prototype.hasOwnProperty.call(data, "exit_code") ? (Number(data.exit_code) === 0 ? "success" : "failed") : "complete";
          commandOutput.innerHTML =
            '<div><strong>Agent:</strong> ' + escapeHtml(agent) + '</div>' +
            '<div><strong>Summary:</strong> ' + escapeHtml(summary) + '</div>' +
            '<div><strong>Status:</strong> ' + escapeHtml(status) + '</div>' +
            '<details style="margin-top:10px;"><summary>Details</summary><pre style="white-space:pre-wrap; margin:10px 0 0;">' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre></details>';
        }

        async function submitCommand(input) {
          const command = input.trim();
          if (!command) {
            return;
          }
          commandOutput.textContent = "Running command...";
          try {
            const response = await fetch("/command", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ input: command }),
            });
            if (!response.ok) {
              throw new Error("Command request failed");
            }
            renderCommandResult(await response.json());
          } catch (error) {
            pendingApproval = null;
            commandOutput.textContent = "Command failed.";
          }
        }

        async function approvePendingCommand() {
          if (!pendingApproval) {
            return;
          }
          commandOutput.textContent = "Running approved command...";
          try {
            const response = await fetch("/command/approve", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(pendingApproval),
            });
            if (!response.ok) {
              throw new Error("Approval request failed");
            }
            pendingApproval = null;
            commandOutput.textContent = JSON.stringify(await response.json(), null, 2);
          } catch (error) {
            pendingApproval = null;
            commandOutput.textContent = "Approved command failed.";
          }
        }

        commandExamples.addEventListener("click", (event) => {
          const button = event.target.closest("button[data-command]");
          if (!button) {
            return;
          }
          commandInput.value = button.dataset.command;
          submitCommand(button.dataset.command);
        });

        commandForm.addEventListener("submit", (event) => {
          event.preventDefault();
          submitCommand(commandInput.value);
        });

        commandOutput.addEventListener("click", (event) => {
          const action = event.target.dataset.commandAction;
          if (action === "approve") {
            approvePendingCommand();
          }
          if (action === "cancel") {
            pendingApproval = null;
            commandOutput.textContent = "Command approval canceled.";
          }
        });
      </script>
    """
    return app_view_html("AgentOS Commands", "commands", content, script)


@app.get("/ops", response_class=HTMLResponse)
def ops_cheat_sheet_page() -> str:
    chips = "".join(
        f'<button class="ops-chip{" active" if key == "all" else ""}" type="button" data-filter="{esc(key)}">{esc(label)}</button>'
        for key, label in OPS_CATEGORY_FILTERS
    )
    groups = "".join(render_ops_group(group) for group in OPS_COMMAND_GROUPS)
    content = f"""
      <style>
        @media (prefers-color-scheme: light) {{
          :root {{
            color-scheme: light;
            --bg: #f6f9fc;
            --panel: rgba(255, 255, 255, 0.82);
            --border: rgba(15, 23, 42, 0.12);
            --border-strong: rgba(14, 116, 144, 0.32);
            --text: #0f172a;
            --muted: #475569;
            --soft: #64748b;
            --cyan: #0891b2;
            --blue: #2563eb;
            --green: #15803d;
            --danger: #b91c1c;
          }}

          body {{
            background:
              radial-gradient(circle at 12% 8%, rgba(14, 165, 233, 0.12), transparent 31%),
              radial-gradient(circle at 88% 4%, rgba(37, 99, 235, 0.1), transparent 30%),
              linear-gradient(145deg, #f8fafc 0%, #eef6fb 52%, #f8fbff 100%);
          }}
        }}

        .ops-hero {{
          display: grid;
          gap: 14px;
          margin-bottom: 14px;
          padding: 20px;
        }}

        .ops-title-row {{
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
        }}

        .ops-eyebrow {{
          margin: 0 0 6px;
          color: var(--blue);
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }}

        .ops-hero h1 {{
          margin: 0;
          color: var(--text);
          font-size: 34px;
          line-height: 1.08;
          letter-spacing: 0;
        }}

        .ops-hero p {{
          max-width: 740px;
          margin: 8px 0 0;
          color: var(--muted);
          font-size: 15px;
          line-height: 1.55;
        }}

        .ops-search-wrap {{
          display: grid;
          grid-template-columns: minmax(0, 1fr);
          gap: 10px;
        }}

        .ops-search {{
          width: 100%;
          min-height: 48px;
          border: 1px solid rgba(110, 203, 255, 0.2);
          border-radius: 12px;
          padding: 0 14px;
          background: rgba(2, 6, 23, 0.36);
          color: var(--text);
          outline: none;
        }}

        .ops-search:focus {{
          border-color: rgba(0, 212, 255, 0.52);
          box-shadow: 0 0 0 3px rgba(0, 212, 255, 0.1);
        }}

        .ops-chips {{
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }}

        .ops-chip,
        .copy-button {{
          min-height: 34px;
          border: 1px solid rgba(110, 203, 255, 0.22);
          border-radius: 999px;
          padding: 0 12px;
          background: rgba(2, 6, 23, 0.32);
          color: var(--muted);
          cursor: pointer;
          font-size: 13px;
          font-weight: 650;
        }}

        .copy-button {{
          border-radius: 10px;
          min-width: 74px;
        }}

        .copy-button.copied {{
          border-color: rgba(55, 214, 122, 0.42);
          background: rgba(21, 128, 61, 0.16);
          color: var(--green);
        }}

        .ops-chip.active,
        .ops-chip:hover,
        .copy-button:hover {{
          border-color: rgba(0, 212, 255, 0.42);
          background: rgba(0, 212, 255, 0.12);
          color: var(--text);
        }}

        .ops-meta {{
          display: inline-flex;
          align-items: center;
          gap: 8px;
          align-self: flex-start;
          min-height: 34px;
          border: 1px solid rgba(55, 214, 122, 0.26);
          border-radius: 999px;
          padding: 0 12px;
          color: var(--green);
          background: rgba(21, 128, 61, 0.12);
          font-size: 13px;
          font-weight: 700;
          white-space: nowrap;
        }}

        .ops-intro {{
          display: grid;
          gap: 10px;
          margin-bottom: 16px;
          padding: 15px;
        }}

        .ops-intro h2 {{
          margin: 0;
          color: var(--text);
          font-size: 17px;
          letter-spacing: 0;
        }}

        .ops-intro-grid {{
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
        }}

        .ops-tip {{
          display: grid;
          gap: 5px;
          border: 1px solid rgba(148, 163, 184, 0.13);
          border-radius: 12px;
          padding: 10px;
          background: rgba(2, 6, 23, 0.2);
        }}

        .ops-tip strong {{
          color: var(--text);
          font-size: 13px;
        }}

        .ops-tip span {{
          color: var(--muted);
          font-size: 12px;
          line-height: 1.4;
        }}

        .ops-group {{
          margin: 18px 0 0;
        }}

        .ops-group-header {{
          display: grid;
          grid-template-columns: auto minmax(0, 1fr);
          gap: 12px;
          align-items: center;
          margin: 0 0 9px;
          padding: 0 2px;
        }}

        .ops-group-header h2 {{
          margin: 0;
          color: var(--text);
          font-size: 18px;
          letter-spacing: 0;
        }}

        .ops-group-header p {{
          margin: 0;
          color: var(--muted);
          font-size: 13px;
          line-height: 1.45;
          text-align: right;
        }}

        .ops-grid {{
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 14px;
        }}

        .ops-card {{
          display: grid;
          gap: 10px;
          min-width: 0;
          border: 1px solid var(--border);
          border-radius: 14px;
          padding: 13px;
          background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.018)),
            rgba(2, 6, 23, 0.3);
        }}

        .ops-card-top {{
          display: grid;
          grid-template-columns: auto minmax(0, 1fr);
          align-items: flex-start;
          gap: 10px;
        }}

        .ops-type-icon {{
          display: inline-grid;
          place-items: center;
          width: 32px;
          height: 32px;
          border: 1px solid rgba(125, 211, 252, 0.24);
          border-radius: 10px;
          background: rgba(96, 165, 250, 0.1);
          color: #9bdcff;
        }}

        .ops-type-icon svg {{
          width: 17px;
          height: 17px;
          fill: none;
          stroke: currentColor;
          stroke-width: 1.9;
          stroke-linecap: round;
          stroke-linejoin: round;
        }}

        .ops-card h3 {{
          margin: 0;
          color: var(--text);
          font-size: 16px;
          line-height: 1.25;
          letter-spacing: 0;
        }}

        .ops-card p {{
          margin: 5px 0 0;
          color: var(--muted);
          font-size: 13px;
          line-height: 1.45;
        }}

        .ops-badges {{
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }}

        .ops-badge {{
          display: inline-flex;
          align-items: center;
          min-height: 24px;
          border: 1px solid rgba(148, 163, 184, 0.16);
          border-radius: 999px;
          padding: 0 8px;
          color: var(--muted);
          background: rgba(2, 6, 23, 0.22);
          font-size: 11px;
          font-weight: 750;
        }}

        .ops-badge.safe {{
          border-color: rgba(55, 214, 122, 0.28);
          color: var(--green);
          background: rgba(21, 128, 61, 0.12);
        }}

        .ops-badge.git {{
          border-color: rgba(96, 165, 250, 0.32);
          color: var(--blue);
          background: rgba(37, 99, 235, 0.12);
        }}

        .ops-badge.service {{
          border-color: rgba(125, 211, 252, 0.28);
          color: var(--cyan);
          background: rgba(14, 165, 233, 0.11);
        }}

        .ops-badge.warn,
        .ops-badge.risk {{
          border-color: rgba(250, 204, 21, 0.36);
          color: #fde68a;
          background: rgba(250, 204, 21, 0.1);
        }}

        .ops-card pre {{
          margin: 0;
          min-width: 0;
          overflow-x: auto;
          border: 1px solid rgba(148, 163, 184, 0.15);
          border-radius: 12px;
          padding: 13px 14px;
          background: rgba(2, 6, 23, 0.48);
          color: #d9f7ff;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 12px;
          line-height: 1.6;
          white-space: pre;
        }}

        .ops-card-actions {{
          display: flex;
          justify-content: flex-end;
        }}

        .ops-note {{
          border-left: 3px solid rgba(250, 204, 21, 0.62);
          padding: 7px 9px;
          border-radius: 8px;
          background: rgba(250, 204, 21, 0.08);
          color: #fde68a;
          font-size: 12px;
          line-height: 1.45;
        }}

        .ops-details {{
          border-top: 1px solid rgba(148, 163, 184, 0.12);
          padding-top: 8px;
          color: var(--muted);
          font-size: 12px;
        }}

        .ops-details summary {{
          width: fit-content;
          color: var(--text);
          cursor: pointer;
          font-weight: 700;
        }}

        .ops-details dl {{
          display: grid;
          gap: 8px;
          margin: 10px 0 0;
        }}

        .ops-details dl div {{
          display: grid;
          gap: 3px;
        }}

        .ops-details dt {{
          color: var(--soft);
          font-size: 11px;
          font-weight: 800;
          text-transform: uppercase;
        }}

        .ops-details dd {{
          margin: 0;
          color: var(--muted);
          line-height: 1.45;
        }}

        .ops-empty {{
          display: none;
          margin-top: 18px;
          padding: 16px;
          color: var(--muted);
          text-align: center;
        }}

        @media (prefers-color-scheme: light) {{
          .ops-search,
          .ops-chip,
          .copy-button,
          .ops-tip,
          .ops-badge,
          .ops-card,
          .ops-card pre {{
            background: rgba(255, 255, 255, 0.72);
          }}

          .ops-card pre {{
            color: #0f172a;
          }}

          .ops-note {{
            color: #854d0e;
            background: rgba(250, 204, 21, 0.16);
          }}

          .ops-badge.warn,
          .ops-badge.risk {{
            color: #854d0e;
          }}
        }}

        @media (max-width: 920px) {{
          .ops-grid {{ grid-template-columns: 1fr; }}
          .ops-intro-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
          .ops-group-header {{
            display: grid;
            align-items: start;
          }}
          .ops-group-header p {{ text-align: left; }}
        }}

        @media (max-width: 560px) {{
          .ops-hero {{ padding: 16px; }}
          .ops-title-row {{ display: grid; }}
          .ops-hero h1 {{ font-size: 28px; }}
          .ops-intro-grid {{ grid-template-columns: 1fr; }}
          .ops-card-actions {{ justify-content: flex-start; }}
        }}
      </style>

      <section class="ops-hero glass" aria-label="Ops cheat sheet header">
        <div class="ops-title-row">
          <div>
            <div class="ops-eyebrow">Runbook</div>
            <h1>Ops Cheat Sheet</h1>
            <p>Quick-reference commands for services, agents, Git, and troubleshooting.</p>
          </div>
          <div class="ops-meta" id="ops-count">0 commands</div>
        </div>
        <div class="ops-search-wrap">
          <input class="ops-search" id="ops-search" type="search" placeholder="Filter commands, paths, services, or notes..." autocomplete="off">
          <div class="ops-chips" aria-label="Command categories">
            {chips}
          </div>
        </div>
      </section>

      <section class="ops-intro glass" aria-label="How to use this page">
        <h2>How to use this page</h2>
        <div class="ops-intro-grid">
          <div class="ops-tip"><strong>Search</strong><span>Filters commands by title, path, category, notes, and command text.</span></div>
          <div class="ops-tip"><strong>Category chips</strong><span>Narrow the page to services, logs, Git, agents, FiveM, or recovery.</span></div>
          <div class="ops-tip"><strong>Copy</strong><span>Copies the command directly to your clipboard without selecting visible text.</span></div>
          <div class="ops-tip"><strong>Reference only</strong><span>Command cards are safe references. Nothing runs from this page automatically.</span></div>
        </div>
      </section>

      <div id="ops-content">
        {groups}
      </div>
      <section class="ops-empty glass" id="ops-empty">No commands match this filter.</section>
    """
    script = """
      <script>
        const searchInput = document.getElementById("ops-search");
        const chips = Array.from(document.querySelectorAll(".ops-chip"));
        const cards = Array.from(document.querySelectorAll(".ops-card"));
        const groups = Array.from(document.querySelectorAll("[data-group]"));
        const emptyState = document.getElementById("ops-empty");
        const count = document.getElementById("ops-count");
        let activeFilter = "all";

        function matchesFilter(card) {
          if (activeFilter === "all") {
            return true;
          }
          return String(card.dataset.tags || "").split(" ").includes(activeFilter);
        }

        function matchesSearch(card) {
          const query = searchInput.value.trim().toLowerCase();
          if (!query) {
            return true;
          }
          return String(card.dataset.search || "").includes(query);
        }

        function applyOpsFilter() {
          let visibleCount = 0;
          cards.forEach((card) => {
            const visible = matchesFilter(card) && matchesSearch(card);
            card.hidden = !visible;
            if (visible) {
              visibleCount += 1;
            }
          });
          groups.forEach((group) => {
            const hasVisibleCard = Array.from(group.querySelectorAll(".ops-card")).some((card) => !card.hidden);
            group.hidden = !hasVisibleCard;
          });
          emptyState.style.display = visibleCount === 0 ? "block" : "none";
          count.textContent = visibleCount + (visibleCount === 1 ? " command" : " commands");
        }

        chips.forEach((chip) => {
          chip.addEventListener("click", () => {
            activeFilter = chip.dataset.filter || "all";
            chips.forEach((item) => item.classList.toggle("active", item === chip));
            applyOpsFilter();
          });
        });

        searchInput.addEventListener("input", applyOpsFilter);

        function fallbackCopyText(command) {
          const textarea = document.createElement("textarea");
          textarea.value = command;
          textarea.setAttribute("readonly", "");
          textarea.style.position = "fixed";
          textarea.style.top = "-1000px";
          textarea.style.left = "-1000px";
          textarea.style.width = "1px";
          textarea.style.height = "1px";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.focus();
          textarea.select();
          let copied = false;
          try {
            copied = document.execCommand("copy");
          } finally {
            document.body.removeChild(textarea);
          }
          if (!copied) {
            throw new Error("Fallback copy failed");
          }
        }

        async function copyCommand(button, command) {
          const originalText = button.textContent;
          try {
            if (navigator.clipboard && window.isSecureContext) {
              try {
                await navigator.clipboard.writeText(command);
              } catch (error) {
                fallbackCopyText(command);
              }
            } else {
              fallbackCopyText(command);
            }
            button.textContent = "Copied!";
            button.classList.add("copied");
            setTimeout(() => {
              button.textContent = originalText || "Copy";
              button.classList.remove("copied");
            }, 1400);
          } catch (error) {
            button.textContent = "Copy failed";
            setTimeout(() => {
              button.textContent = originalText || "Copy";
            }, 1600);
          }
        }

        document.addEventListener("click", (event) => {
          const button = event.target.closest(".copy-button");
          if (!button) {
            return;
          }
          const card = button.closest(".ops-card");
          const code = card ? card.querySelector("code") : null;
          const command = code ? code.textContent : "";
          if (!command) {
            return;
          }
          copyCommand(button, command);
        });

        applyOpsFilter();
      </script>
    """
    return app_view_html("Ops Cheat Sheet", "ops", content, script)


@app.get("/logs", response_class=HTMLResponse)
def logs_page() -> str:
    content = """
      <section class="logs-panel glass" aria-label="System logs">
        <div class="card-header">
          <span class="icon"><svg viewBox="0 0 24 24"><path d="M5 5h14v14H5z"></path><path d="M8 9h8M8 13h8M8 17h5"></path></svg></span>
          Logs
        </div>
        <div class="log-stream" id="log-stream" role="log" aria-live="polite"></div>
      </section>
    """
    script = """
      <script>
        const logStream = document.getElementById("log-stream");

        function escapeHtml(value) {
          return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
        }

        function normalizeLogLevel(entry) {
          const level = String(entry.level || "").toLowerCase();
          if (level === "warning" || String(entry.message || "").startsWith("WARNING:")) {
            return "warning";
          }
          if (level === "error" || String(entry.message || "").startsWith("ERROR:")) {
            return "error";
          }
          return "info";
        }

        function formatLogTime(value) {
          const date = value ? new Date(value) : new Date();
          if (Number.isNaN(date.getTime())) {
            return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
          }
          return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        }

        function renderLogs(logs) {
          const entries = Array.isArray(logs) ? logs.slice(-50) : [];
          if (entries.length === 0) {
            logStream.innerHTML = '<div class="log-line"><span class="log-time">--</span><span class="log-source">system</span><span class="log-level">INFO</span><span class="log-message">No logs available.</span></div>';
            return;
          }
          logStream.innerHTML = entries.map((entry) => {
            const level = normalizeLogLevel(entry);
            return '<div class="log-line ' + level + '"><span class="log-time">' + escapeHtml(formatLogTime(entry.timestamp)) + '</span><span class="log-source">' + escapeHtml(entry.source || "agent") + '</span><span class="log-level">' + level.toUpperCase() + '</span><span class="log-message">' + escapeHtml(entry.message || "") + '</span></div>';
          }).join("");
          logStream.scrollTop = logStream.scrollHeight;
        }

        async function refreshLogs() {
          try {
            const response = await fetch("/agent-logs?limit=50", { cache: "no-store" });
            if (!response.ok) {
              throw new Error("Log request failed");
            }
            const data = await response.json();
            renderLogs(data.logs);
          } catch (error) {
            renderLogs([{ source: "logs", level: "error", message: "Log refresh failed.", timestamp: new Date().toISOString() }]);
          }
        }

        refreshLogs();
        setInterval(refreshLogs, 3000);
      </script>
    """
    return app_view_html("AgentOS Logs", "logs", content, script)


@app.get("/settings", response_class=HTMLResponse)
def settings_page() -> str:
    content = """
      <section class="command-card glass" aria-label="Settings">
        <div class="card-header">
          <span class="icon"><svg viewBox="0 0 24 24"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"></path><path d="M4 12h2M18 12h2M12 4v2M12 18v2"></path></svg></span>
          Settings
        </div>
        <div class="command-output">Settings coming soon

- notification settings
- agent permissions
- service thresholds
- FiveM server path
- theme preferences</div>
      </section>
    """
    return app_view_html("AgentOS Settings", "settings", content)


@app.get("/agents", response_class=HTMLResponse)
def agents_page() -> str:
    agents = agent_registry_snapshot()
    cards = []
    for agent in agents:
        target = agent.get("url") or agent.get("path") or "No path"
        action = agent.get("suggested_action", "")
        open_link = ""
        if agent.get("url"):
            target_attrs = ' target="_blank" rel="noopener noreferrer"' if str(agent["url"]).startswith(("http://", "https://")) else ""
            open_link = f'<a class="button secondary" href="{esc(agent["url"])}"{target_attrs}>Open</a>'
        cards.append(
            f"""
            <article class="registry-card glass">
              <div class="registry-card-top">
                <span class="registry-icon">{esc(agent.get("icon", ""))}</span>
                <div>
                  <h2>{esc(agent.get("display_name", ""))}</h2>
                  <p>{esc(agent.get("description", ""))}</p>
                </div>
                <div class="registry-badges">{render_agent_badges(agent)}</div>
              </div>
              <dl class="registry-details">
                <div><dt>Role</dt><dd>{esc(agent.get("type", ""))}</dd></div>
                <div><dt>Status</dt><dd>{esc(agent.get("status", ""))}</dd></div>
                <div><dt>Service</dt><dd>{esc(agent.get("service_name") or "no service")}</dd></div>
                <div><dt>Path / URL</dt><dd>{esc(target)}</dd></div>
                <div><dt>Suggested action</dt><dd>{esc(action)}</dd></div>
              </dl>
              <div class="registry-actions">{open_link}</div>
            </article>
            """
        )
    content = f"""
      <style>
        .registry-header {{
          display: flex;
          align-items: end;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 16px;
          padding: 18px;
        }}

        .registry-header h1 {{
          margin: 0;
          color: var(--text);
          font-size: 30px;
          letter-spacing: 0;
        }}

        .registry-header p {{
          max-width: 720px;
          margin: 7px 0 0;
          color: var(--muted);
          font-size: 14px;
          line-height: 1.5;
        }}

        .registry-count {{
          flex: 0 0 auto;
          border: 1px solid rgba(55, 214, 122, 0.26);
          border-radius: 999px;
          padding: 7px 11px;
          color: var(--green);
          background: rgba(21, 128, 61, 0.12);
          font-size: 12px;
          font-weight: 800;
        }}

        .registry-grid {{
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 14px;
        }}

        .registry-card {{
          display: grid;
          gap: 12px;
          padding: 15px;
        }}

        .registry-card-top {{
          display: grid;
          grid-template-columns: auto minmax(0, 1fr);
          gap: 10px;
          align-items: start;
        }}

        .registry-icon {{
          display: inline-grid;
          place-items: center;
          width: 34px;
          height: 34px;
          border: 1px solid rgba(125, 211, 252, 0.22);
          border-radius: 10px;
          background: rgba(96, 165, 250, 0.1);
        }}

        .registry-card h2 {{
          margin: 0;
          color: var(--text);
          font-size: 17px;
          letter-spacing: 0;
        }}

        .registry-card p {{
          margin: 5px 0 0;
          color: var(--muted);
          font-size: 13px;
          line-height: 1.45;
        }}

        .registry-badges {{
          grid-column: 1 / -1;
          display: flex;
          flex-wrap: wrap;
          gap: 5px;
        }}

        .registry-details {{
          display: grid;
          gap: 7px;
          margin: 0;
          color: var(--muted);
          font-size: 12px;
        }}

        .registry-details div {{
          display: grid;
          grid-template-columns: 110px minmax(0, 1fr);
          gap: 8px;
        }}

        .registry-details dt {{
          color: var(--soft);
          font-weight: 800;
          text-transform: uppercase;
        }}

        .registry-details dd {{
          min-width: 0;
          margin: 0;
          overflow-wrap: anywhere;
        }}

        .registry-actions {{
          display: flex;
          justify-content: flex-end;
        }}

        @media (max-width: 900px) {{
          .registry-grid {{ grid-template-columns: 1fr; }}
          .registry-header {{ display: grid; align-items: start; }}
        }}

        @media (max-width: 520px) {{
          .registry-details div {{ grid-template-columns: 1fr; }}
          .registry-actions {{ justify-content: flex-start; }}
        }}
      </style>
      <section class="registry-header glass">
        <div>
          <h1>Agents</h1>
          <p>All known AgentOS dashboards, workers, CLIs, bots, services, and planned tools. Inactive entries are inventory, not failures.</p>
        </div>
        <div class="registry-count">{len(agents)} entries</div>
      </section>
      <section class="registry-grid" aria-label="Agent registry">
        {"".join(cards)}
      </section>
    """
    return app_view_html("AgentOS Agents", "agents", content)


def _response_body_text(response: HTMLResponse) -> str:
    return response.body.decode("utf-8") if isinstance(response.body, bytes) else str(response.body)


@app.get("/planner", response_class=HTMLResponse)
def planner_page() -> str:
    from apps.planner_agent import app as planner_app

    return _response_body_text(planner_app.dashboard())


@app.get("/tasks/{task_id}/view", response_class=HTMLResponse)
def planner_task_page(task_id: str) -> str:
    from apps.planner_agent import app as planner_app

    return _response_body_text(planner_app.task_detail(task_id))


@app.post("/tasks")
async def planner_create_task(request: Request) -> dict:
    from apps.planner_agent import app as planner_app
    from apps.planner_agent.models import TaskCreate

    return planner_app.create_task(TaskCreate(**await request.json())).dict()


@app.post("/uploads/start")
async def planner_upload_start(request: Request) -> dict:
    from apps.planner_agent import app as planner_app
    from apps.planner_agent.models import UploadStartRequest

    return planner_app.start_upload(UploadStartRequest(**await request.json()))


@app.put("/uploads/{upload_id}/files")
async def planner_upload_file(upload_id: str, request: Request, x_relative_path: str | None = Header(default=None)) -> dict:
    from apps.planner_agent import app as planner_app

    return await planner_app.upload_file(upload_id, request, x_relative_path)


@app.post("/uploads/{upload_id}/complete")
async def planner_upload_complete(upload_id: str, request: Request) -> dict:
    from apps.planner_agent import app as planner_app
    from apps.planner_agent.models import UploadCompleteRequest

    return planner_app.complete_upload(upload_id, UploadCompleteRequest(**await request.json())).dict()


@app.post("/tasks/{task_id}/generate-fix-plan")
def planner_generate_fix_plan(task_id: str) -> dict:
    from apps.planner_agent import app as planner_app

    return planner_app.generate_fix_plan(task_id)


@app.post("/tasks/{task_id}/approve")
async def planner_approve_task(task_id: str, request: Request) -> dict:
    from apps.planner_agent import app as planner_app
    from apps.planner_agent.models import ApprovalRequest

    body = await request.json()
    return planner_app.approve_task(task_id, ApprovalRequest(**body))


@app.post("/tasks/{task_id}/reject")
async def planner_reject_task(task_id: str, request: Request) -> dict:
    from apps.planner_agent import app as planner_app
    from apps.planner_agent.models import ApprovalRequest

    body = await request.json()
    return planner_app.reject_task(task_id, ApprovalRequest(**body))


@app.post("/tasks/{task_id}/apply")
def planner_apply_task(task_id: str):
    from apps.planner_agent import app as planner_app

    return planner_app.apply_task_to_staging(task_id).dict()


@app.post("/tasks/{task_id}/send-to-coding-agent")
def planner_send_to_coding(task_id: str) -> dict:
    from apps.planner_agent import app as planner_app

    result = planner_app.send_task_to_coding_agent(task_id)
    if isinstance(result, dict) and str(result.get("staging_preview_url", "")).startswith("/"):
        result["staging_preview_url"] = result["staging_preview_url"]
    return result


@app.get("/reports/{task_id}/view")
def planner_report_view(task_id: str):
    from apps.planner_agent import app as planner_app

    return planner_app.view_report(task_id)


@app.get("/coding", response_class=HTMLResponse)
def coding_page() -> str:
    from apps.coding_agent import app as coding_app

    return _response_body_text(coding_app.home())


@app.get("/reports/daily", response_class=HTMLResponse)
def coding_daily_digest_page() -> str:
    from apps.coding_agent import app as coding_app

    return _response_body_text(coding_app.daily_digest())


@app.get("/review/{task_id}", response_class=HTMLResponse)
def coding_review_page(task_id: str) -> str:
    from apps.coding_agent import app as coding_app

    return _response_body_text(coding_app.review_page(task_id))


@app.get("/reviews", response_class=HTMLResponse)
def reviews_index_page() -> str:
    content = """
      <section class="command-card glass">
        <div class="card-header">Reviews</div>
        <p>Open a specific review from a staging preview or the daily digest.</p>
        <p><a class="button secondary" href="/reports/daily">Open Daily Digest</a></p>
      </section>
    """
    return app_view_html("Reviews", "reviews", content)


@app.get("/staging/{task_id}", response_class=HTMLResponse)
def coding_staging_page(task_id: str) -> str:
    from apps.coding_agent import app as coding_app

    return _response_body_text(coding_app.staging_preview(task_id))


@app.get("/staging", response_class=HTMLResponse)
def staging_index_page() -> str:
    content = """
      <section class="command-card glass">
        <div class="card-header">Staging</div>
        <p>Open a specific staging preview from Coding Agent output or the daily digest.</p>
      </section>
    """
    return app_view_html("Staging", "staging", content)


@app.get("/upload", response_class=HTMLResponse)
def upload_page() -> str:
    content = """
      <section class="upload-card">
        <div class="upload-head">
          <div>
            <h2>Upload Script Pipeline</h2>
            <p>Drop a ZIP file or script folder here. AgentOS will plan, stage, and review it without touching live FiveM resources.</p>
          </div>
          <span class="safety-pill">Staging only</span>
        </div>
        <form id="uploadForm" class="upload-form">
          <div id="dropZone" class="drop-zone" tabindex="0">
            <div class="drop-icon">+</div>
            <strong>Drag files or ZIPs here</strong>
            <span>Folders work through the folder selector in supported browsers.</span>
          </div>
          <div class="picker-row">
            <label class="picker-button">Select files<input id="fileInput" name="files" type="file" multiple accept=".zip,.lua,.js,.json,.cfg,.txt,.md,.html,.css"></label>
            <label class="picker-button">Select folder<input id="folderInput" name="files" type="file" multiple webkitdirectory directory></label>
            <button id="uploadButton" class="primary-button" type="submit">Upload and run pipeline</button>
          </div>
          <div id="fileList" class="file-list">No files selected.</div>
        </form>
      </section>
      <section class="progress-card">
        <div class="step" data-step="uploaded"><span></span><div><strong>Uploaded</strong><p>Files saved under incoming.</p></div></div>
        <div class="step" data-step="planning"><span></span><div><strong>Planning</strong><p>Planner Agent analyzes the script.</p></div></div>
        <div class="step" data-step="coding"><span></span><div><strong>Coding</strong><p>Coding Agent creates staged changes only.</p></div></div>
        <div class="step" data-step="reviewing"><span></span><div><strong>Review</strong><p>Human-readable review is generated.</p></div></div>
        <div class="step" data-step="done"><span></span><div><strong>Done</strong><p>Plan, staging, and review links are ready.</p></div></div>
      </section>
      <section id="resultCard" class="result-card hidden"></section>
    """
    return render_layout("Upload Pipeline", "upload", content, extra_css=_upload_page_css(), script=_upload_page_script(), subtitle="Planner to Coding to Review")


@app.post("/upload")
async def upload_pipeline(request: Request) -> dict[str, Any]:
    upload_id = f"upload-{uuid4().hex[:12]}"
    tracker = _upload_tracker(upload_id, "uploaded")
    incoming_path = _safe_incoming_upload_path(upload_id, create=True)
    try:
        saved_files = await _save_upload_form(request, incoming_path)
        extracted_files = _extract_upload_zips(incoming_path)
    except ValueError as error:
        tracker["status"] = "failed"
        tracker["error"] = str(error)
        tracker.setdefault("timestamps", {})["failed"] = _utc_now()
        _save_upload_tracker(tracker)
        raise HTTPException(status_code=400, detail=str(error)) from error
    tracker["files"] = saved_files
    tracker["extracted_files"] = extracted_files
    tracker["incoming_path"] = str(incoming_path)
    _save_upload_tracker(tracker)

    try:
        _set_upload_status(tracker, "planning")
        from apps.planner_agent import app as planner_app
        from apps.planner_agent.models import TaskCreate

        prompt = f"Analyze uploaded script folder {incoming_path.name}, create a QBCore compatibility plan, and keep all changes staged only."
        planner_result = planner_app.create_task(
            TaskCreate(
                prompt=prompt,
                title=f"Upload {incoming_path.name}",
                description="Analyze uploaded script and prepare a safe staged QBCore conversion.",
                script_path=str(incoming_path),
            )
        )
        tracker["planner_task_id"] = planner_result.task_id
        tracker["plan_url"] = f"/tasks/{planner_result.task_id}/view"
        _save_upload_tracker(tracker)

        _set_upload_status(tracker, "coding")
        from apps.coding_agent import app as coding_app
        from apps.coding_agent.app import TaskRequest

        plan = planner_result.plan or {}
        coding_result = coding_app.create_task(
            TaskRequest(
                prompt=_upload_coding_prompt(planner_result.task_id, plan),
                script_path=str(incoming_path),
                source_task_id=planner_result.task_id,
                planner_json=planner_result.integration_analysis or plan.get("integration_analysis", {}),
                mapping_rules=plan.get("mapping_rules", {}),
            )
        )
        coding_task_id = str(coding_result.get("task_id", ""))
        tracker["coding_task_id"] = coding_task_id
        tracker["staging_url"] = coding_result.get("staging_preview_url") or f"/staging/{coding_task_id}"
        _save_upload_tracker(tracker)

        _set_upload_status(tracker, "reviewing")
        tracker["review_url"] = coding_result.get("review_url") or f"/review/{coding_task_id}"
        tracker["review_created"] = bool(coding_result.get("review_report"))
        _set_upload_status(tracker, "done")
        return tracker
    except Exception as error:
        tracker["status"] = "failed"
        tracker["error"] = str(error)
        tracker.setdefault("timestamps", {})["failed"] = _utc_now()
        _save_upload_tracker(tracker)
        raise


@app.get("/upload/status/{task_id}")
def upload_pipeline_status(task_id: str) -> dict[str, Any]:
    try:
        path = _upload_tracker_path(task_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not path.is_file():
        return {"task_id": task_id, "status": "missing", "message": "No upload pipeline task was found."}
    return json.loads(path.read_text(encoding="utf-8"))


def _upload_page_css() -> str:
    return """
      .upload-card,.progress-card,.result-card{
        border:1px solid var(--ao-border);
        border-radius:12px;
        background:var(--ao-panel);
        box-shadow:0 18px 42px rgba(0,0,0,.22);
        margin-bottom:18px;
        overflow:hidden;
      }
      .upload-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:20px;border-bottom:1px solid var(--ao-border)}
      .upload-head h2{margin:0 0 6px;font-size:20px}
      .upload-head p{margin:0;color:var(--ao-muted);line-height:1.5}
      .safety-pill{white-space:nowrap;border:1px solid rgba(94,234,212,.35);border-radius:999px;color:#5eead4;background:rgba(20,184,166,.1);padding:6px 10px;font-size:12px;font-weight:800}
      .upload-form{padding:18px}
      .drop-zone{min-height:220px;border:2px dashed rgba(125,211,252,.35);border-radius:12px;background:rgba(5,12,24,.5);display:grid;place-items:center;text-align:center;gap:8px;padding:24px;color:var(--ao-muted);cursor:pointer;transition:border-color .16s,background .16s}
      .drop-zone strong{display:block;color:var(--ao-text);font-size:19px}
      .drop-zone.dragging{border-color:#5eead4;background:rgba(20,184,166,.12)}
      .drop-icon{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;border:1px solid rgba(125,211,252,.35);color:#9fdcff;font-size:26px;font-weight:300;margin:auto}
      .picker-row{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px;align-items:center}
      .picker-button,.primary-button,.result-card a{display:inline-flex;align-items:center;min-height:38px;border-radius:8px;border:1px solid rgba(125,211,252,.28);background:#10243a;color:#edf5ff;text-decoration:none;padding:8px 12px;font-weight:800;cursor:pointer}
      .picker-button input{display:none}
      .primary-button{background:#1d4ed8;border-color:#60a5fa}
      .primary-button:disabled{opacity:.55;cursor:not-allowed}
      .file-list{margin-top:14px;color:var(--ao-muted);line-height:1.55;overflow-wrap:anywhere}
      .progress-card{padding:16px;display:grid;gap:10px}
      .step{display:flex;gap:12px;align-items:flex-start;border:1px solid rgba(125,211,252,.14);border-radius:10px;padding:12px;background:rgba(5,12,24,.35)}
      .step span{width:24px;height:24px;border-radius:50%;border:1px solid rgba(125,211,252,.35);display:grid;place-items:center;color:var(--ao-muted);flex:0 0 auto}
      .step span::after{content:"";width:8px;height:8px;border-radius:50%;background:rgba(125,211,252,.35)}
      .step p{margin:3px 0 0;color:var(--ao-muted)}
      .step.done span{background:rgba(20,184,166,.16);border-color:rgba(94,234,212,.45);color:#5eead4}
      .step.done span::after{content:"✓";width:auto;height:auto;background:transparent;font-size:13px;font-weight:900}
      .step.active span{border-color:#fbbf24}
      .step.active span::after{background:#fbbf24}
      .step.failed span{border-color:#fb7185}
      .step.failed span::after{background:#fb7185}
      .result-card{padding:18px}
      .result-card h2{margin:0 0 8px}
      .result-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
      .hidden{display:none}
      @media (max-width: 700px){.upload-head{display:block}.safety-pill{display:inline-flex;margin-top:12px}.picker-row>*{width:100%;justify-content:center}}
    """


def _upload_page_script() -> str:
    return """
      <script>
        const dropZone = document.getElementById("dropZone");
        const fileInput = document.getElementById("fileInput");
        const folderInput = document.getElementById("folderInput");
        const uploadForm = document.getElementById("uploadForm");
        const fileList = document.getElementById("fileList");
        const uploadButton = document.getElementById("uploadButton");
        const resultCard = document.getElementById("resultCard");
        let selectedFiles = [];

        function setFiles(files) {
          selectedFiles = Array.from(files || []);
          if (!selectedFiles.length) {
            fileList.textContent = "No files selected.";
            return;
          }
          const preview = selectedFiles.slice(0, 8).map(file => file.webkitRelativePath || file.name).join(", ");
          const more = selectedFiles.length > 8 ? ` and ${selectedFiles.length - 8} more` : "";
          fileList.textContent = `${selectedFiles.length} file(s): ${preview}${more}`;
        }

        function setProgress(status) {
          const order = ["uploaded", "planning", "coding", "reviewing", "done"];
          const index = order.indexOf(status);
          document.querySelectorAll(".step").forEach(step => {
            const stepIndex = order.indexOf(step.dataset.step);
            step.classList.remove("done", "active", "failed");
            if (status === "failed") {
              step.classList.add("failed");
            } else if (stepIndex < index || status === "done") {
              step.classList.add("done");
            } else if (stepIndex === index) {
              step.classList.add("active");
            }
          });
        }

        dropZone.addEventListener("click", () => fileInput.click());
        fileInput.addEventListener("change", event => setFiles(event.target.files));
        folderInput.addEventListener("change", event => setFiles(event.target.files));
        dropZone.addEventListener("dragover", event => { event.preventDefault(); dropZone.classList.add("dragging"); });
        dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
        dropZone.addEventListener("drop", event => {
          event.preventDefault();
          dropZone.classList.remove("dragging");
          setFiles(event.dataTransfer.files);
        });

        uploadForm.addEventListener("submit", async event => {
          event.preventDefault();
          if (!selectedFiles.length) {
            fileList.textContent = "Choose a ZIP, files, or folder before uploading.";
            return;
          }
          uploadButton.disabled = true;
          resultCard.classList.add("hidden");
          setProgress("uploaded");
          const form = new FormData();
          selectedFiles.forEach(file => form.append("files", file, file.webkitRelativePath || file.name));
          try {
            setProgress("planning");
            const response = await fetch("/upload", { method: "POST", body: form });
            const body = await response.json();
            if (!response.ok) throw new Error(body.detail || body.error || "Upload pipeline failed.");
            setProgress("done");
            resultCard.classList.remove("hidden");
            resultCard.innerHTML = `
              <h2>Pipeline Complete</h2>
              <p>${body.files?.length || selectedFiles.length} uploaded file(s) were processed safely. Live FiveM resources were not modified.</p>
              <div class="result-actions">
                <a href="${body.plan_url || "#"}">View Plan</a>
                <a href="${body.staging_url || "#"}">View Staging</a>
                <a href="${body.review_url || "#"}">View Review</a>
              </div>
            `;
          } catch (error) {
            setProgress("failed");
            resultCard.classList.remove("hidden");
            resultCard.innerHTML = `<h2>Pipeline Stopped</h2><p>${String(error.message || error)}</p>`;
          } finally {
            uploadButton.disabled = false;
          }
        });
      </script>
    """


async def _save_upload_form(request: Request, destination: Path) -> list[str]:
    form = await request.form()
    saved: list[str] = []
    for _field, value in form.multi_items():
        filename = getattr(value, "filename", None)
        read = getattr(value, "read", None)
        if not filename or not callable(read):
            continue
        relative_path = _safe_upload_relative_path(str(filename))
        target = (destination / relative_path).resolve()
        if destination.resolve() not in target.parents:
            raise ValueError("Upload path escaped incoming folder.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(await read())
        saved.append(target.relative_to(destination).as_posix())
    if not saved:
        raise ValueError("No upload files were received.")
    return saved


def _safe_upload_relative_path(value: str) -> Path:
    clean = value.replace("\\", "/").lstrip("/")
    parts = [part for part in clean.split("/") if part and part not in {".", ".."}]
    if not parts:
        raise ValueError("Invalid upload filename.")
    return Path(*parts)


def _safe_incoming_upload_path(task_id: str, create: bool = False) -> Path:
    if not task_id.startswith("upload-") or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in task_id):
        raise ValueError("Invalid upload task id.")
    incoming_root = (BASE_DIR / "incoming").resolve()
    path = (incoming_root / task_id).resolve()
    if incoming_root not in path.parents:
        raise ValueError("Invalid incoming upload path.")
    if create:
        path.mkdir(parents=True, exist_ok=False)
    return path


def _extract_upload_zips(destination: Path) -> list[str]:
    extracted: list[str] = []
    for archive in destination.rglob("*.zip"):
        extract_root = destination / archive.stem
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zip_file:
            for member in zip_file.infolist():
                member_path = _safe_upload_relative_path(member.filename)
                target = (extract_root / member_path).resolve()
                if extract_root.resolve() not in target.parents and target != extract_root.resolve():
                    continue
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                extracted.append(target.relative_to(destination).as_posix())
    return extracted


def _upload_tracker(task_id: str, status: str) -> dict[str, Any]:
    return {"task_id": task_id, "status": status, "timestamps": {status: _utc_now()}}


def _upload_tracker_path(task_id: str) -> Path:
    if not task_id.startswith("upload-") or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in task_id):
        raise ValueError("Invalid upload task id.")
    root = (BASE_DIR / "reports" / "upload-pipeline").resolve()
    path = (root / f"{task_id}.json").resolve()
    if root != path.parent:
        raise ValueError("Invalid upload tracker path.")
    return path


def _save_upload_tracker(tracker: dict[str, Any]) -> None:
    path = _upload_tracker_path(str(tracker["task_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tracker, indent=2, sort_keys=True), encoding="utf-8")


def _set_upload_status(tracker: dict[str, Any], status: str) -> None:
    tracker["status"] = status
    tracker.setdefault("timestamps", {})[status] = _utc_now()
    _save_upload_tracker(tracker)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _upload_coding_prompt(planner_task_id: str, plan: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Use Planner Agent task {planner_task_id} to generate staged compatibility changes only.",
            "Do not modify live FiveM resources, do not run SQL, do not restart services, and do not push to Git.",
            "",
            "Planner JSON:",
            json.dumps(plan.get("integration_analysis", {}), indent=2, sort_keys=True),
            "",
            "Patch plan:",
            "\n".join(f"- {item}" for item in plan.get("patch_plan_json", [])),
        ]
    )


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "ollama_required": False,
    }


@app.get("/system")
def system() -> dict:
    return controller.system_agent.stats()


@app.get("/system/services")
def system_services() -> dict:
    return {
        "services": [
            {"name": "Ollama", "key": "ollama", "status": service_status("ollama")},
            {"name": "AgentOS", "key": "agentos", "status": service_status("agentos")},
            {"name": "FiveM", "key": "fivem", "status": "stopped"},
        ]
    }


@app.get("/agents/data")
def agents_data() -> dict:
    return {
        "agents": controller.list_agents(),
        "registry": agent_registry_snapshot(),
        "intents": ["system", "maintenance", "code", "self_heal", "chat"],
    }


@app.get("/agent-logs")
def agent_logs(limit: int = 100) -> dict:
    logs = system_watcher.recent_logs(limit=limit) + self_healing_agent.recent_logs(limit=limit)
    logs.sort(key=lambda entry: entry.get("timestamp", ""))
    return {
        "logs": logs[-max(1, min(limit, 100)):],
        "status": system_watcher.status(),
    }


@app.get("/agents/system_watcher/status")
def system_watcher_status() -> dict:
    return system_watcher.status()


@app.post("/agents/system_watcher/start")
async def start_system_watcher() -> dict:
    return await system_watcher.start()


@app.post("/agents/system_watcher/stop")
async def stop_system_watcher() -> dict:
    return await system_watcher.stop()


@app.get("/self-heal/status")
def self_heal_status() -> dict:
    return self_healing_agent.status()


@app.get("/self-heal/suggestions")
def self_heal_suggestions() -> dict:
    return {
        "agent": self_healing_agent.name,
        "suggestions": self_healing_agent.suggestions(),
    }


@app.post("/self-heal/approve")
def self_heal_approve(payload: SelfHealApprovalRequest) -> dict:
    return self_healing_agent.approve(payload.action)


@app.post("/command")
def command(payload: CommandRequest) -> dict:
    return route_slash_command(payload.input)


@app.post("/command/approve")
def command_approve(payload: CommandApprovalRequest) -> dict:
    return approve_command(payload.action, payload.args)


@app.get("/coding/plan")
def coding_plan(request: str = "") -> dict:
    return controller.local_coding_agent.handle(request)
