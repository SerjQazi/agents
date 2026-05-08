"""FastAPI backend for the local multi-agent dashboard."""

import html
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import zipfile
import math # Added for dashboard rendering helpers
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.agent_core.config import settings
from core.agent_core.controller import AgentController
from core.agent_core.self_healing_agent import SelfHealingAgent
from core.agent_core.system_watcher import SystemWatcher
from apps.shared_layout import layout_css, render_layout

# AGENTOS ANALYZE UPLOAD START
# Import scanner from builder_agent for read-only FiveM script analysis
try:
    from apps.builder_agent.scanner import ScriptScanner
    from apps.builder_agent.config import PlannerConfig
    BUILDER_SCANNER_AVAILABLE = True
except ImportError:
    BUILDER_SCANNER_AVAILABLE = False
    ScriptScanner = None
    PlannerConfig = None
# AGENTOS ANALYZE UPLOAD END


app = FastAPI(title=settings.app_name)
controller = AgentController()
system_watcher = SystemWatcher()
self_healing_agent = SelfHealingAgent()
BASE_DIR = Path(__file__).resolve().parents[2]
GIT_HELPER = BASE_DIR / "scripts" / "git_helper.sh"
BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9/_\.-]+$")
DANGEROUS_MESSAGE_CHARS = re.compile(r"[;&|$`<>\"'\\\n\r]")
SAFE_ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")


class CommandRequest(BaseModel):
    input: str = ""


class CommandApprovalRequest(BaseModel):
    action: str
    args: dict[str, Any] = {}


class SelfHealApprovalRequest(BaseModel):
    action: str


class AITaskRequest(BaseModel):
    instruction: str
    provider: str = "auto"


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


# Dashboard V2 safe built-in task: read-only host checks for end-to-end task pipeline validation.
def run_dashboard_v2_health_check_task() -> dict[str, Any]:
    from orchestrator.models import Plan, RiskLevel, Step, StepStatus, Task, TaskStatus, TimelineEventType, ToolType
    from orchestrator.store import TaskStore

    store = TaskStore()
    command_steps = [
        'echo "Dashboard V2 task system works"',
        "date",
        "whoami",
        "pwd",
        "systemctl is-active agentos.service || true",
    ]

    step = Step(
        name="Run read-only health check commands",
        description="Execute safe shell checks and capture stdout/stderr for Dashboard V2 verification.",
        tool=ToolType.LOCAL_SCRIPT,
        purpose="Validate Dashboard V2 task system end-to-end",
        risk_level=RiskLevel.SAFE,
    )
    plan = Plan(
        name="Health Check Dashboard V2 Plan",
        description="Single safe step to run read-only host commands.",
        steps=[step],
        total_steps=1,
        completed_steps=0,
    )
    task = Task(
        name="Health Check Dashboard V2",
        description="Built-in Dashboard V2 safe test task.",
        status=TaskStatus.PENDING,
        dry_run=False,
        approval_required=False,
        plan=plan,
        metadata={"source": "dashboard-v2", "built_in_task": "health_check_dashboard_v2"},
        logs=[],
    )
    task.add_timeline(event_type=TimelineEventType.CREATED, step_id=step.step_id, step_name=step.name, details="Task queued")
    task.logs.append("Queued: Health Check Dashboard V2")
    store.create(task)

    try:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now()
        task.add_timeline(event_type=TimelineEventType.EXECUTING, step_id=step.step_id, step_name=step.name, tool_used=step.tool, risk_level=step.risk_level, details="Task running")
        task.logs.append("Running: executing read-only commands")
        store.update(task)

        for command in command_steps:
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            task.logs.append(f"$ {command}")
            if result.stdout:
                task.logs.append(f"stdout:\n{result.stdout.rstrip()}")
            if result.stderr:
                task.logs.append(f"stderr:\n{result.stderr.rstrip()}")
            task.logs.append(f"exit_code: {result.returncode}")
            store.update(task)

        step.status = StepStatus.COMPLETED
        step.completed_at = datetime.now()
        task.plan.completed_steps = 1
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.add_timeline(
            event_type=TimelineEventType.COMPLETED,
            step_id=step.step_id,
            step_name=step.name,
            tool_used=step.tool,
            risk_level=step.risk_level,
            details="Task completed",
        )
        task.logs.append("Completed: Health Check Dashboard V2")
        store.update(task)
    except Exception as error:
        step.status = StepStatus.FAILED
        step.completed_at = datetime.now()
        step.error = str(error)
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now()
        task.add_timeline(
            event_type=TimelineEventType.FAILED,
            step_id=step.step_id,
            step_name=step.name,
            tool_used=step.tool,
            risk_level=step.risk_level,
            details=f"Task failed: {error}",
        )
        task.logs.append(f"Failed: {error}")
        store.update(task)

    return {"task_id": task.task_id, "status": task.status.value}


# AGENTOS FIVEM CONTROL CENTER START
def _detect_incoming_folder() -> dict[str, Any]:
    candidates = [
        BASE_DIR / "incoming",
        BASE_DIR / "uploads" / "incoming",
        BASE_DIR / "orchestrator" / "incoming",
        BASE_DIR / "staging" / "incoming",
        Path("/home/agentzero/agents/incoming"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            entries = [p for p in candidate.iterdir() if not p.name.startswith(".")]
            return {
                "path": str(candidate),
                "entries_count": len(entries),
            }
    return {"path": None, "entries_count": 0}


def _detect_fivem_server_path() -> str | None:
    env_candidates = [
        os.getenv("FIVEM_SERVER_PATH"),
        os.getenv("QBCORE_SERVER_PATH"),
        os.getenv("SERVER_PATH"),
        os.getenv("FIVEM_PATH"),
    ]
    for raw in env_candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.exists():
            return str(path)

    known = Path("/home/agentzero/fivem-server/txData/QBCore_F16AC8.base")
    if known.exists():
        return str(known)

    try:
        from apps.planner_agent.config import settings as planner_settings

        server_resources = planner_settings.server_resources
        if server_resources.exists():
            return str(server_resources.parent)
    except Exception:
        pass

    return None


def _analysis_artifacts_exist() -> bool:
    report_roots = [
        BASE_DIR / "reports" / "builder-agent",
        BASE_DIR / "reports" / "coding-agent",
    ]
    for root in report_roots:
        if root.is_dir() and any(root.iterdir()):
            return True

    report_globs = [
        "integration-report-*.md",
        "incoming-review-*.md",
        "gemini-integration-check-*.md",
    ]
    reports_root = BASE_DIR / "reports"
    if reports_root.is_dir():
        for pattern in report_globs:
            if any(reports_root.glob(pattern)):
                return True
    return False


def _next_recommended_action(incoming_path: str | None, entries_count: int, analysis_exists: bool) -> str:
    if not incoming_path:
        return "Create or choose an incoming folder before starting script intake."
    if entries_count == 0:
        return "Upload a FiveM script ZIP/resource to begin analysis."
    if not analysis_exists:
        return "Run analysis on the uploaded script (Planner/AI integration check)."
    return "Review patch plan and approve staged changes."
# AGENTOS FIVEM CONTROL CENTER END


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
        "direct_service_url": "http://100.68.10.125:8010",
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
        "direct_service_url": "http://100.68.10.125:8020",
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
    if url.startswith("/"):
        return True
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
        suggested_action = "Open AgentOS page" if url.startswith("/") or url_reachable else "Check service or use local host access."
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
              <h1>AgentOS Dashboard <span class="home-badge">Home</span></h1>
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


def _incoming_resource_queue_html() -> str:
    """Render the Upload Pipeline-owned incoming resource queue shell."""
    return """
      <section class="incoming-queue-section" id="incoming-queue">
        <div class="incoming-queue-head">
          <div>
            <span class="pipeline-kicker">UPLOAD -> SCAN -> ANALYZE -> PLAN -> STAGE -> REVIEW</span>
            <h3>Incoming Resource Queue</h3>
            <p>Resource-level controls live here so Mission Control stays focused on monitoring and approvals.</p>
          </div>
          <a class="button secondary" href="/reviews">Open Codex Review</a>
        </div>
        <div class="incoming-queue-loading" id="incoming-queue-loading">Loading incoming resources...</div>
        <div class="incoming-queue-error" id="incoming-queue-error" style="display:none;">Failed to load resources</div>
        <div class="incoming-queue-empty" id="incoming-queue-empty" style="display:none;">No incoming resources found</div>
        <div class="incoming-queue-list" id="incoming-queue-list"></div>
      </section>
    """


def _document_modal_html() -> str:
    """Shared document modal used by queue actions for plans, prompts, and staging diffs."""
    return """
      <div class="doc-modal-overlay" id="doc-modal-overlay" aria-hidden="true">
        <div class="doc-modal" role="dialog" aria-modal="true" aria-labelledby="doc-modal-title">
          <div class="doc-modal-header">
            <div>
              <h3 id="doc-modal-title" class="doc-modal-title">Document</h3>
              <p id="doc-modal-meta" class="doc-modal-meta">Ready</p>
            </div>
            <div class="doc-modal-actions">
              <button class="button secondary" type="button" id="doc-modal-copy-btn">Copy</button>
              <button class="button secondary" type="button" id="doc-modal-close-btn" aria-label="Close">X</button>
            </div>
          </div>
          <pre id="doc-modal-content" class="doc-modal-content"></pre>
        </div>
      </div>
    """


def _incoming_resource_queue_css() -> str:
    """Shared styling for the Upload Pipeline incoming queue and document modal."""
    return """
      .incoming-queue-section {
        border: 1px solid rgba(0, 242, 255, 0.2);
        border-radius: 4px;
        background: #0d1c2d;
        padding: 14px;
        min-width: 0;
      }
      .incoming-queue-head {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 14px;
        margin-bottom: 12px;
      }
      .incoming-queue-head h3 {
        margin: 0 0 5px;
        font-size: 15px;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        color: #91f8ff;
      }
      .incoming-queue-head p {
        margin: 0;
        max-width: 720px;
        color: #91a9c4;
        font-size: 12px;
        line-height: 1.45;
      }
      .incoming-queue-list {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        max-height: 720px;
        overflow-y: auto;
        min-width: 0;
        padding-right: 3px;
      }
      .incoming-resource-item {
        border: 1px solid rgba(0, 242, 255, 0.2);
        border-radius: 4px;
        padding: 12px;
        background: rgba(5, 14, 24, 0.78);
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 9px;
      }
      .resource-header {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 8px;
        align-items: start;
        min-width: 0;
      }
      .resource-title-line {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 7px;
        min-width: 0;
      }
      .resource-name {
        font-size: 14px;
        font-weight: 800;
        color: #e8f5ff;
        min-width: 0;
        overflow-wrap: anywhere;
      }
      .resource-manifest {
        font-size: 10px;
        color: #8fa8c4;
        padding: 2px 6px;
        border-radius: 4px;
        background: rgba(0, 242, 255, 0.1);
        overflow-wrap: anywhere;
      }
      .resource-status {
        font-size: 10px;
        padding: 3px 7px;
        border-radius: 4px;
        white-space: nowrap;
        font-weight: 800;
        letter-spacing: 0.05em;
      }
      .resource-status.analyzed { background: rgba(0, 255, 159, 0.15); color: #00ff9f; }
      .resource-status.not-analyzed { background: rgba(255, 200, 87, 0.15); color: #ffc857; }
      .resource-meta-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px 10px;
        color: #7f99b2;
        font-size: 10px;
        font-family: "JetBrains Mono", ui-monospace, monospace;
      }
      .resource-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        min-width: 0;
      }
      .analysis-badge, .staging-badge, .analysis-action {
        padding: 3px 7px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 800;
        border: 1px solid rgba(0, 242, 255, 0.2);
        line-height: 1.25;
      }
      .analysis-badge { background: rgba(0, 242, 255, 0.12); color: #7cecff; }
      .analysis-badge.framework { color: #d2a6ff; border-color: rgba(210, 166, 255, 0.32); background: rgba(210, 166, 255, 0.12); }
      .analysis-badge.inventory { color: #00ff9f; border-color: rgba(0, 255, 159, 0.3); background: rgba(0, 255, 159, 0.12); }
      .analysis-badge.target { color: #ffc857; border-color: rgba(255, 200, 87, 0.3); background: rgba(255, 200, 87, 0.12); }
      .analysis-badge.database { color: #73bfff; border-color: rgba(115, 191, 255, 0.3); background: rgba(115, 191, 255, 0.12); }
      .analysis-badge.risk { border-color: rgba(255, 140, 162, 0.32); background: rgba(255, 95, 122, 0.12); }
      .analysis-action { color: #d8ecff; background: rgba(0, 242, 255, 0.08); }
      .staging-badge.staged { color: #7cecff; background: rgba(0, 242, 255, 0.12); }
      .staging-badge.ready { color: #00ff9f; background: rgba(0, 255, 159, 0.12); }
      .staging-badge.modified { color: #ffc857; background: rgba(255, 200, 87, 0.12); }
      .staging-badge.approved { color: #00ff9f; background: rgba(0, 255, 159, 0.2); }
      .staging-badge.rejected { color: #ff5f7a; background: rgba(255, 95, 122, 0.18); }
      .resource-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        min-width: 0;
      }
      .resource-actions .button {
        min-height: 32px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .incoming-queue-loading, .incoming-queue-error, .incoming-queue-empty {
        padding: 14px;
        border: 1px dashed rgba(0, 242, 255, 0.2);
        border-radius: 4px;
        color: #8fa8c4;
        text-align: center;
        font-size: 12px;
      }
      .incoming-queue-error { color: #ff5f7a; }

      .doc-modal-overlay {
        position: fixed;
        inset: 0;
        background: rgba(2, 10, 20, 0.82);
        display: none;
        align-items: center;
        justify-content: center;
        z-index: 2000;
        padding: 16px;
      }
      .doc-modal-overlay.open { display: flex; }
      .doc-modal {
        width: min(1180px, 98vw);
        max-height: 92vh;
        background: #0d1c2d;
        border: 1px solid rgba(0, 242, 255, 0.22);
        border-radius: 4px;
        box-shadow: 0 0 20px rgba(0, 242, 255, 0.08);
        display: flex;
        flex-direction: column;
      }
      .doc-modal-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        padding: 10px;
        border-bottom: 1px solid rgba(0, 242, 255, 0.22);
        gap: 10px;
      }
      .doc-modal-title { margin: 0; font-size: 13px; color: #d8f2ff; }
      .doc-modal-meta { margin: 3px 0 0; font-size: 11px; color: #8da8c5; }
      .doc-modal-actions { display: flex; gap: 6px; }
      .doc-modal-content {
        margin: 0;
        padding: 10px;
        overflow: auto;
        max-height: 76vh;
        white-space: pre-wrap;
        word-break: break-word;
        font-family: "JetBrains Mono", ui-monospace, monospace;
        font-size: 12px;
        line-height: 1.45;
        color: #e7edf8;
        background: rgba(4, 11, 21, 0.7);
      }
      @media (max-width: 1320px) {
        .incoming-queue-list { grid-template-columns: 1fr; }
      }
      @media (max-width: 760px) {
        .incoming-queue-head { flex-direction: column; }
        .resource-header { grid-template-columns: 1fr; }
        .resource-status { width: fit-content; }
      }
    """


def _incoming_resource_queue_js(incoming_resources_json: str) -> str:
    """Render queue behavior for analysis, patch plans, prompts, and staging."""
    return '''
      <script>
      (function() {
        const incomingResourcesData = ''' + incoming_resources_json + ''';
        const ANALYSIS_ACTION_LABELS = {
          "safe": "Ready for staging",
          "manual-sql": "SQL needs review",
          "review-required": "Risk - review needed",
          "adaptation-needed": "Adaptation needed",
        };

        function escapeHtml(value) {
          return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }

        function getDocModalNodes() {
          return {
            overlay: document.getElementById("doc-modal-overlay"),
            title: document.getElementById("doc-modal-title"),
            meta: document.getElementById("doc-modal-meta"),
            content: document.getElementById("doc-modal-content"),
            copyBtn: document.getElementById("doc-modal-copy-btn"),
            closeBtn: document.getElementById("doc-modal-close-btn"),
          };
        }

        function closeDocumentModal() {
          const nodes = getDocModalNodes();
          if (!nodes.overlay) return;
          nodes.overlay.classList.remove("open");
          nodes.overlay.setAttribute("aria-hidden", "true");
        }

        function openDocumentModal(title, meta, contentText) {
          const nodes = getDocModalNodes();
          if (!nodes.overlay || !nodes.title || !nodes.meta || !nodes.content || !nodes.copyBtn) return;
          nodes.title.textContent = title || "Document";
          nodes.meta.textContent = meta || "";
          nodes.content.textContent = contentText || "";
          nodes.overlay.classList.add("open");
          nodes.overlay.setAttribute("aria-hidden", "false");
          nodes.copyBtn.onclick = () => {
            const text = nodes.content.textContent || "";
            navigator.clipboard.writeText(text).then(() => alert("Copied.")).catch(() => alert("Copy failed."));
          };
          nodes.content.scrollTop = 0;
        }

        function wireDocumentModalBehavior() {
          const nodes = getDocModalNodes();
          if (!nodes.overlay || !nodes.closeBtn) return;
          nodes.closeBtn.addEventListener("click", closeDocumentModal);
          nodes.overlay.addEventListener("click", (event) => {
            if (event.target === nodes.overlay) closeDocumentModal();
          });
          document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && nodes.overlay.classList.contains("open")) closeDocumentModal();
          });
        }

        async function openPatchPlanModal(scriptName) {
          const response = await fetch("/api/analysis/" + encodeURIComponent(scriptName) + "/patch-plan/md", { method: "GET" });
          const body = await response.json();
          if (!response.ok) throw new Error(body.detail || body.error || "Patch plan not found");
          openDocumentModal("Patch Plan", "Resource: " + scriptName, body.content || "No patch plan content.");
        }

        async function openPromptModal(promptType) {
          const endpoint = promptType === "opencode" ? "/api/prompts/opencode-next" : "/api/prompts/codex-audit-next";
          const title = promptType === "opencode" ? "OpenCode Prompt" : "Codex Audit Prompt";
          const response = await fetch(endpoint, { method: "GET" });
          const body = await response.json();
          if (!response.ok) throw new Error(body.detail || body.error || "Prompt not available");
          openDocumentModal(title, "Generated: " + (body.generated_at || "unknown"), body.content || "");
        }

        function stagingDiffText(diff) {
          const lines = [];
          const safeDiff = diff || {};
          const summary = safeDiff.summary || {};
          lines.push("Resource: " + String(safeDiff.resource || "unknown"));
          lines.push("Status: " + String(safeDiff.status || "UNKNOWN"));
          lines.push("");
          lines.push("Changed files (" + String(summary.changed || 0) + "):");
          for (const p of (safeDiff.changed_files || [])) lines.push("  - " + p);
          if (!(safeDiff.changed_files || []).length) lines.push("  - none");
          lines.push("");
          lines.push("Added files (" + String(summary.added || 0) + "):");
          for (const p of (safeDiff.added_files || [])) lines.push("  - " + p);
          if (!(safeDiff.added_files || []).length) lines.push("  - none");
          lines.push("");
          lines.push("Deleted files (" + String(summary.deleted || 0) + "):");
          for (const p of (safeDiff.deleted_files || [])) lines.push("  - " + p);
          if (!(safeDiff.deleted_files || []).length) lines.push("  - none");
          return lines.join("\\n");
        }

        function getRiskColor(risk) {
          if (risk === "high") return "var(--ao-danger)";
          if (risk === "medium") return "#fbbf24";
          return "var(--ao-green)";
        }

        function getActionLabel(recommendedAction) {
          return ANALYSIS_ACTION_LABELS[recommendedAction] || recommendedAction || "Ready";
        }

        function riskFromFindings(findings) {
          let risk = "low";
          for (const finding of (findings || [])) {
            if (finding && finding.severity === "high") {
              risk = "high";
              break;
            }
            if (finding && finding.severity === "medium" && risk !== "high") risk = "medium";
          }
          return risk;
        }

        function summaryFromAnalysis(analysis) {
          if (analysis && analysis.summary) return analysis.summary;
          const markers = (analysis && analysis.markers) || {};
          return {
            framework: Object.keys(markers.framework || {}).join(", ") || "standalone",
            inventory: Object.keys(markers.inventory || {}).join(", ") || "none",
            target: Object.keys(markers.target || {}).join(", ") || "none",
            database: Object.keys(markers.database || {}).join(", ") || "none",
            risk: riskFromFindings(analysis && analysis.findings),
          };
        }

        function summaryBadgesHtml(summary) {
          const safeSummary = summary || {};
          const framework = safeSummary.framework || "standalone";
          const inventory = safeSummary.inventory || "none";
          const target = safeSummary.target || "none";
          const database = safeSummary.database || "none";
          const risk = safeSummary.risk || "low";
          return `
            <span class="analysis-badge framework">${escapeHtml(framework)}</span>
            <span class="analysis-badge inventory">${escapeHtml(inventory)}</span>
            <span class="analysis-badge target">${escapeHtml(target)}</span>
            <span class="analysis-badge database">${escapeHtml(database)}</span>
            <span class="analysis-badge risk" style="color:${getRiskColor(risk)}">Risk: ${escapeHtml(risk)}</span>
          `;
        }

        function normalizedStageStatus(resource) {
          const raw = String((resource && resource.staging && resource.staging.status) || "NONE").toUpperCase();
          if (["STAGED", "READY", "MODIFIED", "APPROVED", "REJECTED"].includes(raw)) return raw;
          return "NONE";
        }

        function stageBadgeHtml(resource) {
          const status = normalizedStageStatus(resource);
          if (status === "NONE") return "";
          return `<span class="staging-badge ${escapeHtml(status.toLowerCase())}">${escapeHtml(status)}</span>`;
        }

        function postStageButtonsHtml(name) {
          return `
            <button class="button secondary view-staging-diff-btn" data-script="${escapeHtml(name)}">View Staging Diff</button>
            <button class="button secondary approve-staging-btn" data-script="${escapeHtml(name)}">Approve For Apply</button>
            <button class="button secondary delete-staging-btn" data-script="${escapeHtml(name)}">Delete Staging Copy</button>
          `;
        }

        function resourceHasPatchPlan(scriptName) {
          const resource = (incomingResourcesData || []).find((item) => item && item.name === scriptName);
          return !!(resource && resource.has_patch_plan);
        }

        function resourceHasStaging(scriptName) {
          const resource = (incomingResourcesData || []).find((item) => item && item.name === scriptName);
          return !!(resource && resource.staging && resource.staging.exists);
        }

        function findResourceItemByName(scriptName) {
          const items = document.querySelectorAll(".incoming-resource-item");
          for (const item of items) {
            if ((item.dataset && item.dataset.name) === scriptName) return item;
          }
          return null;
        }

        function scanStateFor(resource) {
          if (resource && resource.staging && resource.staging.exists) return String(resource.staging.status || "STAGED").toUpperCase();
          if (resource && resource.has_patch_plan) return "PATCH_READY";
          if (resource && resource.analyzed) return "ANALYZED";
          return "PENDING_SCAN";
        }

        function renderIncomingResources() {
          const container = document.getElementById("incoming-queue-list");
          const loading = document.getElementById("incoming-queue-loading");
          const empty = document.getElementById("incoming-queue-empty");
          if (!container || !loading || !empty) return;

          if (!incomingResourcesData || incomingResourcesData.length === 0) {
            loading.style.display = "none";
            empty.style.display = "block";
            return;
          }

          loading.style.display = "none";
          empty.style.display = "none";

          container.innerHTML = incomingResourcesData.map(resource => {
            let badgesHtml = "";
            if (resource.analyzed && resource.analysis) {
              badgesHtml = summaryBadgesHtml(summaryFromAnalysis(resource.analysis));
            } else {
              badgesHtml = '<span class="analysis-badge">Scan pending</span>';
            }
            badgesHtml += stageBadgeHtml(resource);

            const statusHtml = resource.analyzed
              ? `<span class="resource-status analyzed">Analyzed</span>`
              : `<span class="resource-status not-analyzed">Not analyzed</span>`;
            const patchPlanActions = resource.analyzed
              ? `<button class="button secondary generate-plan-btn" data-script="${escapeHtml(resource.name)}">Generate Patch Plan</button>
                 <button class="button secondary view-plan-btn" data-script="${escapeHtml(resource.name)}">View Patch Plan</button>`
              : "";
            const promptActions = (resource.analyzed && resource.has_patch_plan)
              ? `<button class="button secondary generate-opencode-prompt-btn" data-script="${escapeHtml(resource.name)}">Generate OpenCode Prompt</button>
                 <button class="button secondary view-opencode-prompt-btn" data-script="${escapeHtml(resource.name)}">View OpenCode Prompt</button>
                 <button class="button secondary view-codex-prompt-btn" data-script="${escapeHtml(resource.name)}">View Codex Audit Prompt</button>`
              : "";
            const stagingActions = resource.analyzed
              ? (resource.staging && resource.staging.exists
                  ? postStageButtonsHtml(resource.name)
                  : `<button class="button secondary stage-safe-copy-btn" data-script="${escapeHtml(resource.name)}">Stage Safe Copy</button>`)
              : "";
            const analyzedAction = resource.analyzed && resource.analysis
              ? `<span class="analysis-action">${escapeHtml(getActionLabel((resource.analysis.summary || {}).recommended_action || "safe"))}</span>`
              : "";

            return `
              <div class="incoming-resource-item" data-name="${escapeHtml(resource.name)}">
                <div class="resource-header">
                  <div>
                    <div class="resource-title-line">
                      <span class="resource-name">${escapeHtml(resource.name)}</span>
                      <span class="resource-manifest">${escapeHtml(resource.manifest || "No manifest")}</span>
                    </div>
                    <div class="resource-meta-row">
                      <span>${escapeHtml(resource.file_count || 0)} files</span>
                      <span>${escapeHtml(scanStateFor(resource))}</span>
                      <span>${escapeHtml(resource.updated_at || "unknown")}</span>
                    </div>
                  </div>
                  ${statusHtml}
                </div>
                <div class="resource-badges">${badgesHtml}${analyzedAction}</div>
                <div class="resource-actions">
                  <button class="button analyze-btn" data-script="${escapeHtml(resource.name)}">${resource.analyzed ? "Re-analyze" : "Analyze"}</button>
                  ${resource.analyzed ? `<button class="button secondary view-report-btn" data-script="${escapeHtml(resource.name)}">View Report</button>` : ""}
                  ${patchPlanActions}
                  ${promptActions}
                  ${stagingActions}
                </div>
              </div>
            `;
          }).join("");
        }

        async function analyzeResource(scriptName, button) {
          const original = button.textContent;
          button.disabled = true;
          button.textContent = "Analyzing...";
          try {
            const response = await fetch("/api/incoming/" + encodeURIComponent(scriptName) + "/analyze", { method: "POST" });
            const body = await response.json();
            if (!response.ok) throw new Error(body.detail || body.error || "Analysis failed");
            if (body.status === "success" && body.summary) {
              const s = body.summary;
              const resource = (incomingResourcesData || []).find((item) => item && item.name === scriptName);
              if (resource) {
                resource.analyzed = true;
                resource.analysis = resource.analysis || {};
                resource.analysis.markers = resource.analysis.markers || {};
                resource.analysis.summary = s;
              }
              const item = findResourceItemByName(scriptName);
              if (item) {
                const badges = item.querySelector(".resource-badges");
                badges.innerHTML = summaryBadgesHtml(s) + `<span class="analysis-action">${escapeHtml(getActionLabel(s.recommended_action))}</span>` + (resource ? stageBadgeHtml(resource) : "");
                const status = item.querySelector(".resource-status");
                if (status) {
                  status.className = "resource-status analyzed";
                  status.textContent = "Analyzed";
                }
                const actions = item.querySelector(".resource-actions");
                const promptActions = resourceHasPatchPlan(scriptName)
                  ? `<button class="button secondary generate-opencode-prompt-btn" data-script="${escapeHtml(scriptName)}">Generate OpenCode Prompt</button>
                     <button class="button secondary view-opencode-prompt-btn" data-script="${escapeHtml(scriptName)}">View OpenCode Prompt</button>
                     <button class="button secondary view-codex-prompt-btn" data-script="${escapeHtml(scriptName)}">View Codex Audit Prompt</button>`
                  : "";
                const stageActions = resourceHasStaging(scriptName) ? postStageButtonsHtml(scriptName) : `<button class="button secondary stage-safe-copy-btn" data-script="${escapeHtml(scriptName)}">Stage Safe Copy</button>`;
                actions.innerHTML = `
                  <button class="button analyze-btn" data-script="${escapeHtml(scriptName)}">Re-analyze</button>
                  <button class="button secondary view-report-btn" data-script="${escapeHtml(scriptName)}">View Report</button>
                  <button class="button secondary generate-plan-btn" data-script="${escapeHtml(scriptName)}">Generate Patch Plan</button>
                  <button class="button secondary view-plan-btn" data-script="${escapeHtml(scriptName)}">View Patch Plan</button>
                  ${promptActions}
                  ${stageActions}
                `;
              }
            } else {
              throw new Error(body.error || "Analysis failed");
            }
          } catch (error) {
            alert("Analysis failed: " + String(error.message || error));
            button.textContent = original;
            button.disabled = false;
          }
        }

        document.addEventListener("click", function(event) {
          const analyzeBtn = event.target.closest(".analyze-btn");
          if (analyzeBtn) {
            analyzeResource(analyzeBtn.dataset.script, analyzeBtn);
            return;
          }

          const viewBtn = event.target.closest(".view-report-btn");
          if (viewBtn) {
            window.location.href = "/dashboard-v2/report/" + encodeURIComponent(viewBtn.dataset.script);
            return;
          }

          const generatePlanBtn = event.target.closest(".generate-plan-btn");
          if (generatePlanBtn) {
            const scriptName = generatePlanBtn.dataset.script;
            const original = generatePlanBtn.textContent;
            generatePlanBtn.disabled = true;
            generatePlanBtn.textContent = "Generating...";
            fetch("/api/analysis/" + encodeURIComponent(scriptName) + "/generate-patch-plan", { method: "POST" })
              .then(async (response) => {
                const body = await response.json();
                if (!response.ok) throw new Error(body.detail || body.error || "Failed to generate patch plan");
                alert("Patch plan generated for " + scriptName);
                const resource = (incomingResourcesData || []).find((item) => item && item.name === scriptName);
                if (resource) resource.has_patch_plan = true;
                renderIncomingResources();
              })
              .catch((error) => alert("Patch plan generation failed: " + String(error.message || error)))
              .finally(() => {
                generatePlanBtn.disabled = false;
                generatePlanBtn.textContent = original;
              });
            return;
          }

          const viewPlanBtn = event.target.closest(".view-plan-btn");
          if (viewPlanBtn) {
            openPatchPlanModal(viewPlanBtn.dataset.script).catch((error) => alert("View patch plan failed: " + String(error.message || error)));
            return;
          }

          const generatePromptBtn = event.target.closest(".generate-opencode-prompt-btn");
          if (generatePromptBtn) {
            const scriptName = generatePromptBtn.dataset.script;
            const original = generatePromptBtn.textContent;
            generatePromptBtn.disabled = true;
            generatePromptBtn.textContent = "Generating...";
            fetch("/api/patch-plan/" + encodeURIComponent(scriptName) + "/generate-opencode-prompt", { method: "POST" })
              .then(async (response) => {
                const body = await response.json();
                if (!response.ok) throw new Error(body.detail || body.error || "Failed to generate prompts");
                alert("OpenCode and Codex prompts generated for " + scriptName);
              })
              .catch((error) => alert("Prompt generation failed: " + String(error.message || error)))
              .finally(() => {
                generatePromptBtn.disabled = false;
                generatePromptBtn.textContent = original;
              });
            return;
          }

          const stageSafeCopyBtn = event.target.closest(".stage-safe-copy-btn");
          if (stageSafeCopyBtn) {
            const scriptName = stageSafeCopyBtn.dataset.script;
            const original = stageSafeCopyBtn.textContent;
            stageSafeCopyBtn.disabled = true;
            stageSafeCopyBtn.textContent = "Staging...";
            fetch("/api/staging/" + encodeURIComponent(scriptName) + "/create", { method: "POST" })
              .then(async (response) => {
                const body = await response.json();
                if (!response.ok) throw new Error(body.detail || body.error || "Failed to create staging copy");
                const resource = (incomingResourcesData || []).find((item) => item && item.name === scriptName);
                if (resource) resource.staging = { exists: true, status: String(body.staging_status || "STAGED"), approved_at: null };
                renderIncomingResources();
              })
              .catch((error) => alert("Stage Safe Copy failed: " + String(error.message || error)))
              .finally(() => {
                stageSafeCopyBtn.disabled = false;
                stageSafeCopyBtn.textContent = original;
              });
            return;
          }

          const viewStagingDiffBtn = event.target.closest(".view-staging-diff-btn");
          if (viewStagingDiffBtn) {
            const scriptName = viewStagingDiffBtn.dataset.script;
            fetch("/api/staging/" + encodeURIComponent(scriptName) + "/diff", { method: "GET" })
              .then(async (response) => {
                const body = await response.json();
                if (!response.ok) throw new Error(body.detail || body.error || "Failed to load staging diff");
                const resource = (incomingResourcesData || []).find((item) => item && item.name === scriptName);
                if (resource && resource.staging) resource.staging.status = String(body.status || resource.staging.status || "READY");
                openDocumentModal("Staging Diff", "Resource: " + scriptName, stagingDiffText(body));
                renderIncomingResources();
              })
              .catch((error) => alert("View staging diff failed: " + String(error.message || error)));
            return;
          }

          const approveStagingBtn = event.target.closest(".approve-staging-btn");
          if (approveStagingBtn) {
            const scriptName = approveStagingBtn.dataset.script;
            fetch("/api/staging/" + encodeURIComponent(scriptName) + "/approve", { method: "POST" })
              .then(async (response) => {
                const body = await response.json();
                if (!response.ok) throw new Error(body.detail || body.error || "Approval failed");
                const resource = (incomingResourcesData || []).find((item) => item && item.name === scriptName);
                if (resource) {
                  resource.staging = resource.staging || {};
                  resource.staging.exists = true;
                  resource.staging.status = "APPROVED";
                  resource.staging.approved_at = body.approved_at || null;
                }
                renderIncomingResources();
              })
              .catch((error) => alert("Approve staging failed: " + String(error.message || error)));
            return;
          }

          const deleteStagingBtn = event.target.closest(".delete-staging-btn");
          if (deleteStagingBtn) {
            const scriptName = deleteStagingBtn.dataset.script;
            fetch("/api/staging/" + encodeURIComponent(scriptName), { method: "DELETE" })
              .then(async (response) => {
                const body = await response.json();
                if (!response.ok) throw new Error(body.detail || body.error || "Delete staging failed");
                const resource = (incomingResourcesData || []).find((item) => item && item.name === scriptName);
                if (resource) resource.staging = { exists: false, status: "NONE", approved_at: null };
                renderIncomingResources();
              })
              .catch((error) => alert("Delete staging copy failed: " + String(error.message || error)));
            return;
          }

          const viewOpenCodePromptBtn = event.target.closest(".view-opencode-prompt-btn");
          if (viewOpenCodePromptBtn) {
            openPromptModal("opencode").catch((error) => alert("View OpenCode prompt failed: " + String(error.message || error)));
            return;
          }

          const viewCodexPromptBtn = event.target.closest(".view-codex-prompt-btn");
          if (viewCodexPromptBtn) {
            openPromptModal("codex").catch((error) => alert("View Codex prompt failed: " + String(error.message || error)));
          }
        });

        wireDocumentModalBehavior();
        renderIncomingResources();
      })();
      </script>
    '''


@app.get("/dashboard-v2", response_class=HTMLResponse)
def super_dashboard() -> str:
    try:
        from apps.shared_layout import render_cyber_layout
        use_cyber = True
    except ImportError:
        from apps.shared_layout import render_layout
        use_cyber = False

    orchestrator_available = False
    tasks_data = {"active": [], "paused": [], "completed": [], "failed": []}
    approvals_data = []
    stats = {"total": 0, "active": 0, "paused": 0, "completed": 0, "failed": 0}
    timelines_data = []
    audit_logs = []
    blocked_ops = []
    execution_states = []
    risk_distribution = {"safe": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}
    latest_health_check_logs: list[str] = []
    # AGENTOS FIVEM CONTROL CENTER START
    incoming_info = _detect_incoming_folder()
    incoming_path = incoming_info["path"]
    incoming_entries_count = int(incoming_info["entries_count"])
    fivem_server_path = _detect_fivem_server_path()
    analysis_exists = _analysis_artifacts_exist()
    next_action = _next_recommended_action(incoming_path, incoming_entries_count, analysis_exists)
    incoming_resources = _get_incoming_resources_with_analysis(limit=8)
    # AGENTOS FIVEM CONTROL CENTER END

    try:
        import sys
        sys.path.insert(0, "/home/agentzero/agents")
        from orchestrator.store import TaskStore
        from orchestrator.recovery import RecoveryManager
        from orchestrator import Orchestrator

        store = TaskStore()
        rm = RecoveryManager()

        all_tasks = store.list_all()
        stats["total"] = len(all_tasks)

        for task in all_tasks:
            status = task.status.value

            task_info = {
                "id": task.task_id,
                "name": task.name,
                "status": status,
                "dry_run": task.dry_run,
                "approval_required": task.approval_required,
                "steps": len(task.plan.steps) if task.plan else 0,
                "updated": task.updated_at.isoformat() if task.updated_at else "",
                "timeline_count": len(task.timeline),
                "created": task.created_at.isoformat() if task.created_at else "",
                "completed_at": task.completed_at.isoformat() if task.completed_at else "",
            }

            if status == "pending" or status == "planning" or status == "ready" or status == "running":
                tasks_data["active"].append(task_info)
                stats["active"] += 1
            elif status == "paused":
                tasks_data["paused"].append(task_info)
                stats["paused"] += 1
            elif status == "completed":
                tasks_data["completed"].append(task_info)
                stats["completed"] += 1
                if task.name == "Health Check Dashboard V2":
                    latest_health_check_logs = task.logs[-30:]
            elif status == "failed" or status == "cancelled":
                tasks_data["failed"].append(task_info)
                stats["failed"] += 1

            if task.plan and task.plan.steps:
                for step in task.plan.steps:
                    risk = step.risk_level.value
                    if risk in risk_distribution:
                        risk_distribution[risk] += 1

                    for te in task.timeline[-3:]:
                        if te.event_type.value in ("executing", "validated", "completed", "failed"):
                            timelines_data.append({
                                "task_id": task.task_id[:8],
                                "task_name": task.name[:20],
                                "step_id": te.step_id or "",
                                "step_name": te.step_name or "",
                                "event": te.event_type.value,
                                "timestamp": te.timestamp.isoformat() if te.timestamp else "",
                                "duration_ms": te.duration_ms or 0,
                                "details": te.details or "",
                            })

                    if step.status.value == "failed" and step.error:
                        blocked_ops.append({
                            "task_id": task.task_id[:8],
                            "task_name": task.name[:20],
                            "step_name": step.name[:25],
                            "error": step.error[:50],
                            "risk": step.risk_level.value,
                        })

        approvals_data = rm.get_pending_approvals()
        approvals_data.extend(_staging_approval_entries(limit=20))

        try:
            orch = Orchestrator(store=store, dry_run_default=True)
            execution_states = orch.get_execution_audit_log()[:10]
        except Exception:
            pass

        orchestrator_available = True

    except Exception as e:
        orchestrator_available = False
        approvals_data = _staging_approval_entries(limit=20)

    active_tasks_html = ""
    for task in tasks_data["active"][:5]:
        active_tasks_html += f'''
        <div class="task-item">
            <span class="task-id">{task["id"][:8]}...</span>
            <span class="task-name">{task["name"][:30]}{"..." if len(task["name"]) > 30 else ""}</span>
            <span class="task-status active">{task["status"]}</span>
            <span class="task-steps">{task["steps"]} steps</span>
        </div>'''
    if not active_tasks_html:
        active_tasks_html = '<div class="empty-state">No active tasks</div>'

    paused_tasks_html = ""
    for task in tasks_data["paused"][:5]:
        risk_badge = "⚠️" if task.get("approval_required") else ""
        paused_tasks_html += f'''
        <div class="task-item">
            <span class="task-id">{task["id"][:8]}...</span>
            <span class="task-name">{task["name"][:25]}{"..." if len(task["name"]) > 25 else ""}</span>
            <span class="task-status paused">{task["status"]}</span>
            <span class="task-approval">{risk_badge}</span>
        </div>'''
    if not paused_tasks_html:
        paused_tasks_html = '<div class="empty-state">No paused tasks</div>'

    completed_tasks_html = ""
    for task in tasks_data["completed"][:5]:
        completed_tasks_html += f'''
        <div class="task-item">
            <span class="task-id">{task["id"][:8]}...</span>
            <span class="task-name">{task["name"][:30]}{"..." if len(task["name"]) > 30 else ""}</span>
            <span class="task-status completed">{task["status"]}</span>
        </div>'''
    if not completed_tasks_html:
        completed_tasks_html = '<div class="empty-state">No completed tasks</div>'

    health_check_logs_html = ""
    if latest_health_check_logs:
        health_check_logs_html = "<pre class=\"health-check-logs\">" + html.escape("\n".join(latest_health_check_logs)) + "</pre>"
    else:
        health_check_logs_html = '<div class="empty-state">No Health Check Dashboard V2 logs yet</div>'

    approvals_html = ""
    for app in approvals_data[:5]:
        risk = app.get("risk_level", "unknown")
        approvals_html += f'''
        <div class="approval-item">
            <span class="approval-task">{app.get("task_id", "unknown")[:8]}...</span>
            <span class="approval-step">{app.get("step_name", "unknown")}</span>
            <span class="approval-risk {risk}">{risk}</span>
        </div>'''
    if not approvals_html:
        approvals_html = '<div class="empty-state">No pending approvals</div>'

    timelines_html = ""
    for te in timelines_data[:10]:
        timelines_html += f'''
        <div class="timeline-item">
            <span class="timeline-task">{te.get("task_id", "")}...</span>
            <span class="timeline-step">{te.get("step_name", "")[:20]}</span>
            <span class="timeline-event {te.get("event", "")}">{te.get("event", "")}</span>
            <span class="timeline-duration">{te.get("duration_ms", 0)}ms</span>
        </div>'''
    if not timelines_html:
        timelines_html = '<div class="empty-state">No timeline events</div>'

    blocked_html = ""
    for blk in blocked_ops[:10]:
        blocked_html += f'''
        <div class="blocked-item">
            <span class="blocked-task">{blk.get("task_id", "")}</span>
            <span class="blocked-step">{blk.get("step_name", "")}</span>
            <span class="blocked-error">{blk.get("error", "")}</span>
            <span class="blocked-risk {blk.get("risk", "")}">{blk.get("risk", "")}</span>
        </div>'''
    if not blocked_html:
        blocked_html = '<div class="empty-state">No blocked operations</div>'

    audit_html = ""
    for audit in execution_states[:10]:
        audit_html += f'''
        <div class="audit-item">
            <span class="audit-status {audit.get("status", "")}">{audit.get("status", "")}</span>
            <span class="audit-command">{audit.get("command", "N/A")[:30]}</span>
            <span class="audit-risk">{audit.get("risk", "")}</span>
        </div>'''
    if not audit_html:
        audit_html = '<div class="empty-state">No audit logs</div>'

    execution_html = ""
    for exec_state in execution_states[:10]:
        execution_html += f'''
        <div class="execution-item">
            <span class="exec-status {exec_state.get("status", "")}">{exec_state.get("status", "")}</span>
            <span class="exec-command">{exec_state.get("command", "N/A")[:25]}</span>
            <span class="exec-risk">{exec_state.get("risk", "")}</span>
        </div>'''
    if not execution_html:
        execution_html = '<div class="empty-state">No execution states</div>'

    connection_class = "online" if orchestrator_available else "offline"

    focus_resource = (
        next((r for r in incoming_resources if isinstance(r.get("staging"), dict) and r.get("staging", {}).get("exists")), None)
        or next((r for r in incoming_resources if r.get("has_patch_plan")), None)
        or next((r for r in incoming_resources if r.get("analyzed")), None)
        or (incoming_resources[0] if incoming_resources else None)
    )
    focus_name = str(focus_resource.get("name", "No active resource")) if focus_resource else "No active resource"
    focus_stage = "Idle"
    focus_progress = 0
    focus_agent = "No active agent"
    focus_model = "Not selected"
    focus_risk = "unknown"
    focus_files = "0 live files"
    if focus_resource:
        focus_files = f"0 live / {int(focus_resource.get('file_count', 0))} incoming"
        analysis = focus_resource.get("analysis") if isinstance(focus_resource.get("analysis"), dict) else {}
        findings = analysis.get("findings", []) if isinstance(analysis, dict) else []
        focus_risk = "low"
        for finding in findings:
            severity = str(finding.get("severity", "")).lower() if isinstance(finding, dict) else ""
            if severity == "high":
                focus_risk = "high"
                break
            if severity == "medium" and focus_risk != "high":
                focus_risk = "medium"
        staging = focus_resource.get("staging") if isinstance(focus_resource.get("staging"), dict) else {}
        if staging.get("exists"):
            focus_stage = str(staging.get("status") or "STAGED").upper()
            focus_progress = 78 if focus_stage != "APPROVED" else 92
            focus_agent = "StageSafe Orchestrator"
            focus_model = "Rule-based safety runner"
        elif focus_resource.get("has_patch_plan"):
            focus_stage = "Patch plan ready"
            focus_progress = 64
            focus_agent = "Patch Plan Generator"
            focus_model = "Static report model"
        elif focus_resource.get("analyzed"):
            focus_stage = "Analysis complete"
            focus_progress = 46
            focus_agent = "ScriptScanner"
            focus_model = "Read-only analyzer"
        else:
            focus_stage = "Awaiting analysis"
            focus_progress = 22
            focus_agent = "Upload Intake"
            focus_model = "Not active"
    active_task_summary = (
        f'{tasks_data["active"][0]["name"]} ({tasks_data["active"][0]["status"]})'
        if tasks_data["active"]
        else next_action
    )
    focus_eta = "Ready for review" if focus_progress >= 90 else "Monitoring active stage" if focus_progress else "Waiting for intake"
    operation_log_lines = []
    for te in timelines_data[:4]:
        operation_log_lines.append(
            f'{te.get("task_id", "task")} {te.get("event", "event")} {te.get("step_name", "")[:32]}'.strip()
        )
    if not operation_log_lines and latest_health_check_logs:
        operation_log_lines = latest_health_check_logs[-4:]
    if not operation_log_lines:
        operation_log_lines = ["No active operation stream. Upload Pipeline is standing by."]
    operation_logs_html = "".join(f"<span>{html.escape(line)}</span>" for line in operation_log_lines)

    content = f'''
    <div class="mc-shell">
        <section class="mc-header">
            <div class="mc-title">
                <h1>ORCHESTRATOR_V1</h1>
                <p class="mc-subtitle">FiveM_AI_IDE / Instance Alpha-9 / Mission Control</p>
            </div>
            <div class="mc-connection {connection_class}">
                <span class="connection-dot"></span>
                { "CORE LINK ONLINE" if orchestrator_available else "CORE LINK DEGRADED" }
            </div>
        </section>

        <section class="mc-status-grid">
            <div class="mc-status-card"><span class="mc-status-label">Connection</span><strong class="{connection_class}">{ "ONLINE" if orchestrator_available else "OFFLINE" }</strong></div>
            <div class="mc-status-card"><span class="mc-status-label">Active</span><strong>{stats["active"]}</strong></div>
            <div class="mc-status-card"><span class="mc-status-label">Paused</span><strong class="warning">{stats["paused"]}</strong></div>
            <div class="mc-status-card"><span class="mc-status-label">Completed</span><strong class="success">{stats["completed"]}</strong></div>
            <div class="mc-status-card"><span class="mc-status-label">Failed</span><strong class="danger">{stats["failed"]}</strong></div>
        </section>

        <section class="mc-dashboard-grid">
            <article class="mc-panel mc-col-left">
                <header class="mc-panel-header"><h2>Active Agents</h2></header>
                <div class="mc-panel-body">
                    <div class="mc-subpanel">
                        <h3>Running Tasks</h3>
                        <div class="task-list">{active_tasks_html}</div>
                    </div>
                    <div class="mc-subpanel">
                        <h3>Paused Queue</h3>
                        <div class="task-list">{paused_tasks_html}</div>
                    </div>
                    <div class="mc-subpanel">
                        <h3>Approval Queue</h3>
                        <div class="approval-list">{approvals_html}</div>
                    </div>
                    <div class="mc-subpanel">
                        <h3>Completed</h3>
                        <div class="task-list">{completed_tasks_html}</div>
                    </div>
                </div>
            </article>

            <article class="mc-panel mc-col-center">
                <header class="mc-panel-header"><h2>Live Pipeline</h2></header>
                <div class="mc-panel-body">
                    <div class="workflow-steps">
                        <span class="workflow-step">1 Upload</span>
                        <span class="workflow-step">2 Analyze</span>
                        <span class="workflow-step">3 Patch Plan</span>
                        <span class="workflow-step">4 Approve</span>
                        <span class="workflow-step">5 Stage</span>
                        <span class="workflow-step">6 Apply</span>
                        <span class="workflow-step">7 Test</span>
                        <span class="workflow-step">8 Push</span>
                    </div>
                    <div class="mc-meta-grid">
                        <div class="focus-card">
                            <h3>Upload Pipeline</h3>
                            <p>Intake ZIP/resource uploads before any live operations.</p>
                            <a class="button" href="/upload">Open Upload Pipeline</a>
                        </div>
                        <div class="focus-card">
                            <h3>Incoming Scripts</h3>
                            <p>{html.escape(incoming_path) if incoming_path else "No incoming folder detected."}</p>
                            <p class="focus-meta">{incoming_entries_count} item(s) detected</p>
                        </div>
                        <div class="focus-card">
                            <h3>FiveM Target</h3>
                            <p>{html.escape(fivem_server_path) if fivem_server_path else "Server path not configured."}</p>
                        </div>
                        <div class="focus-card">
                            <h3>Next Action</h3>
                            <p>{html.escape(next_action)}</p>
                        </div>
                    </div>
                    <section class="operation-focus-panel" aria-label="Current Operation Focus">
                        <div class="operation-focus-head">
                            <span class="operation-live-dot"></span>
                            <div>
                                <h3>Current Operation Focus</h3>
                                <p>Live AI orchestration overview. Detailed resource actions now live in Upload Pipeline.</p>
                            </div>
                        </div>
                        <div class="operation-focus-main">
                            <div>
                                <span class="operation-label">Active Resource</span>
                                <strong class="operation-resource">{html.escape(focus_name)}</strong>
                                <p>{html.escape(active_task_summary)}</p>
                            </div>
                            <div class="operation-progress">
                                <span>{html.escape(focus_stage)}</span>
                                <div class="operation-track"><div class="operation-fill" style="width: {focus_progress}%"></div></div>
                                <small>{focus_progress}% · {html.escape(focus_eta)}</small>
                            </div>
                        </div>
                        <div class="operation-focus-grid">
                            <div><span>Active Agent</span><strong>{html.escape(focus_agent)}</strong></div>
                            <div><span>Reasoning Model</span><strong>{html.escape(focus_model)}</strong></div>
                            <div><span>Risk Level</span><strong class="risk-{html.escape(focus_risk)}">{html.escape(focus_risk.upper())}</strong></div>
                            <div><span>Files Modified</span><strong>{html.escape(focus_files)}</strong></div>
                        </div>
                        <div class="operation-log-stream">
                            {operation_logs_html}
                        </div>
                    </section>
                </div>
            </article>

            <article class="mc-panel mc-col-right">
                <header class="mc-panel-header"><h2>System Pulse Feed</h2></header>
                <div class="mc-panel-body">
                    <div class="mc-subpanel">
                        <h3>Execution Timelines</h3>
                        <div class="timeline-list">{timelines_html}</div>
                    </div>
                    <div class="mc-subpanel">
                        <h3>Audit Logs</h3>
                        <div class="audit-list">{audit_html}</div>
                    </div>
                    <div class="mc-subpanel">
                        <h3>Blocked Operations</h3>
                        <div class="blocked-list">{blocked_html}</div>
                    </div>
                    <div class="mc-subpanel">
                        <h3>Execution States</h3>
                        <div class="execution-list">{execution_html}</div>
                    </div>
                    <div class="mc-subpanel">
                        <h3>Health Logs</h3>
                        {health_check_logs_html}
                    </div>
                </div>
            </article>
        </section>

        <section class="mc-guard-strip">
            <div class="guard-left">
                <h3>Global System Guard</h3>
                <p>Staging-only operations enabled. No live apply, no txAdmin automation, no automatic push.</p>
                <div class="risk-bars">
                    <div class="risk-bar"><span>SAFE</span><div class="risk-track"><div class="risk-fill safe" style="width: { (risk_distribution['safe'] / max(stats['total'], 1)) * 100 }%"></div></div><strong>{risk_distribution['safe']}</strong></div>
                    <div class="risk-bar"><span>LOW</span><div class="risk-track"><div class="risk-fill low" style="width: { (risk_distribution['low'] / max(stats['total'], 1)) * 100 }%"></div></div><strong>{risk_distribution['low']}</strong></div>
                    <div class="risk-bar"><span>MED</span><div class="risk-track"><div class="risk-fill medium" style="width: { (risk_distribution['medium'] / max(stats['total'], 1)) * 100 }%"></div></div><strong>{risk_distribution['medium']}</strong></div>
                    <div class="risk-bar"><span>HIGH</span><div class="risk-track"><div class="risk-fill high" style="width: { (risk_distribution['high'] / max(stats['total'], 1)) * 100 }%"></div></div><strong>{risk_distribution['high']}</strong></div>
                    <div class="risk-bar"><span>CRIT</span><div class="risk-track"><div class="risk-fill critical" style="width: { (risk_distribution['critical'] / max(stats['total'], 1)) * 100 }%"></div></div><strong>{risk_distribution['critical']}</strong></div>
                </div>
            </div>
            <div class="guard-right">
                <button class="health-check-button" type="button" onclick="runHealthCheckDashboardV2Task()">Run Global Guard Health Check</button>
            </div>
        </section>

    </div>
    '''

    extra_css = '''
        .mc-shell {
            width: 100%;
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: 16px;
            font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
        }
        .mc-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 14px;
            padding: 16px 18px;
            border: 1px solid rgba(0, 242, 255, 0.2);
            border-radius: 4px;
            background: #0d1c2d;
        }
        .mc-title h1 {
            margin: 0 0 4px;
            font-size: 24px;
            font-weight: 700;
            letter-spacing: 0.04em;
            color: #00f2ff;
        }
        .mc-subtitle {
            margin: 0;
            font-size: 12px;
            font-weight: 500;
            letter-spacing: 0.04em;
            color: #8eeeff;
        }
        .mc-connection {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 10px;
            border: 1px solid rgba(0, 242, 255, 0.25);
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.06em;
        }
        .mc-connection.online { color: #00ff9f; border-color: rgba(0, 255, 159, 0.35); background: rgba(0, 255, 159, 0.08); }
        .mc-connection.offline { color: #ff5f7a; border-color: rgba(255, 95, 122, 0.35); background: rgba(255, 95, 122, 0.08); }
        .connection-dot { width: 8px; height: 8px; border-radius: 999px; background: currentColor; }

        .mc-status-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 10px;
            min-width: 0;
        }
        .mc-status-card {
            border: 1px solid rgba(0, 242, 255, 0.2);
            border-radius: 4px;
            background: #122131;
            padding: 11px 12px;
            min-width: 0;
        }
        .mc-status-label {
            display: block;
            font-size: 10px;
            letter-spacing: 0.08em;
            color: #8fa3be;
            margin-bottom: 5px;
            text-transform: uppercase;
        }
        .mc-status-card strong {
            font-size: 18px;
            color: #e9f5ff;
        }
        .mc-status-card strong.online, .mc-status-card strong.success { color: #00ff9f; }
        .mc-status-card strong.warning { color: #ffc857; }
        .mc-status-card strong.danger, .mc-status-card strong.offline { color: #ff5f7a; }

        .mc-dashboard-grid {
            width: 100%;
            min-width: 0;
            display: grid;
            grid-template-columns: repeat(12, minmax(0, 1fr));
            gap: 16px;
            align-items: start;
        }
        .mc-dashboard-grid > * { min-width: 0; }
        .mc-col-left { grid-column: span 3; }
        .mc-col-center { grid-column: span 6; }
        .mc-col-right { grid-column: span 3; }
        .mc-panel {
            border: 1px solid rgba(0, 242, 255, 0.2);
            border-radius: 4px;
            background: #122131;
            min-width: 0;
            overflow: hidden;
        }
        .mc-panel-header {
            border-bottom: 1px solid rgba(0, 242, 255, 0.2);
            padding: 10px 12px;
        }
        .mc-panel-header h2 {
            margin: 0;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #95f7ff;
        }
        .mc-panel-body {
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            min-width: 0;
        }
        .mc-subpanel {
            border: 1px solid rgba(0, 242, 255, 0.16);
            border-radius: 4px;
            background: rgba(6, 16, 28, 0.66);
            padding: 10px;
            min-width: 0;
        }
        .mc-subpanel h3 {
            margin: 0 0 8px;
            font-size: 11px;
            font-weight: 700;
            color: #90a7c3;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .task-list, .approval-list, .timeline-list, .blocked-list, .audit-list, .execution-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
            min-width: 0;
        }
        .task-item, .approval-item, .timeline-item, .blocked-item, .audit-item, .execution-item {
            display: grid;
            gap: 10px;
            align-items: center;
            border: 1px solid rgba(0, 242, 255, 0.18);
            border-radius: 4px;
            background: rgba(6, 16, 28, 0.75);
            padding: 8px 9px;
            min-width: 0;
            font-size: 11px;
        }
        .task-item { grid-template-columns: 72px minmax(0, 1fr) auto auto; }
        .approval-item { grid-template-columns: 72px minmax(0, 1fr) auto; }
        .timeline-item { grid-template-columns: 72px minmax(0, 1fr) auto auto; }
        .blocked-item { grid-template-columns: 72px minmax(0, 1fr) minmax(0, 1.4fr) auto; }
        .audit-item, .execution-item { grid-template-columns: auto minmax(0, 1fr) auto; }
        .task-id, .approval-task, .timeline-task, .blocked-task { font-family: ui-monospace, monospace; color: #84a5bf; }
        .task-name, .approval-step, .timeline-step, .blocked-step, .audit-command, .exec-command {
            min-width: 0;
            color: #dcecff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .blocked-error {
            min-width: 0;
            color: #b8d0e7;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .timeline-duration, .task-steps {
            color: #9ab7d3;
            font-family: ui-monospace, monospace;
            font-size: 10px;
            white-space: nowrap;
        }
        .task-approval {
            color: #ffc857;
            font-size: 12px;
            line-height: 1;
        }
        .task-status, .approval-risk, .timeline-event, .blocked-risk, .audit-status, .exec-status {
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            text-transform: uppercase;
            font-weight: 700;
            white-space: nowrap;
        }
        .task-status.active, .timeline-event.executing, .exec-status.executed { color: #00ff9f; background: rgba(0, 255, 159, 0.12); }
        .task-status.paused, .approval-risk.medium, .blocked-risk.medium, .audit-status.dry_run { color: #ffc857; background: rgba(255, 200, 87, 0.12); }
        .task-status.completed, .timeline-event.validated { color: #00f2ff; background: rgba(0, 242, 255, 0.12); }
        .approval-risk.high, .blocked-risk.high, .timeline-event.failed, .audit-status.blocked, .exec-status.blocked { color: #ff5f7a; background: rgba(255, 95, 122, 0.12); }
        .empty-state {
            border: 1px dashed rgba(0, 242, 255, 0.18);
            border-radius: 4px;
            padding: 10px;
            text-align: center;
            color: #8fa3be;
            font-size: 11px;
        }

        .workflow-steps {
            display: grid;
            grid-template-columns: repeat(8, minmax(0, 1fr));
            gap: 7px;
            min-width: 0;
        }
        .workflow-step {
            border: 1px solid rgba(0, 242, 255, 0.2);
            border-radius: 4px;
            background: rgba(6, 16, 28, 0.74);
            color: #c8e9ff;
            font-size: 10px;
            font-weight: 600;
            padding: 7px 4px;
            text-align: center;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }
        .mc-meta-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            min-width: 0;
        }
        .focus-card {
            border: 1px solid rgba(0, 242, 255, 0.2);
            border-radius: 4px;
            background: rgba(7, 18, 31, 0.8);
            padding: 10px 11px;
            min-width: 0;
        }
        .focus-card h3 { margin: 0 0 7px; font-size: 12px; color: #b7edff; letter-spacing: 0.03em; }
        .focus-card p { margin: 0 0 7px; font-size: 11px; line-height: 1.5; color: #a8bdd7; overflow-wrap: anywhere; }
        .focus-card .focus-meta { color: #8ca5c1; margin: 0; }

        .operation-focus-panel {
            border: 1px solid rgba(0, 242, 255, 0.2);
            border-radius: 4px;
            background:
                linear-gradient(135deg, rgba(0, 242, 255, 0.08), transparent 42%),
                rgba(7, 18, 31, 0.88);
            padding: 14px;
            min-width: 0;
            display: grid;
            gap: 14px;
        }
        .operation-focus-head {
            display: flex;
            gap: 10px;
            align-items: flex-start;
        }
        .operation-live-dot {
            width: 10px;
            height: 10px;
            margin-top: 4px;
            border-radius: 999px;
            background: #00ff9f;
            box-shadow: 0 0 16px rgba(0, 255, 159, 0.45);
            animation: operationPulse 2.2s ease-in-out infinite;
        }
        @keyframes operationPulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.55; transform: scale(0.82); }
        }
        .operation-focus-head h3 {
            margin: 0 0 5px;
            font-size: 16px;
            color: #dff8ff;
            letter-spacing: 0.04em;
        }
        .operation-focus-head p {
            margin: 0;
            color: #94aac4;
            font-size: 12px;
            line-height: 1.45;
        }
        .operation-focus-main {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(180px, 260px);
            gap: 14px;
            align-items: end;
            min-width: 0;
        }
        .operation-label {
            display: block;
            color: #7f99b2;
            font-family: ui-monospace, monospace;
            font-size: 10px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 4px;
        }
        .operation-resource {
            display: block;
            color: #00f2ff;
            font-size: 24px;
            line-height: 1.15;
            overflow-wrap: anywhere;
        }
        .operation-focus-main p {
            margin: 7px 0 0;
            color: #b1c7de;
            font-size: 12px;
            line-height: 1.45;
        }
        .operation-progress {
            display: grid;
            gap: 7px;
        }
        .operation-progress span {
            color: #dff4ff;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .operation-progress small {
            color: #8fa8c4;
            font-family: ui-monospace, monospace;
            font-size: 10px;
        }
        .operation-track {
            height: 8px;
            border-radius: 4px;
            background: rgba(0, 242, 255, 0.12);
            overflow: hidden;
        }
        .operation-fill {
            height: 100%;
            border-radius: 4px;
            background: linear-gradient(90deg, #00f2ff, #00ff9f);
            box-shadow: 0 0 14px rgba(0, 242, 255, 0.35);
        }
        .operation-focus-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
        }
        .operation-focus-grid div {
            border: 1px solid rgba(0, 242, 255, 0.15);
            border-radius: 4px;
            background: rgba(1, 15, 31, 0.72);
            padding: 8px;
            min-width: 0;
        }
        .operation-focus-grid span {
            display: block;
            color: #7f99b2;
            font-size: 10px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 4px;
        }
        .operation-focus-grid strong {
            color: #e6f5ff;
            font-size: 12px;
            overflow-wrap: anywhere;
        }
        .operation-focus-grid .risk-low { color: #00ff9f; }
        .operation-focus-grid .risk-medium { color: #ffc857; }
        .operation-focus-grid .risk-high { color: #ff5f7a; }
        .operation-log-stream {
            display: grid;
            gap: 6px;
            border: 1px solid rgba(0, 242, 255, 0.14);
            border-radius: 4px;
            background: rgba(1, 15, 31, 0.82);
            padding: 10px;
            max-height: 128px;
            overflow: auto;
            color: #9eb9d4;
            font-family: ui-monospace, monospace;
            font-size: 11px;
            line-height: 1.4;
        }

        .mc-guard-strip {
            border: 1px solid rgba(0, 242, 255, 0.2);
            border-radius: 4px;
            background: #0d1c2d;
            padding: 14px;
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 14px;
            align-items: start;
            min-width: 0;
        }
        .mc-guard-strip h3 {
            margin: 0;
            font-size: 12px;
            color: #9cf8ff;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .mc-guard-strip p {
            margin: 5px 0 10px;
            color: #9cb2cc;
            font-size: 11px;
            line-height: 1.45;
        }
        .risk-bars { display: flex; flex-direction: column; gap: 5px; }
        .risk-bar {
            display: grid;
            grid-template-columns: 44px minmax(0, 1fr) 26px;
            gap: 8px;
            align-items: center;
            font-size: 10px;
            color: #b9d6ef;
        }
        .risk-track {
            height: 6px;
            border-radius: 4px;
            background: rgba(0, 242, 255, 0.1);
            overflow: hidden;
        }
        .risk-fill { height: 100%; border-radius: 4px; }
        .risk-fill.safe { background: #00ff9f; }
        .risk-fill.low { background: #00f2ff; }
        .risk-fill.medium { background: #ffc857; }
        .risk-fill.high { background: #ff9f43; }
        .risk-fill.critical { background: #ff5f7a; }
        .health-check-button {
            border: 1px solid rgba(0, 242, 255, 0.32);
            background: rgba(0, 242, 255, 0.08);
            color: #c8f8ff;
            border-radius: 4px;
            padding: 9px 11px;
            font-size: 11px;
            font-weight: 700;
            cursor: pointer;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .health-check-button:hover { background: rgba(0, 242, 255, 0.16); }
        .health-check-logs {
            margin: 0;
            border: 1px solid rgba(0, 242, 255, 0.14);
            border-radius: 4px;
            background: rgba(2, 9, 17, 0.9);
            color: #b8d7ef;
            padding: 8px;
            max-height: 170px;
            overflow: auto;
            white-space: pre-wrap;
            font-size: 11px;
            line-height: 1.4;
        }

        @media (max-width: 1500px) {
            .mc-col-left { grid-column: span 4; }
            .mc-col-center { grid-column: span 5; }
            .mc-col-right { grid-column: span 3; }
            .workflow-steps { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        }
        @media (max-width: 1200px) {
            .mc-dashboard-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); }
            .mc-col-left { grid-column: span 3; }
            .mc-col-center { grid-column: span 3; }
            .mc-col-right { grid-column: span 6; }
            .blocked-item { grid-template-columns: 72px minmax(0, 1fr) auto; }
            .blocked-error { display: none; }
        }
        @media (max-width: 900px) {
            .mc-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .mc-dashboard-grid { grid-template-columns: 1fr; }
            .mc-col-left, .mc-col-center, .mc-col-right { grid-column: span 1; }
            .mc-meta-grid { grid-template-columns: 1fr; }
            .mc-guard-strip { grid-template-columns: 1fr; }
        }
    '''

    extra_js = '''
        <script>
        async function runHealthCheckDashboardV2Task() {
            const response = await fetch("/dashboard-v2/tasks/health-check", { method: "POST" });
            if (!response.ok) {
                alert("Failed to start Health Check Dashboard V2 task.");
                return;
            }
            window.location.reload();
        }
        </script>
    '''

    if use_cyber:
        from apps.shared_layout import render_cyber_layout
        host = controller.system_agent.stats()
        topbar_stats = {
            "cpu": f"{host.get('cpu_percent', 'n/a')}%",
            "memory": f"{host.get('memory_percent', 'n/a')}%",
            "active_tasks": str(stats.get("active", 0)),
            "uptime": str(host.get("uptime", "n/a")),
        }
        return render_cyber_layout(
            "Mission Control",
            "dashboard",
            content,
            extra_css,
            extra_js,
            topbar_stats=topbar_stats,
        )
    return render_layout("ORCHESTRATOR_V1 Mission Control", "dashboard-v2", content, extra_css, extra_js)


@app.post("/dashboard-v2/tasks/health-check")
def run_dashboard_v2_health_check() -> dict[str, Any]:
    # Built-in safe task trigger for Dashboard V2 end-to-end task verification.
    return run_dashboard_v2_health_check_task()


@app.get("/dashboard-v2/report/{script_name}", response_class=HTMLResponse)
def analysis_report_page(script_name: str) -> str:
    """Render readable HTML analysis report page for an incoming script."""
    safe_name = _safe_incoming_script_name(script_name)

    reports_dir = BASE_DIR / "reports" / "analysis"
    if not reports_dir.is_dir():
        return render_layout(
            "Analysis Report - Not Found",
            "dashboard-v2",
            f"""
            <section class="ao-card">
                <h2>Analysis Report Not Found</h2>
                <p>No analysis reports directory found.</p>
                <p>Script: {esc(safe_name)}</p>
                <div class="index-actions">
                    <a class="button" href="/dashboard-v2">Back to Dashboard V2</a>
                </div>
            </section>
            """,
            subtitle=f"Report for {safe_name}"
        )

    reports = sorted(
        reports_dir.glob(f"analysis-{safe_name}-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not reports:
        return render_layout(
            "Analysis Report - Not Found",
            "dashboard-v2",
            f"""
            <section class="ao-card">
                <h2>Analysis Report Not Found</h2>
                <p>No analysis has been performed for this script yet.</p>
                <p>Script: {esc(safe_name)}</p>
                <div class="index-actions">
                    <a class="button" href="/dashboard-v2">Back to Dashboard V2</a>
                </div>
            </section>
            """,
            subtitle=f"Report for {safe_name}"
        )

    try:
        report = json.loads(reports[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return render_layout(
            "Analysis Report - Error",
            "dashboard-v2",
            f"""
            <section class="ao-card">
                <h2>Error Reading Report</h2>
                <p>Failed to parse analysis report: {esc(str(e))}</p>
                <div class="index-actions">
                    <a class="button" href="/dashboard-v2">Back to Dashboard V2</a>
                </div>
            </section>
            """,
            subtitle=f"Report for {safe_name}"
        )

    analysis = report.get("full_analysis", {})
    summary = _generate_analysis_summary(analysis)
    framework = str(summary.get("framework", "standalone"))
    inventory = str(summary.get("inventory", "none"))
    target = str(summary.get("target", "none"))
    database = str(summary.get("database", "none"))
    risk_level = str(summary.get("risk", "low"))
    recommended = str(summary.get("recommended_action", "safe"))

    findings = analysis.get("findings", [])

    risk_color = "var(--ao-green)" if risk_level == "low" else "#fbbf24" if risk_level == "medium" else "var(--ao-danger)"
    recommended_text = {
        "safe": "Ready for staging",
        "manual-sql": "SQL requires manual review before staging",
        "review-required": "Risk detected - manual review required",
        "adaptation-needed": "Framework adaptation required for QBCore"
    }.get(recommended, recommended)

    findings_html = ""
    for f in findings:
        # Keep CSS class constrained to known values; escape user-controlled display fields.
        severity_raw = str(f.get("severity", "info")).lower()
        severity_class = severity_raw if severity_raw in {"high", "medium", "warning", "info"} else "info"
        severity_label = severity_raw.upper()
        category = str(f.get("category", "unknown"))
        findings_html += f"""
        <div class="finding-item {severity_class}">
            <span class="finding-severity">{esc(severity_label)}</span>
            <span class="finding-category">[{esc(category)}]</span>
            <span class="finding-message">{esc(f.get("message", ""))}</span>
        </div>
        """

    dependencies = analysis.get("dependencies", [])
    deps_html = "".join(f"<li>{esc(d)}</li>" for d in dependencies) if dependencies else "<li>No dependencies detected</li>"

    sql_files = analysis.get("sql_files", [])
    sql_html = "".join(f"<li>{esc(f)}</li>" for f in sql_files) if sql_files else "<li>No SQL files detected</li>"

    content = f"""
    <section class="ao-card">
        <div class="report-header">
            <h2>Analysis Report: {esc(safe_name)}</h2>
            <p class="report-meta">Analyzed: {esc(report.get("analyzed_at", "unknown"))}</p>
        </div>

        <div class="report-badges">
            <span class="badge framework">{esc(framework)}</span>
            <span class="badge inventory">{esc(inventory)}</span>
            <span class="badge target">{esc(target)}</span>
            <span class="badge database">{esc(database)}</span>
            <span class="badge risk" style="background:{risk_color}20;color:{risk_color};border-color:{risk_color}">Risk: {esc(risk_level)}</span>
        </div>

        <div class="report-section">
            <h3>Recommended Action</h3>
            <p class="recommended-action">{esc(recommended_text)}</p>
        </div>

        <div class="report-section">
            <h3>Dependencies</h3>
            <ul class="report-list">{deps_html}</ul>
        </div>

        <div class="report-section">
            <h3>SQL Files</h3>
            <ul class="report-list">{sql_html}</ul>
        </div>

        <div class="report-section">
            <h3>Findings ({len(findings)})</h3>
            <div class="findings-list">{findings_html}</div>
        </div>

        <div class="report-section">
            <h3>Files Scanned</h3>
            <p>{report.get("files_count", len(analysis.get("files", [])))} files scanned</p>
        </div>

        <div class="report-actions">
            <a class="button" href="/dashboard-v2">Back to Dashboard V2</a>
            <a class="button secondary" href="/upload">Upload New Script</a>
        </div>
    </section>

    <style>
        .report-header {{ margin-bottom: 20px; }}
        .report-header h2 {{ margin: 0 0 8px; }}
        .report-meta {{ color: var(--ao-muted); font-size: 13px; }}
        .report-badges {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }}
        .badge {{ padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 700; border: 1px solid; }}
        .badge.framework {{ background: rgba(167, 139, 250, 0.15); color: #a78bfa; border-color: rgba(167, 139, 250, 0.3); }}
        .badge.inventory {{ background: rgba(52, 211, 153, 0.15); color: #34d399; border-color: rgba(52, 211, 153, 0.3); }}
        .badge.target {{ background: rgba(251, 191, 36, 0.15); color: #fbbf24; border-color: rgba(251, 191, 36, 0.3); }}
        .badge.database {{ background: rgba(96, 165, 250, 0.15); color: #60a5fa; border-color: rgba(96, 165, 250, 0.3); }}
        .badge.risk {{ border-width: 2px; }}
        .report-section {{ margin-bottom: 24px; padding: 16px; background: rgba(2, 6, 23, 0.3); border-radius: 8px; }}
        .report-section h3 {{ margin: 0 0 12px; font-size: 15px; color: var(--ao-cyan); }}
        .report-list {{ list-style: none; padding: 0; margin: 0; }}
        .report-list li {{ padding: 4px 0; color: var(--ao-muted); font-size: 13px; }}
        .recommended-action {{ font-size: 14px; font-weight: 600; color: var(--ao-text); }}
        .findings-list {{ display: flex; flex-direction: column; gap: 8px; }}
        .finding-item {{ padding: 10px; border-radius: 6px; background: rgba(2, 6, 23, 0.4); font-size: 13px; }}
        .finding-item.high {{ border-left: 3px solid var(--ao-danger); }}
        .finding-item.medium {{ border-left: 3px solid #fbbf24; }}
        .finding-item.warning {{ border-left: 3px solid #fbbf24; }}
        .finding-item.info {{ border-left: 3px solid var(--ao-cyan); }}
        .finding-severity {{ font-weight: 700; margin-right: 8px; }}
        .finding-item.high .finding-severity {{ color: var(--ao-danger); }}
        .finding-item.medium .finding-severity, .finding-item.warning .finding-severity {{ color: #fbbf24; }}
        .finding-item.info .finding-severity {{ color: var(--ao-cyan); }}
        .finding-category {{ color: var(--ao-soft); margin-right: 8px; }}
        .finding-message {{ color: var(--ao-muted); }}
        .report-actions {{ display: flex; gap: 12px; margin-top: 24px; }}
    </style>
    """

    return render_layout(
        f"Analysis Report - {safe_name}",
        "dashboard-v2",
        content,
        subtitle=f"Report for {safe_name}"
    )


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


def app_view_html(title: str, active: str, content: str, script: str = "", subtitle: str = "") -> str:
    extra_css = """
      :root {
        --bg: var(--ao-bg);
        --panel: var(--ao-panel);
        --border: var(--ao-border);
        --border-strong: var(--ao-border-strong);
        --text: var(--ao-text);
        --muted: var(--ao-muted);
        --soft: var(--ao-soft);
        --cyan: var(--ao-cyan);
        --blue: var(--ao-blue);
        --green: var(--ao-green);
        --danger: var(--ao-danger);
      }

      button,
      input,
      select,
      textarea { font: inherit; }

      .glass,
      .command-card,
      .logs-panel,
      .agent-panel,
      .index-card,
      .empty-state {
        position: relative;
        overflow: hidden;
        border: 1px solid var(--ao-border);
        border-radius: 8px;
        background:
          linear-gradient(180deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.025)),
          var(--ao-panel);
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.07);
        backdrop-filter: blur(18px);
      }

      .command-card,
      .logs-panel,
      .agent-panel,
      .index-card,
      .empty-state {
        margin-bottom: 14px;
        padding: 16px;
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 14px;
        color: var(--ao-muted);
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 0.04em;
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

      .button,
      .command-card a.button,
      .registry-actions a,
      .index-actions a,
      .agent-actions a {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 38px;
        border: 1px solid rgba(0, 212, 255, 0.34);
        border-radius: 8px;
        padding: 8px 12px;
        background: rgba(16, 36, 58, 0.9);
        color: var(--ao-text);
        cursor: pointer;
        font-weight: 800;
        text-decoration: none;
        overflow-wrap: anywhere;
      }

      .button:hover,
      .registry-actions a:hover,
      .index-actions a:hover,
      .agent-actions a:hover {
        background: rgba(22, 52, 83, 0.95);
        text-decoration: none;
      }

      .button.secondary,
      .registry-actions a.secondary,
      .index-actions a.secondary,
      .agent-actions a.secondary {
        border-color: rgba(110, 203, 255, 0.22);
        background: rgba(2, 6, 23, 0.34);
        color: var(--ao-muted);
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
        border-radius: 8px;
        padding: 0 14px;
        background: rgba(2, 6, 23, 0.48);
        color: var(--ao-text);
        outline: none;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 14px;
      }

      .terminal-container {
        display: grid;
        gap: 0;
        border: 1px solid var(--ao-border-strong);
        border-radius: 12px;
        overflow: hidden;
        background: rgba(2, 6, 23, 0.5);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
      }

      .terminal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 14px;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.03));
        border-bottom: 1px solid var(--ao-border);
      }

      .terminal-title {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--ao-text);
        font-size: 14px;
        font-weight: 600;
      }

      .terminal-icon {
        color: var(--ao-cyan);
        font-size: 16px;
      }

      .terminal-dots {
        display: flex;
        gap: 6px;
      }

      .terminal-dots span {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--ao-soft);
      }

      .terminal-dots span:first-child { background: #ff5f56; }
      .terminal-dots span:nth-child(2) { background: #ffbd2e; }
      .terminal-dots span:nth-child(3) { background: #27c93f; }

      .terminal-body {
        padding: 16px;
      }

      .terminal-body .command-form {
        display: flex;
        align-items: center;
        gap: 10px;
        background: rgba(2, 6, 23, 0.6);
        border: 1px solid var(--ao-border);
        border-radius: 8px;
        padding: 8px 12px;
      }

      .terminal-prompt {
        color: var(--ao-cyan);
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 15px;
        font-weight: 700;
      }

      .terminal-body .command-input {
        border: none;
        background: transparent;
        min-height: 36px;
        padding: 0 8px;
      }

      .terminal-run {
        min-height: 36px;
        padding: 0 14px;
        font-size: 13px;
      }

      .terminal-output-wrapper {
        margin-top: 14px;
        border: 1px solid var(--ao-border);
        border-radius: 8px;
        overflow: hidden;
      }

      .terminal-output {
        padding: 14px;
        background: rgba(2, 6, 23, 0.7);
        color: var(--ao-muted);
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 13px;
        line-height: 1.5;
        min-height: 120px;
        max-height: 400px;
        overflow-y: auto;
      }

      .examples-label {
        display: block;
        margin-bottom: 8px;
        color: var(--ao-soft);
        font-size: 12px;
      }

      .command-output,
      .examples {
        margin-top: 12px;
        padding: 12px;
        border: 1px solid rgba(148, 163, 184, 0.14);
        border-radius: 8px;
        background: rgba(2, 6, 23, 0.36);
        color: var(--ao-muted);
        font-size: 13px;
        line-height: 1.45;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }

      .log-stream {
        display: grid;
        gap: 8px;
        max-height: calc(100vh - 185px);
        overflow: auto;
        padding: 12px;
        border: 1px solid rgba(148, 163, 184, 0.13);
        border-radius: 8px;
        background: rgba(2, 6, 23, 0.34);
        color: var(--ao-muted);
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 12px;
        line-height: 1.55;
      }

      .logs-container {
        display: grid;
        gap: 12px;
      }

      .logs-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 16px;
        border: 1px solid var(--ao-border);
        border-radius: 10px;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.02));
      }

      .logs-title {
        display: flex;
        align-items: center;
        gap: 10px;
        color: var(--ao-text);
        font-size: 16px;
        font-weight: 600;
      }

      .logs-icon {
        font-size: 18px;
      }

      .logs-badge {
        padding: 2px 8px;
        border-radius: 999px;
        background: rgba(0, 212, 255, 0.15);
        color: var(--ao-cyan);
        font-size: 12px;
        font-weight: 700;
      }

      .logs-status {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--ao-soft);
        font-size: 13px;
      }

      .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--ao-green);
        animation: pulse 2s infinite;
      }

      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
      }

      .logs-footer {
        display: flex;
        justify-content: space-between;
        padding: 8px 4px;
        color: var(--ao-soft);
        font-size: 12px;
      }

      .logs-info {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      .log-line {
        display: grid;
        grid-template-columns: 96px 150px 86px minmax(0, 1fr);
        gap: 12px;
        align-items: baseline;
      }

      .log-time { color: var(--ao-soft); }
      .log-source { color: var(--ao-blue); }
      .log-level { color: var(--ao-soft); font-weight: 700; }
      .log-line.warning .log-level,
      .log-line.warning .log-message { color: #facc15; }
      .log-line.error .log-level,
      .log-line.error .log-message { color: var(--ao-danger); }

      .agent-grid,
      .index-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
      }

      .agent-panel h2,
      .index-card h2,
      .empty-state h2 {
        margin: 0 0 7px;
        font-size: 18px;
        letter-spacing: 0;
      }

      .agent-panel p,
      .index-card p,
      .empty-state p {
        margin: 0;
        color: var(--ao-muted);
        line-height: 1.5;
        overflow-wrap: anywhere;
      }

      .agent-actions,
      .index-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 9px;
        margin-top: 14px;
      }

      .agent-status {
        justify-self: start;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 999px;
        padding: 3px 8px;
        color: var(--ao-soft);
        font-size: 10px;
        font-weight: 850;
        line-height: 1.2;
      }

      .agent-status.online {
        border-color: rgba(55, 214, 122, 0.32);
        color: var(--ao-green);
        background: rgba(21, 128, 61, 0.12);
      }

      .agent-status.local-only,
      .agent-status.cli,
      .agent-status.no-ui {
        border-color: rgba(125, 211, 252, 0.28);
        color: var(--ao-blue);
        background: rgba(14, 165, 233, 0.1);
      }

      .agent-status.offline,
      .agent-status.service-missing {
        border-color: rgba(255, 99, 112, 0.3);
        color: var(--ao-danger);
        background: rgba(127, 29, 29, 0.12);
      }

      .safety-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 14px;
      }

      .status-row {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 10px;
        align-items: start;
        border: 1px solid rgba(125, 211, 252, 0.16);
        border-radius: 8px;
        padding: 10px;
        background: rgba(2, 6, 23, 0.28);
      }

      .status-row > span {
        width: 12px;
        height: 12px;
        margin-top: 4px;
        border-radius: 999px;
        background: var(--ao-green);
        box-shadow: 0 0 14px rgba(55, 214, 122, 0.28);
      }

      .status-row.warn > span {
        background: #fbbf24;
        box-shadow: 0 0 14px rgba(251, 191, 36, 0.22);
      }

      .status-row strong {
        display: block;
        color: var(--ao-text);
        font-size: 13px;
      }

      .status-row small {
        display: block;
        margin-top: 2px;
        color: var(--ao-muted);
        line-height: 1.4;
      }

      .subtle-id {
        color: var(--ao-soft);
        font-size: 12px;
        overflow-wrap: anywhere;
      }

      .card-title-row {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 7px;
      }

      .card-title-row h2 {
        margin: 0;
      }

      .status-pill {
        display: inline-flex;
        align-items: center;
        min-height: 24px;
        border: 1px solid rgba(148, 163, 184, 0.22);
        border-radius: 999px;
        padding: 3px 8px;
        color: var(--ao-muted);
        background: rgba(15, 23, 42, 0.28);
        font-size: 11px;
        font-weight: 850;
        white-space: nowrap;
      }

      .status-pill.ok {
        border-color: rgba(55, 214, 122, 0.32);
        color: var(--ao-green);
        background: rgba(21, 128, 61, 0.12);
      }

      .status-pill.warn {
        border-color: rgba(251, 191, 36, 0.34);
        color: #fbbf24;
        background: rgba(146, 64, 14, 0.12);
      }

      .status-pill.danger {
        border-color: rgba(255, 99, 112, 0.34);
        color: var(--ao-danger);
        background: rgba(127, 29, 29, 0.12);
      }

      .report-view pre,
      .file-list-panel {
        max-height: 58vh;
        overflow: auto;
        border: 1px solid rgba(148, 163, 184, 0.14);
        border-radius: 8px;
        padding: 12px;
        background: rgba(2, 6, 23, 0.36);
        color: var(--ao-muted);
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }

      .file-list-panel {
        margin: 0;
        line-height: 1.7;
      }

      @media (max-width: 900px) {
        .agent-grid,
        .index-grid,
        .safety-grid,
        .command-form,
        .log-line { grid-template-columns: 1fr; }
      }
    """
    try:
        from apps.shared_layout import render_cyber_layout
        shell_active = "dashboard" if active == "dashboard-v2" else active
        host = controller.system_agent.stats()
        topbar_stats = {
            "cpu": f"{host.get('cpu_percent', 'n/a')}%",
            "memory": f"{host.get('memory_percent', 'n/a')}%",
            "active_tasks": str(host.get("tasks", "--")),
            "uptime": str(host.get("uptime", "n/a")),
        }
        return render_cyber_layout(
            title,
            shell_active,
            content,
            extra_css=extra_css,
            script=script,
            topbar_stats=topbar_stats,
        )
    except ImportError:
        return render_layout(title, active, content, extra_css=extra_css, script=script, subtitle=subtitle)


@app.get("/commands", response_class=HTMLResponse)
def commands_page() -> str:
    content = """
      <div class="terminal-container">
        <div class="terminal-header">
          <span class="terminal-title"><span class="terminal-icon">❯</span> Command Center</span>
          <span class="terminal-dots"><span></span><span></span><span></span></span>
        </div>
        <section class="terminal-body glass" aria-label="Command workspace">
          <form class="command-form" id="command-form">
            <span class="terminal-prompt">$</span>
            <input class="command-input" id="command-input" type="text" placeholder="Type a command..." autocomplete="off">
            <button class="button terminal-run" type="submit">Run</button>
          </form>
          <div class="examples" id="command-examples">
            <span class="examples-label">Quick commands:</span>
            <button class="button secondary" type="button" data-command="/system health">/system health</button>
            <button class="button secondary" type="button" data-command="/git status">/git status</button>
            <button class="button secondary" type="button" data-command="/git push message">/git push message</button>
            <button class="button secondary" type="button" data-command="/git branch feature/name">/git branch</button>
            <button class="button secondary" type="button" data-command="/code plan request">/code plan</button>
          </div>
          <div class="terminal-output-wrapper">
            <div class="terminal-output" id="command-output" aria-live="polite">Command response will appear here.</div>
          </div>
        </section>
      </div>
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

      <div class="terminal-container">
        <div class="terminal-header">
          <span class="terminal-title"><span class="terminal-icon">⚡</span> Ops Command Center</span>
          <span class="terminal-dots"><span></span><span></span><span></span></span>
        </div>
        <div class="terminal-body">
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
        </div>
      </div>
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
    agent_filters = [
        ("system_watcher", "system_watcher"),
        ("self_healing_agent", "self_healing_agent"),
        ("coding_agent", "coding_agent"),
        ("planner_agent", "planner_agent"),
        ("builder_agent", "builder_agent"),
    ]
    agent_checks = "".join(
        f"""
        <label class="agent-check-row">
          <input class="agent-check" type="checkbox" value="{esc(value)}" checked>
          <span>{esc(label)}</span>
        </label>
        """
        for value, label in agent_filters
    )
    known_sources_json = json.dumps([value for value, _label in agent_filters])
    content = f"""
      <section class="logs-workspace">
        <article class="log-terminal">
          <header class="terminal-head">
            <div>
              <span class="terminal-kicker">AGENT_LOG_STREAM</span>
              <h1>System Logs</h1>
            </div>
            <div class="terminal-actions">
              <button class="button secondary" type="button" id="clearBuffer">Clear Buffer</button>
              <button class="button" type="button" id="exportCsv">Export CSV</button>
            </div>
          </header>
          <div class="command-search">
            <span>$</span>
            <input id="logSearch" type="search" autocomplete="off" placeholder="search /agent-logs --message error --source planner_agent">
          </div>
          <div class="terminal-table">
            <div class="terminal-table-head">
              <span>UTC_TIME</span><span>AGENT</span><span>LEVEL</span><span>EVENT</span>
            </div>
            <div class="terminal-stream" id="log-stream" role="log" aria-live="polite"></div>
          </div>
        </article>

        <aside class="log-filter-rail">
          <div class="filter-head">
            <h2>Filters</h2>
            <span id="filterCount">0 active</span>
          </div>
          <section class="filter-section">
            <h3>Agents</h3>
            <div class="agent-checks">{agent_checks}</div>
          </section>
          <section class="filter-section">
            <h3>Date Range</h3>
            <label class="date-field">Start<input id="dateStart" type="datetime-local"></label>
            <label class="date-field">End<input id="dateEnd" type="datetime-local"></label>
          </section>
          <section class="log-stat-grid" aria-label="Log counters">
            <article class="log-stat"><span>Ingestion</span><strong id="metric-ingestion">0</strong></article>
            <article class="log-stat warn"><span>Warnings</span><strong id="metric-warning">0</strong></article>
            <article class="log-stat danger"><span>Errors</span><strong id="metric-error">0</strong></article>
          </section>
          <button class="button apply-filters" type="button" id="applyFilters">Apply Filters</button>
        </aside>

        <footer class="log-status-strip">
          <span>ROWS <strong id="statusRows">0</strong></span>
          <span>LAST_REFRESH <strong id="statusLastRefresh">--</strong></span>
          <span>SOURCE <strong>/agent-logs</strong></span>
          <span>POLL <strong>3000ms</strong></span>
        </footer>
      </section>
    """
    script = """
      <script>
        const logStream = document.getElementById("log-stream");
        const searchInput = document.getElementById("logSearch");
        const dateStartInput = document.getElementById("dateStart");
        const dateEndInput = document.getElementById("dateEnd");
        const knownSources = new Set(KNOWN_SOURCES_PLACEHOLDER);
        let allEntries = [];
        let clearedAt = 0;
        let appliedFilters = { query: "", sources: new Set(KNOWN_SOURCES_PLACEHOLDER), start: "", end: "" };

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
          if (level === "warning" || String(entry.message || "").startsWith("WARNING:")) return "warning";
          if (level === "error" || String(entry.message || "").startsWith("ERROR:")) return "error";
          return "info";
        }

        function formatLogTime(value) {
          const date = value ? new Date(value) : new Date();
          if (Number.isNaN(date.getTime())) return "--";
          return date.toISOString().replace("T", " ").slice(0, 19);
        }

        function parseFilterDate(value) {
          if (!value) return null;
          const date = new Date(value);
          return Number.isNaN(date.getTime()) ? null : date;
        }

        function activeSourcesFromUi() {
          return new Set(Array.from(document.querySelectorAll(".agent-check:checked")).map((el) => el.value));
        }

        function filteredEntries() {
          const query = appliedFilters.query.toLowerCase();
          const start = parseFilterDate(appliedFilters.start);
          const end = parseFilterDate(appliedFilters.end);
          return allEntries.filter((entry) => {
            const src = String(entry.source || "agent");
            if (knownSources.has(src) && !appliedFilters.sources.has(src)) return false;
            const date = entry.timestamp ? new Date(entry.timestamp) : null;
            if (start && date && date < start) return false;
            if (end && date && date > end) return false;
            if (query) {
              const haystack = [src, normalizeLogLevel(entry), entry.message || ""].join(" ").toLowerCase();
              if (!haystack.includes(query)) return false;
            }
            return true;
          });
        }

        function updateMetrics(entries) {
          const warning = entries.filter((e) => normalizeLogLevel(e) === "warning").length;
          const error = entries.filter((e) => normalizeLogLevel(e) === "error").length;
          document.getElementById("metric-ingestion").textContent = String(allEntries.length);
          document.getElementById("metric-warning").textContent = String(warning);
          document.getElementById("metric-error").textContent = String(error);
          document.getElementById("statusRows").textContent = String(entries.length);
          document.getElementById("filterCount").textContent = String(entries.length) + " rows";
        }

        function renderLogs() {
          const entries = filteredEntries().slice(-160);
          if (!entries.length) {
            logStream.innerHTML = '<div class="log-row empty"><span>--</span><span>logs</span><span><span class="log-level-pill info">INFO</span></span><span class="log-message">No logs match current filters.</span></div>';
            updateMetrics(entries);
            return;
          }
          logStream.innerHTML = entries.map((entry) => {
            const level = normalizeLogLevel(entry);
            return '<div class="log-row ' + level + '"><span>' + escapeHtml(formatLogTime(entry.timestamp)) + '</span><span>' + escapeHtml(entry.source || "agent") + '</span><span><span class="log-level-pill ' + level + '">' + level.toUpperCase() + '</span></span><span class="log-message">' + escapeHtml(entry.message || "") + '</span></div>';
          }).join("");
          updateMetrics(entries);
          logStream.scrollTop = logStream.scrollHeight;
        }

        function applyFilters() {
          appliedFilters = {
            query: searchInput ? searchInput.value.trim() : "",
            sources: activeSourcesFromUi(),
            start: dateStartInput ? dateStartInput.value : "",
            end: dateEndInput ? dateEndInput.value : ""
          };
          renderLogs();
        }

        async function refreshLogs() {
          try {
            const response = await fetch("/agent-logs?limit=120", { cache: "no-store" });
            if (!response.ok) throw new Error("Log request failed");
            const data = await response.json();
            const logs = Array.isArray(data.logs) ? data.logs : [];
            allEntries = clearedAt ? logs.filter((entry) => {
              const date = entry.timestamp ? new Date(entry.timestamp) : null;
              return date && date.getTime() > clearedAt;
            }) : logs;
            document.getElementById("statusLastRefresh").textContent = new Date().toISOString().slice(11, 19) + " UTC";
            renderLogs();
          } catch (_) {
            allEntries = [{ source: "logs", level: "error", message: "Log refresh failed.", timestamp: new Date().toISOString() }];
            renderLogs();
          }
        }

        function csvEscape(value) {
          const text = String(value ?? "");
          return '"' + text.replaceAll('"', '""') + '"';
        }

        function exportCsv() {
          const rows = filteredEntries();
          const csv = ["timestamp,source,level,message"].concat(rows.map((entry) => [
            entry.timestamp || "",
            entry.source || "agent",
            normalizeLogLevel(entry),
            entry.message || ""
          ].map(csvEscape).join(","))).join("\\n");
          const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = "agent-logs.csv";
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
        }

        document.getElementById("applyFilters")?.addEventListener("click", applyFilters);
        document.getElementById("exportCsv")?.addEventListener("click", exportCsv);
        document.getElementById("clearBuffer")?.addEventListener("click", () => {
          clearedAt = Date.now();
          allEntries = [];
          renderLogs();
        });
        searchInput?.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            applyFilters();
          }
        });

        refreshLogs();
        setInterval(refreshLogs, 3000);
      </script>
    """.replace("KNOWN_SOURCES_PLACEHOLDER", known_sources_json)
    try:
        from apps.shared_layout import render_cyber_layout
        host = controller.system_agent.stats()
        return render_cyber_layout(
            "System Logs",
            "logs",
            content,
            extra_css=_logs_page_css(),
            script=script,
            topbar_stats={
                "title": "System Logs",
                "cpu": f"{host.get('cpu_percent', 'n/a')}%",
                "memory": f"{host.get('memory_percent', 'n/a')}%",
                "active_tasks": "logs",
                "uptime": str(host.get("uptime", "n/a")),
            },
        )
    except ImportError:
        return app_view_html("System Logs", "logs", content, script)


def _logs_page_css() -> str:
    return """
      .logs-workspace{
        display:grid;
        grid-template-columns:minmax(0,1fr) 320px;
        grid-template-rows:minmax(0,1fr) auto;
        gap:12px;
        min-width:0;
      }
      .log-terminal,.log-filter-rail,.log-status-strip{
        border:1px solid rgba(0,242,255,.2);
        border-radius:4px;
        background:#0d1c2d;
        min-width:0;
      }
      .log-terminal{
        display:flex;
        flex-direction:column;
        overflow:hidden;
      }
      .terminal-head{
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:12px;
        padding:12px;
        border-bottom:1px solid rgba(0,242,255,.2);
        background:#122131;
      }
      .terminal-kicker{
        display:block;
        margin-bottom:3px;
        color:#00f2ff;
        font-family:'JetBrains Mono',ui-monospace,monospace;
        font-size:10px;
        letter-spacing:.08em;
      }
      .terminal-head h1{
        margin:0;
        color:#e0f4ff;
        font-size:17px;
        letter-spacing:.04em;
      }
      .terminal-actions{
        display:flex;
        flex-wrap:wrap;
        gap:8px;
        justify-content:flex-end;
      }
      .command-search{
        display:grid;
        grid-template-columns:auto minmax(0,1fr);
        gap:8px;
        align-items:center;
        margin:12px;
        border:1px solid rgba(0,242,255,.18);
        border-radius:4px;
        background:#010f1f;
        padding:8px 10px;
      }
      .command-search span{
        color:#00f2ff;
        font-family:'JetBrains Mono',ui-monospace,monospace;
        font-weight:800;
      }
      .command-search input{
        width:100%;
        border:0;
        outline:0;
        background:transparent;
        color:#e0f4ff;
        font-family:'JetBrains Mono',ui-monospace,monospace;
        font-size:12px;
      }
      .terminal-table{
        margin:0 12px 12px;
        border:1px solid rgba(0,242,255,.16);
        border-radius:4px;
        overflow:hidden;
        min-width:0;
      }
      .terminal-table-head,.log-row{
        display:grid;
        grid-template-columns:150px 150px 76px minmax(0,1fr);
        gap:8px;
        align-items:center;
        min-width:0;
      }
      .terminal-table-head{
        background:rgba(0,242,255,.1);
        color:#95f7ff;
        font-size:10px;
        letter-spacing:.08em;
        padding:7px 9px;
        font-family:'JetBrains Mono',ui-monospace,monospace;
      }
      .terminal-stream{
        max-height:calc(100vh - 250px);
        min-height:500px;
        overflow:auto;
        background:#010f1f;
      }
      .log-row{
        border-top:1px solid rgba(0,242,255,.09);
        padding:6px 9px;
        color:#c5ddf4;
        font-family:'JetBrains Mono',ui-monospace,monospace;
        font-size:11px;
        line-height:1.35;
      }
      .log-row.error{color:#ff9ab0}
      .log-row.warning{color:#ffd27a}
      .log-row.empty{color:#7f99b2}
      .log-level-pill{
        display:inline-flex;
        justify-content:center;
        min-width:52px;
        border:1px solid rgba(0,242,255,.18);
        border-radius:4px;
        padding:2px 6px;
        font-size:10px;
        font-weight:800;
      }
      .log-level-pill.error{border-color:rgba(255,95,122,.36);color:#ff8fa7;background:rgba(255,95,122,.12)}
      .log-level-pill.warning{border-color:rgba(255,200,87,.35);color:#ffd27a;background:rgba(255,200,87,.12)}
      .log-level-pill.info{border-color:rgba(0,242,255,.35);color:#8df7ff;background:rgba(0,242,255,.1)}
      .log-message{
        min-width:0;
        overflow-wrap:anywhere;
      }
      .log-filter-rail{
        padding:12px;
        display:flex;
        flex-direction:column;
        gap:12px;
      }
      .filter-head{
        display:flex;
        justify-content:space-between;
        gap:8px;
        align-items:center;
      }
      .filter-head h2,.filter-section h3{
        margin:0;
        color:#93f7ff;
        font-size:12px;
        letter-spacing:.08em;
        text-transform:uppercase;
      }
      .filter-head span{
        color:#7f99b2;
        font-size:11px;
      }
      .filter-section{
        display:grid;
        gap:8px;
        min-width:0;
      }
      .agent-checks{
        display:grid;
        gap:6px;
      }
      .agent-check-row{
        display:grid;
        grid-template-columns:auto minmax(0,1fr);
        gap:8px;
        align-items:center;
        border:1px solid rgba(0,242,255,.14);
        border-radius:4px;
        background:#010f1f;
        padding:7px 8px;
        color:#c8ddf2;
        font-family:'JetBrains Mono',ui-monospace,monospace;
        font-size:11px;
      }
      .agent-check-row input{
        accent-color:#00dbe7;
      }
      .date-field{
        display:grid;
        gap:5px;
        color:#7f99b2;
        font-size:10px;
        letter-spacing:.08em;
        text-transform:uppercase;
      }
      .date-field input{
        width:100%;
        border:1px solid rgba(0,242,255,.18);
        border-radius:4px;
        background:#010f1f;
        color:#e0f4ff;
        min-height:34px;
        padding:6px 8px;
        font-family:'JetBrains Mono',ui-monospace,monospace;
        font-size:11px;
      }
      .log-stat-grid{
        display:grid;
        grid-template-columns:1fr;
        gap:8px;
      }
      .log-stat{
        border:1px solid rgba(0,242,255,.16);
        border-radius:4px;
        background:#122131;
        padding:9px;
      }
      .log-stat span{
        display:block;
        margin-bottom:4px;
        color:#7f99b2;
        font-size:10px;
        letter-spacing:.08em;
        text-transform:uppercase;
      }
      .log-stat strong{
        color:#e0f4ff;
        font-size:18px;
      }
      .log-stat.warn strong{color:#ffc857}
      .log-stat.danger strong{color:#ff5f7a}
      .apply-filters{
        width:100%;
        justify-content:center;
      }
      .log-status-strip{
        grid-column:1 / -1;
        display:flex;
        flex-wrap:wrap;
        justify-content:space-between;
        gap:10px;
        padding:8px 10px;
        color:#7f99b2;
        font-family:'JetBrains Mono',ui-monospace,monospace;
        font-size:11px;
      }
      .log-status-strip strong{
        color:#00f2ff;
      }
      @media (max-width:1200px){
        .logs-workspace{grid-template-columns:1fr}
        .terminal-stream{min-height:420px}
      }
      @media (max-width:760px){
        .terminal-head{display:grid}
        .terminal-actions{justify-content:flex-start}
        .terminal-table-head,.log-row{grid-template-columns:112px 112px 68px minmax(0,1fr)}
      }
    """


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
    online = sum(1 for agent in agents if str(agent.get("status", "")).lower() == "online")
    offline = max(0, len(agents) - online)

    rows = []
    for agent in agents:
        status = str(agent.get("status", "unknown")).lower()
        status_class = "ok" if status == "online" else "danger" if status in {"offline", "stopped", "failed"} else "warn"
        label = str(agent.get("display_name", "agent"))
        route = str(agent.get("url") or "")
        action = (
            f'<a class="button secondary" href="{esc(route)}"'
            + (' target="_blank" rel="noopener noreferrer"' if route.startswith(("http://", "https://")) else "")
            + ">Open</a>"
            if route
            else '<span class="agent-empty">No route</span>'
        )
        rows.append(
            f"""
            <div class="agent-row">
              <span class="agent-name">{esc(label)}</span>
              <span class="agent-type">{esc(agent.get("type", "unknown"))}</span>
              <span class="agent-service">{esc(agent.get("service_name") or "none")}</span>
              <span class="agent-status {status_class}">{esc(status.upper())}</span>
              <span class="agent-action">{action}</span>
            </div>
            """
        )

    content = f"""
      <style>
        .agents-shell {{
          display: grid;
          grid-template-columns: 320px minmax(0, 1fr);
          gap: 10px;
          min-width: 0;
        }}
        .agents-summary, .agents-table {{
          border: 1px solid rgba(0, 242, 255, 0.2);
          border-radius: 4px;
          background: rgba(13, 28, 45, 0.9);
          min-width: 0;
          padding: 10px;
        }}
        .agents-summary h2, .agents-table h2 {{
          margin: 0 0 8px;
          font-size: 13px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: #92f5ff;
        }}
        .summary-grid {{
          display: grid;
          gap: 8px;
        }}
        .summary-item {{
          border: 1px solid rgba(0, 242, 255, 0.16);
          border-radius: 4px;
          background: rgba(4, 12, 21, 0.74);
          padding: 8px;
        }}
        .summary-item span {{
          display: block;
          color: #8da8c4;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          margin-bottom: 4px;
        }}
        .summary-item strong {{ font-size: 18px; color: #dff2ff; }}
        .summary-item strong.ok {{ color: #00ff9f; }}
        .summary-item strong.danger {{ color: #ff5f7a; }}

        .agents-head, .agent-row {{
          display: grid;
          grid-template-columns: minmax(160px, 1.3fr) 90px 110px 100px 92px;
          gap: 8px;
          align-items: center;
          min-width: 0;
        }}
        .agents-head {{
          border: 1px solid rgba(0, 242, 255, 0.2);
          border-radius: 4px;
          background: rgba(0, 242, 255, 0.11);
          color: #94f7ff;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          padding: 7px 8px;
          margin-bottom: 6px;
        }}
        .agent-rows {{
          max-height: 620px;
          overflow: auto;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }}
        .agent-row {{
          border: 1px solid rgba(0, 242, 255, 0.14);
          border-radius: 4px;
          background: rgba(4, 11, 20, 0.76);
          padding: 7px 8px;
          color: #c6dcf4;
          font-size: 11px;
        }}
        .agent-name {{
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          color: #e7f4ff;
          font-weight: 700;
        }}
        .agent-type, .agent-service {{ color: #9ab2cb; text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em; }}
        .agent-status {{
          display: inline-flex;
          justify-content: center;
          border: 1px solid rgba(0, 242, 255, 0.2);
          border-radius: 4px;
          padding: 2px 6px;
          font-size: 10px;
          font-weight: 700;
        }}
        .agent-status.ok {{ color: #00ff9f; border-color: rgba(0, 255, 159, 0.34); background: rgba(0, 255, 159, 0.12); }}
        .agent-status.warn {{ color: #ffc857; border-color: rgba(255, 200, 87, 0.34); background: rgba(255, 200, 87, 0.12); }}
        .agent-status.danger {{ color: #ff5f7a; border-color: rgba(255, 95, 122, 0.34); background: rgba(255, 95, 122, 0.12); }}
        .agent-empty {{ font-size: 10px; color: #7f97af; }}
        .agent-action {{ display: flex; justify-content: flex-end; }}
        @media (max-width: 1200px) {{
          .agents-shell {{ grid-template-columns: 1fr; }}
        }}
        @media (max-width: 900px) {{
          .agents-head, .agent-row {{
            grid-template-columns: minmax(140px, 1fr) 80px 80px 80px 80px;
          }}
        }}
      </style>
      <section class="agents-shell">
        <aside class="agents-summary">
          <h2>Active Agents</h2>
          <div class="summary-grid">
            <div class="summary-item"><span>Total Agents</span><strong>{len(agents)}</strong></div>
            <div class="summary-item"><span>Online</span><strong class="ok">{online}</strong></div>
            <div class="summary-item"><span>Offline</span><strong class="danger">{offline}</strong></div>
          </div>
        </aside>
        <article class="agents-table">
          <h2>Agent Matrix</h2>
          <div class="agents-head">
            <span>Agent</span><span>Type</span><span>Service</span><span>Status</span><span>Action</span>
          </div>
          <div class="agent-rows">
            {"".join(rows)}
          </div>
        </article>
      </section>
    """
    return app_view_html("Active Agents", "agents", content)


def _response_body_text(response: HTMLResponse) -> str:
    return response.body.decode("utf-8") if isinstance(response.body, bytes) else str(response.body)


def _agent_by_display_name(name: str) -> dict[str, Any] | None:
    for agent in agent_registry_snapshot():
        if str(agent.get("display_name", "")) == name:
            return agent
    return None


def _status_badge(label: str, ok: bool, detail: str = "") -> str:
    class_name = "ok" if ok else "warn"
    detail_html = f"<small>{esc(detail)}</small>" if detail else ""
    return f'<div class="status-row {class_name}"><span></span><div><strong>{esc(label)}</strong>{detail_html}</div></div>'


def _agent_status_card(agent: dict[str, Any] | None, label: str) -> str:
    if not agent:
        return _status_badge(f"{label} reachable", False, "Agent registry entry not found.")
    status = str(agent.get("status", "unknown"))
    ok = status == "online"
    service = str(agent.get("service_state", "unknown"))
    detail = f"{status.title()} · service: {service}"
    return _status_badge(f"{label} reachable", ok, detail)


def _direct_service_button(agent: dict[str, Any] | None, label: str) -> str:
    if not agent or not agent.get("direct_service_url"):
        return ""
    return (
        f'<a class="button secondary" href="{esc(agent["direct_service_url"])}" '
        f'target="_blank" rel="noopener noreferrer">Open direct {esc(label)} service</a>'
    )


def _format_timestamp(value: object) -> str:
    if not value:
        return "Unknown time"
    raw = str(value)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _safe_named_item(value: str, label: str = "item") -> str:
    if not SAFE_ITEM_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {label}.")
    return value


def _relative_to_base(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def _safe_resource_name(value: str) -> str:
    return _safe_incoming_script_name(value)


def _incoming_resource_dir(resource_name: str) -> Path:
    return _resolve_incoming_script_dir(resource_name)


def _staging_resource_dir(resource_name: str) -> Path:
    staging_root = (BASE_DIR / "staging").resolve()
    candidate = (staging_root / resource_name).resolve()
    if staging_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Staging path must stay under staging/.")
    return candidate


def _orchestrator_staging_dir(resource_name: str) -> Path:
    orch_root = (BASE_DIR / "orchestrator" / "staging").resolve()
    candidate = (orch_root / resource_name).resolve()
    if orch_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Orchestrator staging path must stay under orchestrator/staging/.")
    return candidate


def _latest_analysis_report_path(resource_name: str) -> Path | None:
    reports_dir = BASE_DIR / "reports" / "analysis"
    if not reports_dir.is_dir():
        return None
    reports = sorted(
        reports_dir.glob(f"analysis-{resource_name}-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


def _patch_plan_json_path(resource_name: str) -> Path | None:
    safe_name = _safe_resource_id(resource_name)
    if not safe_name:
        return None
    path = _safe_patch_plan_path(safe_name)
    return path if path.exists() else None


def _compute_analysis_risk(resource_name: str) -> str:
    report_path = _latest_analysis_report_path(resource_name)
    if not report_path:
        return "unknown"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    summary = _generate_analysis_summary(payload.get("full_analysis", {}))
    return str(summary.get("risk", "unknown"))


def _stage_info_paths(resource_name: str) -> tuple[Path, Path]:
    stage_root = _staging_resource_dir(resource_name)
    orch_root = _orchestrator_staging_dir(resource_name)
    return stage_root / "stage-info.json", orch_root / "stage-info.json"


def _read_stage_info(resource_name: str) -> dict[str, Any] | None:
    stage_info_path, orch_stage_info_path = _stage_info_paths(resource_name)
    for candidate in [orch_stage_info_path, stage_info_path]:
        if not candidate.is_file():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _write_stage_info(resource_name: str, stage_info: dict[str, Any]) -> None:
    stage_info_path, orch_stage_info_path = _stage_info_paths(resource_name)
    stage_info_path.parent.mkdir(parents=True, exist_ok=True)
    orch_stage_info_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(stage_info, indent=2, sort_keys=True)
    stage_info_path.write_text(encoded, encoding="utf-8")
    orch_stage_info_path.write_text(encoded, encoding="utf-8")


def _safe_rel_file_map(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    ignore_rel_paths = {"stage-info.json"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        rel = resolved.relative_to(root.resolve()).as_posix()
        if rel in ignore_rel_paths:
            continue
        h = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                h.update(chunk)
        files[rel] = h.hexdigest()
    return files


def _build_staging_diff(resource_name: str) -> dict[str, Any]:
    incoming_dir = _incoming_resource_dir(resource_name)
    staging_dir = _staging_resource_dir(resource_name)
    if not staging_dir.is_dir():
        raise HTTPException(status_code=404, detail="Staging copy not found")
    incoming_files = _safe_rel_file_map(incoming_dir)
    staging_files = _safe_rel_file_map(staging_dir)

    incoming_set = set(incoming_files.keys())
    staging_set = set(staging_files.keys())
    added = sorted(staging_set - incoming_set)
    deleted = sorted(incoming_set - staging_set)
    changed = sorted(
        rel for rel in (incoming_set & staging_set) if incoming_files.get(rel) != staging_files.get(rel)
    )
    status = "READY" if not (added or deleted or changed) else "MODIFIED"
    return {
        "resource": resource_name,
        "status": status,
        "added_files": added,
        "deleted_files": deleted,
        "changed_files": changed,
        "summary": {
            "added": len(added),
            "deleted": len(deleted),
            "changed": len(changed),
        },
    }


def _safe_workspace_file(relative_path: str, root_name: str) -> Path:
    root = (BASE_DIR / root_name).resolve()
    candidate = (BASE_DIR / relative_path).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=400, detail=f"Path must stay under {root_name}/.")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return candidate


def _badge_class(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ["fail", "error", "blocked", "critical", "high risk"]):
        return "danger"
    if any(word in lowered for word in ["warn", "risk", "review", "manual", "sql"]):
        return "warn"
    if any(word in lowered for word in ["ready", "done", "staged", "ok", "complete"]):
        return "ok"
    return "neutral"


def _status_pill(label: object) -> str:
    text = str(label or "unknown")
    return f'<span class="status-pill {_badge_class(text)}">{esc(text)}</span>'


def _read_text_preview(path: Path, limit: int = 60000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    if len(text) > limit:
        return text[:limit] + "\n\n[Report truncated in UI.]"
    return text


def _report_entries(limit: int = 80) -> list[dict[str, Any]]:
    reports_root = BASE_DIR / "reports"
    if not reports_root.is_dir():
        return []
    files = [
        path
        for path in reports_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".json", ".txt", ".log"}
    ]
    entries: list[dict[str, Any]] = []
    for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        rel = _relative_to_base(path)
        text = ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            pass
        status = "ready"
        if any(token in text.lower() for token in ["failed", "error", "blocked"]):
            status = "needs review"
        elif any(token in text.lower() for token in ["risk", "sql", "manual approval"]):
            status = "review"
        linked_staging = ""
        match = re.search(r"\b(coding-[A-Za-z0-9]+|upload-[A-Za-z0-9]+|planner-[A-Za-z0-9]+)\b", path.name + "\n" + text)
        if match:
            candidate = BASE_DIR / "staging" / match.group(1)
            if candidate.is_dir():
                linked_staging = f"/staging/{match.group(1)}"
        entries.append(
            {
                "name": path.name,
                "path": rel,
                "folder": path.parent.relative_to(reports_root).as_posix() if path.parent != reports_root else "reports",
                "status": status,
                "size": path.stat().st_size,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "view_url": f"/reports/view?path={quote(rel)}",
                "linked_staging": linked_staging,
            }
        )
    return entries


def _incoming_entries(limit: int = 40) -> list[dict[str, Any]]:
    incoming_root = BASE_DIR / "incoming"
    if not incoming_root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(incoming_root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        file_count = sum(1 for _ in path.rglob("*") if _.is_file()) if path.is_dir() else 1
        entries.append(
            {
                "name": path.name,
                "path": _relative_to_base(path),
                "kind": "folder" if path.is_dir() else "file",
                "file_count": file_count,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
        )
    return entries


def _get_incoming_resources_with_analysis(limit: int = 20) -> list[dict[str, Any]]:
    """Get incoming resources with their analysis data if available."""
    incoming_root = BASE_DIR / "incoming"
    reports_dir = BASE_DIR / "reports" / "analysis"
    patch_plan_root = BASE_DIR / "orchestrator" / "archive"

    if not incoming_root.is_dir():
        return []

    resources: list[dict[str, Any]] = []

    for path in sorted(incoming_root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        if not path.is_dir():
            continue

        file_count = sum(1 for _ in path.rglob("*") if _.is_file())
        resource = {
            "name": path.name,
            "path": _relative_to_base(path),
            "file_count": file_count,
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "manifest": None,
            "analyzed": False,
            "analysis": None,
            "has_patch_plan": False,
            "staging": {
                "exists": False,
                "status": "NONE",
                "approved_at": None,
            },
        }

        fxmanifest = path / "fxmanifest.lua"
        resource_lua = path / "__resource.lua"
        if fxmanifest.is_file():
            resource["manifest"] = "fxmanifest.lua"
        elif resource_lua.is_file():
            resource["manifest"] = "__resource.lua"

        if reports_dir.is_dir():
            reports = sorted(
                reports_dir.glob(f"analysis-{path.name}-*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if reports:
                try:
                    report = json.loads(reports[0].read_text(encoding="utf-8"))
                    resource["analyzed"] = True
                    resource["analysis"] = report.get("full_analysis", {})
                    resource["analyzed_at"] = report.get("analyzed_at")
                except (OSError, json.JSONDecodeError):
                    pass

        patch_plan_path = patch_plan_root / path.name / "patch-plan.json"
        if patch_plan_path.is_file():
            resource["has_patch_plan"] = True

        try:
            staging_dir = _staging_resource_dir(path.name)
        except HTTPException:
            staging_dir = None
        if staging_dir and staging_dir.is_dir():
            resource["staging"]["exists"] = True
            stage_info = _read_stage_info(path.name) or {}
            resource["staging"]["status"] = str(stage_info.get("status", "STAGED")).upper()
            resource["staging"]["approved_at"] = stage_info.get("approved_at")

        resources.append(resource)

    return resources


def _upload_jobs(limit: int = 30) -> list[dict[str, Any]]:
    root = BASE_DIR / "reports" / "upload-pipeline"
    if not root.is_dir():
        return []
    jobs: list[dict[str, Any]] = []
    for path in sorted(root.glob("upload-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data["tracker_path"] = _relative_to_base(path)
        data["updated_at"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        jobs.append(data)
    return jobs


def _staging_approval_entries(limit: int = 20) -> list[dict[str, Any]]:
    incoming_root = BASE_DIR / "incoming"
    if not incoming_root.is_dir():
        return []
    approvals: list[dict[str, Any]] = []
    for path in sorted(incoming_root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_dir():
            continue
        stage_info = _read_stage_info(path.name)
        if not stage_info:
            continue
        status = str(stage_info.get("status", "")).upper()
        if status not in {"APPROVED", "REJECTED"}:
            continue
        risk = str(stage_info.get("risk_level", "unknown")).lower()
        approvals.append(
            {
                "task_id": f"staging:{path.name}",
                "step_name": f"{path.name} ({status})",
                "risk_level": risk if risk in {"high", "medium", "low"} else "unknown",
            }
        )
        if len(approvals) >= limit:
            break
    return approvals


def _recent_reports_html(limit: int = 12) -> str:
    reports = _report_entries(limit)
    if not reports:
        return """
          <section class="empty-state">
            <h2>No reports yet</h2>
            <p>Run an upload, review, or explicit AI check to generate a report.</p>
          </section>
        """
    cards = []
    for report in reports:
        staging_link = (
            f'<a class="button secondary" href="{esc(report["linked_staging"])}">Related staging</a>'
            if report.get("linked_staging")
            else ""
        )
        cards.append(
            f"""
            <article class="index-card report-card">
              <div class="card-title-row"><h2>{esc(report["name"])}</h2>{_status_pill(report["status"])}</div>
              <p>{esc(report["folder"])} · {esc(_format_timestamp(report["updated_at"]))} · {esc(report["size"])} bytes</p>
              <p class="subtle-id">{esc(report["path"])}</p>
              <div class="index-actions">
                <a class="button" href="{esc(report["view_url"])}">Open report</a>
                {staging_link}
              </div>
            </article>
            """
        )
    return f'<section class="index-grid" aria-label="Recent reports">{"".join(cards)}</section>'


def _recent_upload_jobs_html(limit: int = 8) -> str:
    jobs = _upload_jobs(limit)
    if not jobs:
        return """
          <section class="empty-state">
            <h2>No uploads yet</h2>
            <p>Drop a script ZIP or folder above to start the staging-only pipeline.</p>
          </section>
        """
    cards = []
    for job in jobs:
        task_id = str(job.get("task_id", ""))
        incoming_path = str(job.get("incoming_path") or "")
        actions = []
        if job.get("plan_url"):
            actions.append(f'<a class="button" href="{esc(job["plan_url"])}">Plan</a>')
        if job.get("staging_url"):
            actions.append(f'<a class="button secondary" href="{esc(job["staging_url"])}">Staging</a>')
        if job.get("review_url"):
            actions.append(f'<a class="button secondary" href="{esc(job["review_url"])}">Review</a>')
        actions.append(f'<button class="button secondary ai-check-button" type="button" data-path="{esc(incoming_path)}">Run AI Integration Check</button>')
        cards.append(
            f"""
            <article class="index-card upload-job-card">
              <div class="card-title-row"><h2>{esc(task_id)}</h2>{_status_pill(job.get("status"))}</div>
              <p>{esc(len(job.get("files", [])))} file(s) · {esc(_format_timestamp(job.get("updated_at")))}</p>
              <p class="subtle-id">{esc(incoming_path or job.get("tracker_path", ""))}</p>
              <div class="index-actions">{"".join(actions)}</div>
            </article>
            """
        )
    return f'<section class="index-grid" aria-label="Recent upload jobs">{"".join(cards)}</section>'


def _incoming_index_html(limit: int = 8) -> str:
    entries = _incoming_entries(limit)
    if not entries:
        return """
          <section class="empty-state">
            <h2>No incoming scripts</h2>
            <p>Uploaded raw scripts will appear here before they are planned, staged, and reviewed.</p>
          </section>
        """
    cards = []
    for entry in entries:
        cards.append(
            f"""
            <article class="index-card incoming-card" data-script-name="{esc(entry["name"])}">
              <div class="card-title-row"><h2>{esc(entry["name"])}</h2>{_status_pill(entry["kind"])}</div>
              <p>{esc(entry["file_count"])} file(s) · {esc(_format_timestamp(entry["updated_at"]))}</p>
              <p class="subtle-id">{esc(entry["path"])}</p>
              <div class="analysis-summary" id="analysis-{esc(entry["name"])}"></div>
              <div class="index-actions">
                <button class="button analyze-button" type="button" data-script="{esc(entry["name"])}">Analyze</button>
                <button class="button secondary ai-check-button" type="button" data-path="{esc(str(BASE_DIR / entry["path"]))}">AI Check</button>
              </div>
            </article>
            """
        )
    return f'<section class="index-grid" aria-label="Incoming scripts">{"".join(cards)}</section>'


def _generic_staging_preview_html(task_id: str) -> str:
    task_id = _safe_named_item(task_id, "staging task id")
    staging_root = (BASE_DIR / "staging").resolve()
    path = (staging_root / task_id).resolve()
    if staging_root not in path.parents or not path.is_dir():
        raise HTTPException(status_code=404, detail="Staging folder not found.")
    files = sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix())[:80]
    file_rows = "".join(f"<li><code>{esc(item.relative_to(path).as_posix())}</code></li>" for item in files) or "<li>No files found.</li>"
    preview_parts = []
    for name in ["STAGING_SUMMARY.json", "PATCH_NOTES.md", "DIFF_PREVIEW.patch", "ROLLBACK_NOTES.md"]:
        candidate = path / name
        if candidate.is_file():
            preview_parts.append(f"<h3>{esc(name)}</h3><pre>{esc(_read_text_preview(candidate, 30000))}</pre>")
    preview = "".join(preview_parts) or "<p>No standard staging summary files were found.</p>"
    content = f"""
      <section class="agent-panel">
        <h2>{esc(task_id)}</h2>
        <p>Read-only staging folder preview. Live FiveM resources are not modified from this page.</p>
        <div class="agent-actions">
          <a class="button" href="/staging">Back to Staging</a>
          <a class="button secondary" href="/reviews">Reviews</a>
        </div>
      </section>
      <section class="agent-panel">
        <h2>Files</h2>
        <ul class="file-list-panel">{file_rows}</ul>
      </section>
      <section class="agent-panel report-view">
        <h2>Staging Notes</h2>
        {preview}
      </section>
    """
    return app_view_html("Staging Preview", "staging", content, subtitle=task_id)


def _recent_planner_tasks_html(limit: int = 5) -> str:
    try:
        from apps.planner_agent import app as planner_app

        tasks = planner_app.storage.list_recent("tasks", limit)
    except Exception as error:
        return f"""
          <section class="empty-state">
            <h2>Planner tasks unavailable</h2>
            <p>{esc(error)}</p>
          </section>
        """
    if not tasks:
        return """
          <section class="empty-state">
            <h2>No Planner tasks yet</h2>
            <p>Upload a script to generate a compatibility plan.</p>
            <div class="index-actions"><a class="button" href="/upload">Open Upload Pipeline</a></div>
          </section>
        """
    cards = []
    for task in tasks:
        task_id = str(task.get("id", ""))
        title = task.get("title") or task.get("prompt") or task_id
        status = task.get("status") or "unknown"
        created = _format_timestamp(task.get("created_at") or task.get("updated_at"))
        cards.append(
            f"""
            <article class="index-card">
              <h2>{esc(title)}</h2>
              <p>{esc(status)} · {esc(created)}</p>
              <p class="subtle-id">{esc(task_id)}</p>
              <div class="index-actions">
                <a class="button" href="/tasks/{esc(task_id)}/view">View task</a>
                <a class="button secondary" href="/reports/{esc(task_id)}/view">View report</a>
              </div>
            </article>
            """
        )
    return f'<section class="index-grid" aria-label="Recent Planner tasks">{"".join(cards)}</section>'


def _review_entries() -> list[dict[str, Any]]:
    reviews_root = BASE_DIR / "reports" / "reviews"
    entries: list[dict[str, Any]] = []
    if not reviews_root.is_dir():
        return entries
    for path in sorted(reviews_root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task_id = str(data.get("task_id") or path.stem)
        if not task_id:
            continue
        entries.append(
            {
                "task_id": task_id,
                "task_name": data.get("task_name") or task_id,
                "summary": data.get("summary") or data.get("notes") or "Review report saved.",
                "status": data.get("status") or "warning",
                "created_at": data.get("created_at") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
        )
    return entries


def _review_index_html() -> str:
    reviews = _review_entries()
    if not reviews:
        return """
          <section class="empty-state">
            <h2>No reviews yet</h2>
            <p>No reviews yet. Upload a script or run a coding task to generate one.</p>
            <div class="index-actions">
              <a class="button" href="/upload">Open Upload Pipeline</a>
              <a class="button secondary" href="/reports/daily">Open Daily Coding Digest</a>
            </div>
          </section>
        """
    cards = []
    for review in reviews:
        task_id = str(review["task_id"])
        cards.append(
            f"""
            <article class="index-card">
              <h2>{esc(review["task_name"])}</h2>
              <p>{esc(review["summary"])}</p>
              <p class="subtle-id">{esc(task_id)} · {esc(_format_timestamp(review["created_at"]))} · {esc(str(review["status"]).title())}</p>
              <div class="index-actions">
                <a class="button" href="/review/{esc(task_id)}">Open review</a>
                <a class="button secondary" href="/reports/daily">Daily Coding Digest</a>
              </div>
            </article>
            """
        )
    return f'<section class="index-grid" aria-label="Review reports">{"".join(cards)}</section>'


def _staging_entries() -> list[dict[str, Any]]:
    staging_root = BASE_DIR / "staging"
    entries: list[dict[str, Any]] = []
    if not staging_root.is_dir():
        return entries
    for path in sorted((item for item in staging_root.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime, reverse=True):
        task_id = path.name
        supported = task_id.startswith("coding-")
        summary_path = path / "STAGING_SUMMARY.json"
        summary = "Staging folder ready for review."
        status = "staged"
        if summary_path.is_file():
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                summary = str(data.get("summary") or summary)
                status = str(data.get("status") or status)
            except (OSError, json.JSONDecodeError):
                summary = "Staging summary could not be read."
                status = "needs review"
        entries.append(
            {
                "task_id": task_id,
                "path": path,
                "summary": summary,
                "status": status,
                "supported": supported,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
        )
    return entries


def _staging_index_html() -> str:
    entries = _staging_entries()
    if not entries:
        return """
          <section class="empty-state">
            <h2>No staging folders yet</h2>
            <p>No staging folders are available. Upload a script or run a coding task to create staging output.</p>
            <div class="index-actions">
              <a class="button" href="/upload">Open Upload Pipeline</a>
              <a class="button secondary" href="/reviews">Open Reviews</a>
            </div>
          </section>
        """
    cards = []
    for entry in entries:
        task_id = str(entry["task_id"])
        primary_action = (
            f'<a class="button" href="/staging/{esc(task_id)}">Open staging preview</a>'
            if entry["supported"]
            else '<span class="subtle-id">Preview route not available for this staging folder.</span>'
        )
        cards.append(
            f"""
            <article class="index-card">
              <h2>{esc(task_id)}</h2>
              <p>{esc(entry["summary"])}</p>
              <p class="subtle-id">{esc(str(entry["path"]))} · {esc(str(entry["status"]).title())} · {esc(_format_timestamp(entry["updated_at"]))}</p>
              <div class="index-actions">
                {primary_action}
                <a class="button secondary" href="/reviews">Open Reviews</a>
              </div>
            </article>
            """
        )
    return f'<section class="index-grid" aria-label="Staging folders">{"".join(cards)}</section>'


@app.get("/guide", response_class=HTMLResponse)
def system_guide_page() -> str:
    tabs = [
        ("Dashboard", "Home base for system health, pipeline counts, and next actions."),
        ("Control Panels", "Operational command surfaces and status cards."),
        ("Agents", "Registry of AgentOS services, CLIs, and fallback providers."),
        ("Logs", "Recent operational log stream for debugging."),
        ("Upload Pipeline", "Upload raw FiveM scripts into incoming and start staging-only processing."),
        ("Planner Agent", "Inspects framework, dependencies, SQL, config, client, server, and shared files."),
        ("Coding Agent", "Creates staging-only output and human-readable review material."),
        ("Daily Digest", "Daily coding and review summary."),
        ("Reviews", "Readable risk reports before any human-approved apply step."),
        ("Staging", "Safe generated output folders for inspection and manual testing."),
        ("Ops Cheat Sheet", "Known safe operational commands and reminders."),
        ("Commands", "Interactive command center with approval gates."),
        ("Settings", "Reserved for future UI preferences and integration settings."),
    ]
    tab_cards = "".join(
        f"<article class='guide-card'><h3>{esc(name)}</h3><p>{esc(text)}</p></article>"
        for name, text in tabs
    )
    provider_cards = "".join(
        [
            "<article class='guide-card'><h3>Codex</h3><p>Primary coding agent for repo changes, validation, and playbook updates.</p></article>",
            "<article class='guide-card'><h3>Gemini</h3><p>Cloud fallback for bounded reports and planning when Codex is unavailable.</p></article>",
            "<article class='guide-card'><h3>OpenCode</h3><p>Multi-model fallback coding agent for explicit, scoped tasks using API providers.</p></article>",
            "<article class='guide-card'><h3>Local coder / Ollama</h3><p>Emergency-only and deprecated for normal work on this CPU-only VM.</p></article>",
        ]
    )
    content = f"""
      <style>
        .guide-hero,
        .guide-panel {{
          border: 1px solid var(--ao-border);
          border-radius: 8px;
          background: var(--ao-panel);
          box-shadow: 0 18px 42px rgba(0,0,0,.22);
          margin-bottom: 16px;
          padding: 18px;
        }}
        .guide-hero h2,
        .guide-panel h2 {{ margin: 0 0 8px; }}
        .guide-hero p,
        .guide-panel p {{ color: var(--ao-muted); line-height: 1.55; }}
        .workflow-line {{
          display: grid;
          grid-template-columns: repeat(7, minmax(0, 1fr));
          gap: 8px;
          margin-top: 14px;
        }}
        .workflow-node {{
          min-height: 82px;
          border: 1px solid rgba(125,211,252,.18);
          border-radius: 8px;
          padding: 10px;
          background: rgba(2,6,23,.32);
        }}
        .workflow-node strong {{ display: block; color: var(--ao-text); font-size: 13px; }}
        .workflow-node span {{ display: block; margin-top: 5px; color: var(--ao-muted); font-size: 12px; line-height: 1.35; }}
        .guide-grid {{
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 12px;
        }}
        .guide-card {{
          border: 1px solid rgba(125,211,252,.16);
          border-radius: 8px;
          padding: 12px;
          background: rgba(2,6,23,.28);
        }}
        .guide-card h3 {{ margin: 0 0 6px; font-size: 15px; }}
        .guide-card p {{ margin: 0; font-size: 13px; }}
        @media (max-width: 1100px) {{
          .workflow-line,
          .guide-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}
        @media (max-width: 700px) {{
          .workflow-line,
          .guide-grid {{ grid-template-columns: 1fr; }}
        }}
      </style>
      <section class="guide-hero">
        <h2>AgentOS Script Integration Control Center</h2>
        <p>AgentOS keeps third-party FiveM script intake safe: raw uploads stay in incoming, generated output stays in staging, reports explain risk, and live server actions remain human-approved.</p>
        <div class="workflow-line" aria-label="Script integration workflow">
          <div class="workflow-node"><strong>incoming</strong><span>Raw upload saved.</span></div>
          <div class="workflow-node"><strong>planner</strong><span>Framework and dependency scan.</span></div>
          <div class="workflow-node"><strong>coding</strong><span>Staging-only adaptation.</span></div>
          <div class="workflow-node"><strong>staging</strong><span>Generated files reviewed.</span></div>
          <div class="workflow-node"><strong>review</strong><span>Risks and next action.</span></div>
          <div class="workflow-node"><strong>human approval</strong><span>No automatic live apply.</span></div>
          <div class="workflow-node"><strong>test + git</strong><span>Only after approval.</span></div>
        </div>
      </section>
      <section class="guide-panel">
        <h2>Sidebar tabs</h2>
        <div class="guide-grid">{tab_cards}</div>
      </section>
      <section class="guide-panel">
        <h2>AI provider roles</h2>
        <div class="guide-grid">{provider_cards}</div>
      </section>
      <section class="guide-panel">
        <h2>Safety model</h2>
        <p>No page in AgentOS should edit live FiveM resources, touch qb-core, run SQL, restart services, or push Git automatically. Apply/deploy actions stay disabled or human-approved until testing is intentionally started.</p>
      </section>
    """
    return app_view_html("System Guide", "guide", content, subtitle="How AgentOS routes uploads, staging, reviews, and fallback AI.")


def _upload_safety_checklist_html() -> str:
    planner_agent = _agent_by_display_name("Planner Agent")
    coding_agent = _agent_by_display_name("Coding Agent")
    rows = [
        _status_badge("AgentOS online", True, "Dashboard route is serving this page."),
        _agent_status_card(planner_agent, "Planner Agent"),
        _agent_status_card(coding_agent, "Coding Agent"),
        _status_badge("Staging-only mode active", True, "Pipeline writes incoming, reports, and staging artifacts only."),
        _status_badge("Live FiveM resources will not be modified", True, "No live apply, SQL, Git push, or restart is part of upload."),
    ]
    return f"""
      <section class="safety-checklist" aria-label="Pre-upload safety checklist">
        <div class="safety-head">
          <div>
            <h2>Pre-upload safety</h2>
            <p>Upload testing stays inside AgentOS staging until reviewed.</p>
          </div>
          <span class="safety-pill">Staging only</span>
        </div>
        <div class="safety-grid">{"".join(rows)}</div>
      </section>
    """


@app.get("/planner", response_class=HTMLResponse)
def planner_page() -> str:
    planner_agent = _agent_by_display_name("Planner Agent")
    content = f"""
      <section class="agent-panel">
        <h2>Planner Agent</h2>
        <p>Planner Agent reads incoming FiveM scripts, identifies framework and dependency risks, and writes a staging-only plan before any coding work starts.</p>
        <div class="safety-grid">
          {_agent_status_card(planner_agent, "Planner Agent")}
          {_status_badge("Plan-only mode", True, "No SQL, live resource edits, Git push, or service restart.")}
        </div>
        <div class="agent-actions">
          <a class="button" href="/upload">Open Upload Pipeline</a>
          <a class="button secondary" href="/reports/daily">Daily Coding Digest</a>
          {_direct_service_button(planner_agent, "Planner")}
        </div>
      </section>
      <section class="agent-panel">
        <h2>Recent Planner tasks</h2>
        <p>Open a task to review its plan, findings, report links, and staging-only controls.</p>
      </section>
      {_recent_planner_tasks_html()}
    """
    return app_view_html("Planner Agent", "planner", content, subtitle="Plan incoming scripts before staged coding work.")


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
    coding_agent = _agent_by_display_name("Coding Agent")
    review_count = len(_review_entries())
    staging_count = len(_staging_entries())
    content = f"""
      <section class="agent-panel">
        <h2>Coding Agent</h2>
        <p>Coding Agent turns approved Planner context into staged patch suggestions and human-readable reviews. It does not apply changes to live FiveM resources.</p>
        <div class="safety-grid">
          {_agent_status_card(coding_agent, "Coding Agent")}
          {_status_badge("Staging-only output", True, "Generated files stay under the agents staging and reports folders.")}
        </div>
        <div class="agent-actions">
          <a class="button" href="/reports/daily">Open Daily Coding Digest</a>
          <a class="button secondary" href="/reviews">Reviews</a>
          <a class="button secondary" href="/staging">Staging</a>
          {_direct_service_button(coding_agent, "Coding")}
        </div>
      </section>
      <section class="agent-grid">
        <article class="agent-panel">
          <h2>{review_count} review report(s)</h2>
          <p>Readable safety reviews generated from staged Coding Agent output.</p>
          <div class="agent-actions"><a class="button" href="/reviews">Open Reviews</a></div>
        </article>
        <article class="agent-panel">
          <h2>{staging_count} staging folder(s)</h2>
          <p>Staged output folders waiting for manual or Codex review.</p>
          <div class="agent-actions"><a class="button" href="/staging">Open Staging</a></div>
        </article>
      </section>
    """
    return app_view_html("Coding Agent", "coding", content, subtitle="Staged code suggestions and review output.")


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
    resources = _get_incoming_resources_with_analysis(limit=24)
    tree_items: list[str] = []
    for resource in resources:
        status = "Analyzed" if resource.get("analyzed") else "Pending"
        marker = "READY" if resource.get("has_patch_plan") else status.upper()
        tree_items.append(
            f'<li><span class="file-name">{esc(resource.get("name", "unknown"))}</span>'
            f'<span class="file-meta">{esc(marker)}</span></li>'
        )
    tree_html = "".join(tree_items) or '<li><span class="file-name">No incoming resources</span><span class="file-meta">EMPTY</span></li>'

    op_prompt = BASE_DIR / "orchestrator" / "prompts" / "opencode-next.md"
    codex_prompt = BASE_DIR / "orchestrator" / "prompts" / "codex-audit-next.md"
    health_score = 0
    if op_prompt.exists() and op_prompt.stat().st_size > 0:
        health_score += 50
    if codex_prompt.exists() and codex_prompt.stat().st_size > 0:
        health_score += 50

    analyzed_count = sum(1 for resource in resources if resource.get("analyzed"))
    patch_plan_count = sum(1 for resource in resources if resource.get("has_patch_plan"))
    staged_count = sum(
        1
        for resource in resources
        if isinstance(resource.get("staging"), dict) and resource.get("staging", {}).get("exists")
    )

    prompt_specs = [
        ("opencode", "OPENCODE", BASE_DIR / "orchestrator" / "prompts" / "opencode-next.md", "/api/prompts/opencode-next"),
        ("gemini", "GEMINI", BASE_DIR / "orchestrator" / "prompts" / "gemini-plan-latest.md", ""),
        ("codex", "CODEX", BASE_DIR / "orchestrator" / "prompts" / "codex-audit-next.md", "/api/prompts/codex-audit-next"),
    ]
    prompt_cards: list[str] = []
    for key, label, path, endpoint in prompt_specs:
        exists = path.is_file() and path.stat().st_size > 0
        preview = _read_text_preview(path, 2400) if exists else "Prompt file has not been generated yet."
        updated = _format_timestamp(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()) if exists else "Not generated"
        load_attr = f'data-endpoint="{esc(endpoint)}"' if endpoint else f'data-inline-target="prompt-preview-{esc(key)}"'
        prompt_cards.append(
            f"""
            <article class="prompt-card model-{esc(key)}">
              <div class="prompt-card-head">
                <span class="model-ref">MODEL_REF: {esc(label)}</span>
                <span class="prompt-state {'ready' if exists else 'missing'}">{'READY' if exists else 'MISSING'}</span>
              </div>
              <pre id="prompt-preview-{esc(key)}" class="prompt-preview">{esc(preview)}</pre>
              <div class="prompt-card-foot">
                <span>{esc(updated)}</span>
                <div>
                  <button class="button secondary load-prompt-card" type="button" data-label="{esc(label)}" {load_attr}>Load</button>
                  <button class="button secondary copy-prompt-card" type="button" data-target="prompt-preview-{esc(key)}">Copy</button>
                </div>
              </div>
            </article>
            """
        )

    artifact_rows = []
    for report in _report_entries(6):
        artifact_rows.append(
            f"""
            <a class="artifact-row" href="{esc(report['view_url'])}">
              <span>{esc(report['name'])}</span>
              <small>{esc(report['folder'])} · {esc(_format_timestamp(report['updated_at']))}</small>
            </a>
            """
        )
    artifacts_html = "".join(artifact_rows) or '<div class="artifact-empty">No report artifacts yet.</div>'

    content = f"""
      <style>
        .review-shell {{
          display: flex;
          flex-direction: column;
          gap: 10px;
          min-width: 0;
        }}
        .review-header {{
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: flex-start;
        }}
        .review-header h2 {{
          margin: 0 0 6px;
          font-size: 16px;
          color: #dff4ff;
          letter-spacing: 0.04em;
        }}
        .review-header p {{
          margin: 0;
          color: #9eb9d4;
          font-size: 12px;
          line-height: 1.45;
        }}
        .review-badge {{
          display: inline-flex;
          border: 1px solid rgba(0, 242, 255, 0.32);
          border-radius: 4px;
          padding: 4px 8px;
          color: #8df7ff;
          background: rgba(0, 242, 255, 0.12);
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          white-space: nowrap;
        }}
        .review-status-grid {{
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 8px;
          min-width: 0;
        }}
        .review-status-card {{
          border: 1px solid rgba(0, 242, 255, 0.18);
          border-radius: 4px;
          background: rgba(5, 14, 25, 0.75);
          padding: 8px;
          min-width: 0;
        }}
        .review-status-card span {{
          display: block;
          color: #8da8c4;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin-bottom: 4px;
        }}
        .review-status-card strong {{
          font-size: 15px;
          color: #e7f4ff;
        }}
        .review-status-card .ok {{ color: #00ff9f; }}

        .settings-bar {{
          display: grid;
          grid-template-columns: minmax(170px, 220px) minmax(0, 1fr) minmax(170px, 220px) auto;
          gap: 10px;
          align-items: end;
          border: 1px solid rgba(0, 242, 255, 0.2);
          border-radius: 4px;
          background: #010f1f;
          padding: 10px;
          min-width: 0;
        }}
        .setting-field {{
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: 5px;
        }}
        .setting-field label {{
          color: #7f99b2;
          font-family: 'JetBrains Mono', ui-monospace, monospace;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }}
        .setting-field select,
        .setting-field input {{
          border: 1px solid rgba(0, 242, 255, 0.22);
          border-radius: 4px;
          background: #0d1c2d;
          color: #e0f4ff;
          min-height: 34px;
          padding: 6px 8px;
        }}
        .segmented {{
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }}
        .segmented button {{
          min-height: 34px;
        }}

        .review-split {{
          display: grid;
          grid-template-columns: repeat(12, minmax(0, 1fr));
          gap: 10px;
          min-width: 0;
        }}
        .review-col-left {{ grid-column: span 3; }}
        .review-col-center {{ grid-column: span 6; }}
        .review-col-right {{ grid-column: span 3; }}

        .review-pane {{
          border: 1px solid rgba(0, 242, 255, 0.18);
          border-radius: 4px;
          background: rgba(13, 28, 45, 0.9);
          min-width: 0;
          display: flex;
          flex-direction: column;
        }}
        .review-pane h3 {{
          margin: 0;
          padding: 10px;
          border-bottom: 1px solid rgba(0, 242, 255, 0.2);
          font-size: 12px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: #8cf7ff;
        }}
        .review-pane-body {{
          padding: 10px;
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }}
        .files-tree {{
          list-style: none;
          margin: 0;
          padding: 0;
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 520px;
          overflow: auto;
        }}
        .files-tree li {{
          display: flex;
          justify-content: space-between;
          gap: 8px;
          border: 1px solid rgba(0, 242, 255, 0.14);
          border-radius: 4px;
          padding: 6px 8px;
          background: rgba(4, 12, 21, 0.7);
        }}
        .file-name {{
          color: #d6ecff;
          font-family: ui-monospace, monospace;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }}
        .file-meta {{
          color: #8ca8c4;
          font-size: 10px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          white-space: nowrap;
        }}
        .score-pill {{
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border: 1px solid rgba(0, 242, 255, 0.22);
          border-radius: 4px;
          padding: 4px 8px;
          font-size: 11px;
          color: #b6ddff;
          width: fit-content;
        }}
        .score-value {{ color: #00ff9f; font-weight: 700; }}
        .review-output {{
          margin: 0;
          min-height: 460px;
          max-height: 520px;
          overflow: auto;
          border: 1px solid rgba(0, 242, 255, 0.2);
          border-radius: 4px;
          background: rgba(3, 9, 16, 0.85);
          padding: 10px;
          color: #d5ebff;
          white-space: pre-wrap;
          word-break: break-word;
          font-family: ui-monospace, monospace;
          font-size: 12px;
          line-height: 1.45;
        }}
        .review-actions {{
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }}
        .prompt-stack {{
          display: grid;
          gap: 10px;
        }}
        .prompt-card {{
          border: 1px solid rgba(0, 242, 255, 0.18);
          border-radius: 4px;
          background: #122131;
          min-width: 0;
          overflow: hidden;
        }}
        .prompt-card-head,
        .prompt-card-foot {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 8px;
          padding: 8px 10px;
          border-bottom: 1px solid rgba(0, 242, 255, 0.16);
        }}
        .prompt-card-foot {{
          border-top: 1px solid rgba(0, 242, 255, 0.16);
          border-bottom: 0;
          color: #7f99b2;
          font-size: 10px;
        }}
        .prompt-card-foot > div {{
          display: flex;
          gap: 6px;
        }}
        .model-ref {{
          color: #00f2ff;
          font-family: 'JetBrains Mono', ui-monospace, monospace;
          font-size: 11px;
          letter-spacing: 0.06em;
        }}
        .prompt-state {{
          border: 1px solid rgba(0, 242, 255, 0.22);
          border-radius: 4px;
          padding: 2px 6px;
          color: #00ff9f;
          font-size: 10px;
        }}
        .prompt-state.missing {{ color: #ffc857; border-color: rgba(255, 200, 87, 0.35); }}
        .prompt-preview {{
          margin: 0;
          max-height: 150px;
          overflow: auto;
          padding: 10px;
          background: #010f1f;
          color: #c7def2;
          white-space: pre-wrap;
          word-break: break-word;
          font-size: 11px;
          line-height: 1.45;
        }}
        .inspector-stack {{
          display: grid;
          gap: 10px;
        }}
        .health-ring {{
          width: 116px;
          height: 116px;
          border-radius: 999px;
          margin: 0 auto;
          display: grid;
          place-items: center;
          background: conic-gradient(#00f2ff {health_score}%, rgba(0,242,255,.1) 0);
          border: 1px solid rgba(0, 242, 255, 0.3);
        }}
        .health-ring span {{
          width: 84px;
          height: 84px;
          border-radius: 999px;
          display: grid;
          place-items: center;
          background: #010f1f;
          color: #e0f4ff;
          font-weight: 800;
          font-size: 20px;
        }}
        .context-checks {{
          display: grid;
          gap: 7px;
        }}
        .inspector-label {{
          color: #7f99b2;
          font-family: 'JetBrains Mono', ui-monospace, monospace;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          text-align: center;
        }}
        .context-checks div {{
          display: flex;
          justify-content: space-between;
          gap: 8px;
          border: 1px solid rgba(0, 242, 255, 0.12);
          border-radius: 4px;
          background: #010f1f;
          padding: 7px 8px;
          color: #a9c4df;
          font-size: 11px;
        }}
        .context-checks strong {{ color: #00ff9f; }}
        .metadata-grid {{
          display: grid;
          gap: 7px;
        }}
        .metadata-grid div {{
          display: grid;
          gap: 2px;
          border: 1px solid rgba(0, 242, 255, 0.12);
          border-radius: 4px;
          background: #010f1f;
          padding: 7px 8px;
        }}
        .metadata-grid span {{
          color: #7f99b2;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }}
        .metadata-grid strong {{
          color: #dff4ff;
          font-size: 11px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }}
        .artifact-list {{
          display: grid;
          gap: 6px;
        }}
        .artifact-row {{
          display: grid;
          gap: 2px;
          border: 1px solid rgba(0, 242, 255, 0.12);
          border-radius: 4px;
          background: #010f1f;
          padding: 7px 8px;
        }}
        .artifact-row span {{
          color: #dff4ff;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }}
        .artifact-row small,
        .artifact-empty {{
          color: #7f99b2;
          font-size: 10px;
        }}
        @media (max-width: 1350px) {{
          .review-col-left {{ grid-column: span 4; }}
          .review-col-center {{ grid-column: span 5; }}
          .review-col-right {{ grid-column: span 4; }}
          .review-output {{ min-height: 420px; }}
        }}
        @media (max-width: 1000px) {{
          .settings-bar {{ grid-template-columns: 1fr; }}
          .review-status-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
          .review-split {{ grid-template-columns: 1fr; }}
          .review-col-left, .review-col-center, .review-col-right {{ grid-column: span 1; }}
        }}
      </style>
      <section class="review-shell">
        <article class="ov1-panel">
          <div class="ov1-panel-body review-header">
            <div>
              <h2>Codex Review</h2>
              <p>Tactical review workspace mapped to prompt generation, resource analysis, and final audit output.</p>
            </div>
            <span class="review-badge">Prompt Health {health_score}%</span>
          </div>
        </article>

        <section class="review-status-grid">
          <article class="review-status-card"><span>Incoming Resources</span><strong>{len(resources)}</strong></article>
          <article class="review-status-card"><span>Analyzed</span><strong class="ok">{analyzed_count}</strong></article>
          <article class="review-status-card"><span>Patch Plans</span><strong>{patch_plan_count}</strong></article>
          <article class="review-status-card"><span>Staged Copies</span><strong>{staged_count}</strong></article>
        </section>

        <section class="settings-bar">
          <div class="setting-field">
            <label for="promptEngine">PROMPT_ENGINE</label>
            <select id="promptEngine">
              <option>OPENCODE</option>
              <option>GEMINI</option>
              <option>CODEX</option>
            </select>
          </div>
          <div class="setting-field">
            <label>DETAIL_LEVEL</label>
            <div class="segmented">
              <button class="button secondary" type="button">Brief</button>
              <button class="button" type="button">Standard</button>
              <button class="button secondary" type="button">Deep</button>
            </div>
          </div>
          <div class="setting-field">
            <label for="outputTone">OUTPUT_TONE</label>
            <select id="outputTone">
              <option>technical</option>
              <option>audit</option>
              <option>implementation</option>
            </select>
          </div>
          <button class="button secondary" type="button" id="regenerateAllPrompts">REGENERATE_ALL</button>
        </section>

        <section class="review-split">
          <article class="review-pane review-col-left">
            <h3>Analyzed Files Tree</h3>
            <div class="review-pane-body">
              <ul class="files-tree">{tree_html}</ul>
            </div>
          </article>

          <article class="review-pane review-col-center">
            <h3>Generated Prompt Cards</h3>
            <div class="review-pane-body">
              <div class="prompt-stack">{"".join(prompt_cards)}</div>
              <div class="review-actions">
                <button class="button" type="button" id="loadOpenCodePrompt">Load OpenCode Prompt</button>
                <button class="button secondary" type="button" id="loadCodexPrompt">Load Codex Audit Prompt</button>
              </div>
            </div>
          </article>

          <article class="review-pane review-col-right">
            <h3>Inspector</h3>
            <div class="review-pane-body inspector-stack">
              <div>
                <div class="inspector-label">PROMPT_HEALTH</div>
                <div class="health-ring"><span>{health_score}%</span></div>
              </div>
              <div class="context-checks">
                <div><span>NODE_DETAILS</span><strong>{len(resources)} nodes</strong></div>
                <div><span>ANALYSIS_READY</span><strong>{analyzed_count}</strong></div>
                <div><span>PATCH_CONTEXT</span><strong>{patch_plan_count}</strong></div>
                <div><span>STAGING_CONTEXT</span><strong>{staged_count}</strong></div>
              </div>
              <div class="metadata-grid">
                <div><span>METADATA_SOURCE</span><strong>orchestrator/prompts</strong></div>
                <div><span>MODEL_REFS</span><strong>OPENCODE / GEMINI / CODEX</strong></div>
                <div><span>ARTIFACTS</span><strong>{len(artifact_rows)} recent report(s)</strong></div>
              </div>
              <pre class="review-output" id="reviewOutput">Select a prompt card to load full content here.</pre>
              <div class="review-actions">
                <button class="button secondary" type="button" id="copyReviewOutput">Copy Output</button>
              </div>
            </div>
          </article>
        </section>

        <section class="review-pane">
          <h3>Secondary Report Artifacts</h3>
          <div class="review-pane-body artifact-list">{artifacts_html}</div>
        </section>
      </section>
    """
    script = """
      <script>
        function copyText(text) {
          return navigator.clipboard.writeText(text);
        }
        async function loadPrompt(endpoint, label) {
          const out = document.getElementById("reviewOutput");
          if (!out) return;
          out.textContent = "Loading " + label + "...";
          try {
            const response = await fetch(endpoint);
            const body = await response.json();
            if (!response.ok) {
              throw new Error(body.detail || body.error || "Request failed");
            }
            out.textContent = body.content || ("No content returned for " + label + ".");
          } catch (error) {
            out.textContent = label + " load failed: " + String(error.message || error);
          }
        }
        function loadInlinePrompt(targetId, label) {
          const out = document.getElementById("reviewOutput");
          const source = document.getElementById(targetId);
          if (!out || !source) return;
          out.textContent = source.textContent || ("No content returned for " + label + ".");
        }
        document.getElementById("loadOpenCodePrompt")?.addEventListener("click", () => loadPrompt("/api/prompts/opencode-next", "OpenCode Prompt"));
        document.getElementById("loadCodexPrompt")?.addEventListener("click", () => loadPrompt("/api/prompts/codex-audit-next", "Codex Audit Prompt"));
        document.getElementById("copyReviewOutput")?.addEventListener("click", () => {
          const text = document.getElementById("reviewOutput")?.textContent || "";
          copyText(text).then(() => alert("Output copied."));
        });
        document.addEventListener("click", (event) => {
          const loadButton = event.target.closest(".load-prompt-card");
          if (loadButton) {
            const endpoint = loadButton.getAttribute("data-endpoint");
            const label = loadButton.getAttribute("data-label") || "Prompt";
            const inlineTarget = loadButton.getAttribute("data-inline-target");
            if (endpoint) {
              loadPrompt(endpoint, label);
            } else if (inlineTarget) {
              loadInlinePrompt(inlineTarget, label);
            }
            return;
          }
          const copyButton = event.target.closest(".copy-prompt-card");
          if (copyButton) {
            const target = document.getElementById(copyButton.getAttribute("data-target") || "");
            copyText(target?.textContent || "").then(() => {
              copyButton.textContent = "Copied";
              setTimeout(() => { copyButton.textContent = "Copy"; }, 1200);
            });
          }
        });
        document.getElementById("regenerateAllPrompts")?.addEventListener("click", () => {
          const out = document.getElementById("reviewOutput");
          if (out) out.textContent = "Prompt regeneration requires an approved patch-plan source. No backend mutation was started from this review page.";
        });
      </script>
    """
    try:
        from apps.shared_layout import render_cyber_layout
        host = controller.system_agent.stats()
        return render_cyber_layout(
            "Codex Review",
            "reviews",
            content,
            script=script,
            topbar_stats={
                "title": "Codex Review",
                "cpu": f"{host.get('cpu_percent', 'n/a')}%",
                "memory": f"{host.get('memory_percent', 'n/a')}%",
                "active_tasks": str(len(resources)),
                "uptime": str(host.get("uptime", "n/a")),
            },
        )
    except ImportError:
        return app_view_html("Codex Review", "reviews", content, script=script, subtitle="Tactical review workspace for prompt and report validation.")


@app.get("/codex-review", response_class=HTMLResponse)
def codex_review_page() -> str:
    """Alias route for Codex Review blueprint shell."""
    return reviews_index_page()


@app.get("/staging/{task_id}", response_class=HTMLResponse)
def coding_staging_page(task_id: str) -> str:
    from apps.coding_agent import app as coding_app

    if task_id.startswith("coding-"):
        try:
            return _response_body_text(coding_app.staging_preview(task_id))
        except HTTPException:
            return _generic_staging_preview_html(task_id)
    return _generic_staging_preview_html(task_id)


@app.get("/staging", response_class=HTMLResponse)
def staging_index_page() -> str:
    content = f"""
      <section class="agent-panel">
        <h2>Staging</h2>
        <p>Staging folders are review-only workspace outputs. Live FiveM resources are not modified from this page.</p>
        <div class="agent-actions">
          <a class="button" href="/upload">Open Upload Pipeline</a>
          <a class="button secondary" href="/reviews">Open Reviews</a>
        </div>
      </section>
      {_staging_index_html()}
      <section class="agent-panel">
        <h2>Recent reports</h2>
        <p>Use reports to decide whether staged output is ready for human testing.</p>
      </section>
      {_recent_reports_html(8)}
    """
    return app_view_html("Staging", "staging", content, subtitle="Staging-only script output.")


@app.get("/upload", response_class=HTMLResponse)
def upload_page() -> str:
    jobs = _upload_jobs(limit=25)
    resources = _get_incoming_resources_with_analysis(limit=24)
    incoming_resources_json = json.dumps(resources).replace("</", "<\\/")

    tag_rows: list[str] = []
    for resource in resources[:12]:
        analysis = resource.get("analysis") or {}
        summary = _generate_analysis_summary(analysis) if analysis else {}
        framework = str(summary.get("framework", "unknown")).upper()
        inventory = str(summary.get("inventory", "none")).upper()
        database = str(summary.get("database", "none")).upper()
        tag_rows.append(
            f"""
            <div class="framework-row">
              <span class="framework-name">{esc(resource.get("name", "resource"))}</span>
              <div class="framework-tags">
                <span class="tag">{esc(framework)}</span>
                <span class="tag">{esc(inventory)}</span>
                <span class="tag">{esc(database)}</span>
              </div>
            </div>
            """
        )
    tag_html = "".join(tag_rows) or '<div class="framework-row"><span class="framework-name">No analyzed resources yet.</span></div>'

    ready_jobs = sum(1 for job in jobs if str(job.get("status", "")).lower() in {"ready", "completed"})
    failed_jobs = sum(1 for job in jobs if str(job.get("status", "")).lower() == "failed")
    active_jobs = max(0, len(jobs) - ready_jobs - failed_jobs)

    history_cards: list[str] = []
    for job in jobs[:6]:
        task_id = str(job.get("task_id", "upload"))
        incoming_path = str(job.get("incoming_path") or job.get("tracker_path") or "")
        history_actions = []
        if str(job.get("plan_url", "")).startswith("/"):
            history_actions.append(f'<a class="button secondary" href="{esc(str(job["plan_url"]))}">Plan</a>')
        if str(job.get("review_url", "")).startswith("/"):
            history_actions.append(f'<a class="button secondary" href="{esc(str(job["review_url"]))}">Review</a>')
        if str(job.get("staging_url", "")).startswith("/"):
            history_actions.append(f'<a class="button secondary" href="{esc(str(job["staging_url"]))}">Staging</a>')
        history_cards.append(
            f"""
            <article class="history-card">
              <div class="history-card-head"><strong>{esc(task_id)}</strong>{_status_pill(job.get("status"))}</div>
              <p>{esc(len(job.get("files", [])))} file(s) · {esc(_format_timestamp(job.get("updated_at")))}</p>
              <code>{esc(incoming_path or "reports/upload-pipeline")}</code>
              <div class="history-actions">{''.join(history_actions) or '<span class="subtle-id">No linked artifacts</span>'}</div>
            </article>
            """
        )
    recent_history_html = "".join(history_cards) or """
            <article class="history-card empty-history">
              <strong>No upload history</strong>
              <p>Completed upload pipeline runs will appear here.</p>
            </article>
    """

    content = f"""
      <section class="upload-workspace">
        <article class="upload-hero">
          <div class="upload-hero-copy">
            <span class="pipeline-kicker">UPLOAD PIPELINE</span>
            <h2>Drop Scripts Here</h2>
            <p>Upload ZIP files or resource folders into isolated incoming intake. Nothing touches live FiveM resources.</p>
          </div>
          <span class="safety-pill">STAGING ONLY</span>
        </article>

        <section class="upload-primary">
          <article class="drop-panel">
            <form id="uploadForm" class="upload-form">
              <div id="dropZone" class="drop-zone" tabindex="0">
                <div class="drop-zone-center">
                  <div class="drop-icon">+</div>
                  <strong>Drop Scripts Here</strong>
                  <span>ZIP, Lua resource files, or full resource folders for staging-only scan.</span>
                </div>
              </div>
              <div class="picker-row">
                <label class="picker-button">Browse Files<input id="fileInput" name="files" type="file" multiple accept=".zip,.lua,.js,.json,.cfg,.txt,.md,.html,.css"></label>
                <label class="picker-button secondary-picker">Browse Folder<input id="folderInput" name="files" type="file" multiple webkitdirectory directory></label>
                <button id="uploadButton" class="primary-button" type="submit">Submit Pipeline</button>
              </div>
              <div id="fileList" class="file-list">No files selected.</div>
            </form>
          </article>

          <aside class="upload-side">
            <section class="upload-status-grid">
              <article class="upload-status-card"><span>Total Jobs</span><strong>{len(jobs)}</strong></article>
              <article class="upload-status-card"><span>Active</span><strong class="warn">{active_jobs}</strong></article>
              <article class="upload-status-card"><span>Ready</span><strong class="ok">{ready_jobs}</strong></article>
              <article class="upload-status-card"><span>Failed</span><strong class="danger">{failed_jobs}</strong></article>
            </section>
            <article class="queue-card">
              <h3>Framework Tags</h3>
              <div class="framework-list">{tag_html}</div>
            </article>
          </aside>
        </section>

        {_incoming_resource_queue_html()}

        <section class="pipeline-lower-grid pipeline-overview-grid">
          <article class="progress-card">
            <h3>Pipeline Stages</h3>
            <div class="step-list">
              <div class="step" data-step="uploaded"><span></span><div><strong>Uploaded</strong><p>Files saved under incoming.</p></div></div>
              <div class="step" data-step="scanning"><span></span><div><strong>Scanning</strong><p>Manifest and risk markers are scanned.</p></div></div>
              <div class="step" data-step="planning"><span></span><div><strong>Planning</strong><p>Planner builds safe conversion strategy.</p></div></div>
              <div class="step" data-step="staging"><span></span><div><strong>Staging</strong><p>Coding Agent writes staged output only.</p></div></div>
              <div class="step" data-step="reviewing"><span></span><div><strong>Reviewing</strong><p>Readable report and guard checks generated.</p></div></div>
              <div class="step" data-step="ready"><span></span><div><strong>Ready</strong><p>Plan/review/staging links available.</p></div></div>
            </div>
          </article>
        </section>

        <section id="resultCard" class="result-card hidden"></section>

        <section class="history-section">
          <div class="section-title-row">
            <h3>Recent History</h3>
            <span>{len(jobs)} tracked run(s)</span>
          </div>
          <div class="history-grid">{recent_history_html}</div>
        </section>
        {_document_modal_html()}
      </section>
    """
    try:
        from apps.shared_layout import render_cyber_layout
        host = controller.system_agent.stats()
        topbar_stats = {
            "title": "Upload Pipeline",
            "cpu": f"{host.get('cpu_percent', 'n/a')}%",
            "memory": f"{host.get('memory_percent', 'n/a')}%",
            "active_tasks": str(len(_upload_jobs(20))),
            "uptime": str(host.get("uptime", "n/a")),
        }
        return render_cyber_layout(
            "Upload Pipeline",
            "upload",
            content,
            extra_css=_upload_page_css() + _incoming_resource_queue_css(),
            script=_upload_page_script() + _incoming_resource_queue_js(incoming_resources_json),
            topbar_stats=topbar_stats,
        )
    except ImportError:
        return render_layout(
            "Upload Pipeline",
            "upload",
            content,
            extra_css=_upload_page_css() + _incoming_resource_queue_css(),
            script=_upload_page_script() + _incoming_resource_queue_js(incoming_resources_json),
            subtitle="Planner to Coding to Review",
        )


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
        _set_upload_status(tracker, "scanning")
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

        _set_upload_status(tracker, "staging")
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
        _set_upload_status(tracker, "ready")
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
      .upload-workspace{
        display:flex;
        flex-direction:column;
        gap:14px;
        min-width:0;
      }
      .upload-hero{
        display:flex;
        justify-content:space-between;
        gap:16px;
        align-items:flex-start;
        border:1px solid rgba(0,242,255,.2);
        border-radius:4px;
        background:#0d1c2d;
        padding:16px 18px;
      }
      .pipeline-kicker{display:block;margin-bottom:5px;color:#00f2ff;font-size:11px;font-family:'JetBrains Mono',ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase}
      .upload-hero h2{margin:0 0 6px;font-size:22px;letter-spacing:.02em;color:#dff4ff}
      .upload-hero p{max-width:720px;margin:0;color:#9eb9d4;font-size:13px;line-height:1.45}
      .upload-primary{
        display:grid;
        grid-template-columns:minmax(0,1fr) 360px;
        gap:14px;
        min-width:0;
      }
      .drop-panel,.upload-side{min-width:0}
      .drop-panel{
        border:1px solid rgba(0,242,255,.2);
        border-radius:4px;
        background:#0d1c2d;
      }
      .upload-side{display:flex;flex-direction:column;gap:10px}
      .upload-side .upload-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
      .upload-status-grid{
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:10px;
        min-width:0;
      }
      .upload-status-card{
        border:1px solid rgba(0,242,255,.18);
        border-radius:4px;
        background:#122131;
        padding:10px;
        min-width:0;
      }
      .upload-status-card span{
        display:block;
        color:#8da8c4;
        font-size:10px;
        letter-spacing:.08em;
        text-transform:uppercase;
        margin-bottom:4px;
      }
      .upload-status-card strong{font-size:15px;color:#e7f4ff}
      .upload-status-card .ok{color:#00ff9f}
      .upload-status-card .warn{color:#ffc857}
      .upload-status-card .danger{color:#ff5f7a}
      .pipeline-lower-grid{
        display:grid;
        grid-template-columns:repeat(12,minmax(0,1fr));
        gap:14px;
        min-width:0;
      }
      .processing-queue{grid-column:span 8}
      .progress-card{grid-column:span 4}
      .pipeline-overview-grid .progress-card{grid-column:1 / -1}
      .processing-queue,.progress-card{min-width:0}
      .queue-card{
        border:1px solid rgba(0,242,255,.2);
        border-radius:4px;
        background:#0d1c2d;
        padding:12px;
        min-width:0;
      }
      .queue-card h3{
        margin:0 0 8px;
        color:#93f7ff;
        font-size:12px;
        letter-spacing:.08em;
        text-transform:uppercase;
      }
      .queue-table{
        width:100%;
        border-collapse:collapse;
        font-size:11px;
        table-layout: fixed;
      }
      .queue-table th,.queue-table td{
        border:1px solid rgba(0,242,255,.14);
        padding:9px 10px;
        text-align:left;
        vertical-align:top;
        overflow-wrap:anywhere;
      }
      .queue-table th{
        color:#9cf8ff;
        background:rgba(0,242,255,.1);
        font-size:10px;
        letter-spacing:.08em;
        text-transform:uppercase;
      }
      .queue-file{display:block;color:#e0f4ff;font-weight:700}
      .queue-table small{display:block;margin-top:2px;color:#7f99b2;font-size:10px}
      .queue-analysis{margin-top:6px;font-size:10px;color:#7f99b2}
      .queue-pill{
        display:inline-flex;
        border:1px solid rgba(0,242,255,.25);
        border-radius:4px;
        padding:2px 6px;
        font-size:10px;
        font-weight:700;
      }
      .queue-pill.ready,.queue-pill.completed{color:#00ff9f;border-color:rgba(0,255,159,.35);background:rgba(0,255,159,.12)}
      .queue-pill.failed{color:#ff5f7a;border-color:rgba(255,95,122,.35);background:rgba(255,95,122,.12)}
      .queue-pill.scanning,.queue-pill.planning,.queue-pill.staging,.queue-pill.reviewing,.queue-pill.uploaded{color:#00f2ff;background:rgba(0,242,255,.12)}
      .queue-pill.running{color:#00f2ff;background:rgba(0,242,255,.12)}
      .queue-pill.analyzed,.queue-pill.patch_ready,.queue-pill.staged,.queue-pill.approved{color:#00ff9f;background:rgba(0,255,159,.12);border-color:rgba(0,255,159,.35)}
      .queue-pill.pending_scan{color:#ffc857;background:rgba(255,200,87,.12);border-color:rgba(255,200,87,.35)}
      .queue-actions{display:flex;flex-wrap:wrap;gap:4px}
      .framework-list{display:flex;flex-direction:column;gap:6px;max-height:240px;overflow:auto}
      .framework-row{
        display:flex;
        justify-content:space-between;
        gap:8px;
        border:1px solid rgba(0,242,255,.14);
        border-radius:4px;
        padding:6px 8px;
        background:rgba(3,10,19,.72);
      }
      .framework-name{
        color:#d8eeff;
        font-family:ui-monospace,monospace;
        min-width:0;
        overflow:hidden;
        text-overflow:ellipsis;
        white-space:nowrap;
      }
      .framework-tags{display:flex;flex-wrap:wrap;gap:4px}
      .framework-tags .tag{
        border:1px solid rgba(0,242,255,.22);
        border-radius:4px;
        padding:2px 6px;
        color:#94f8ff;
        background:rgba(0,242,255,.1);
        font-size:10px;
        letter-spacing:.04em;
      }
      .safety-checklist{
        border:1px solid var(--ao-border);
        border-radius:4px;
        background:var(--ao-panel);
        box-shadow:0 18px 42px rgba(0,0,0,.22);
        margin-bottom:18px;
        overflow:hidden;
      }
      .safety-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:18px;border-bottom:1px solid var(--ao-border)}
      .safety-head h2{margin:0 0 6px;font-size:19px}
      .safety-head p{margin:0;color:var(--ao-muted);line-height:1.5}
      .safety-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:16px}
      .status-row{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;align-items:start;border:1px solid rgba(125,211,252,.16);border-radius:4px;padding:10px;background:rgba(2,6,23,.28)}
      .status-row>span{width:12px;height:12px;margin-top:4px;border-radius:999px;background:#37d67a;box-shadow:0 0 14px rgba(55,214,122,.28)}
      .status-row.warn>span{background:#fbbf24;box-shadow:0 0 14px rgba(251,191,36,.22)}
      .status-row strong{display:block;color:var(--ao-text);font-size:13px}
      .status-row small{display:block;margin-top:2px;color:var(--ao-muted);line-height:1.4}
      .upload-card,.progress-card,.result-card{
        border:1px solid var(--ao-border);
        border-radius:4px;
        background:var(--ao-panel);
        box-shadow:0 18px 42px rgba(0,0,0,.22);
        margin-bottom:18px;
        overflow:hidden;
      }
      .upload-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:20px;border-bottom:1px solid var(--ao-border)}
      .upload-head h2{margin:0 0 6px;font-size:20px}
      .upload-head p{margin:0;color:var(--ao-muted);line-height:1.5}
      .safety-pill{white-space:nowrap;border:1px solid rgba(0,219,231,.45);border-radius:4px;color:#00f2ff;background:rgba(0,219,231,.1);padding:6px 10px;font-size:12px;font-weight:800}
      .upload-form{padding:18px}
      .drop-zone{min-height:320px;border:2px dashed rgba(0,242,255,.5);border-radius:4px;background:rgba(18,33,49,.72);display:grid;place-items:center;text-align:center;gap:10px;padding:28px;color:var(--ao-muted);cursor:pointer;transition:border-color .16s,background .16s}
      .drop-zone-center{display:grid;place-items:center;gap:10px}
      .drop-zone strong{display:block;color:var(--ao-text);font-size:22px;line-height:1.2}
      .drop-zone.dragging{border-color:#5eead4;background:rgba(20,184,166,.12)}
      .drop-icon{width:56px;height:56px;border-radius:4px;display:grid;place-items:center;border:1px solid rgba(0,242,255,.45);color:#9fdcff;font-size:30px;font-weight:500;margin:auto;background:rgba(0,242,255,.08)}
      .picker-row{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px;align-items:center}
      .picker-button,.primary-button,.result-card a{display:inline-flex;align-items:center;min-height:38px;border-radius:4px;border:1px solid rgba(0,242,255,.28);background:#122131;color:#edf5ff;text-decoration:none;padding:8px 12px;font-weight:800;cursor:pointer}
      .picker-button input{display:none}
      .primary-button{background:rgba(0,219,231,.16);border-color:#00dbe7;color:#eaffff}
      .primary-button:disabled{opacity:.55;cursor:not-allowed}
      .file-list{margin-top:14px;color:var(--ao-muted);line-height:1.55;overflow-wrap:anywhere}
      .progress-card{padding:12px;display:grid;gap:10px}
      .progress-card h3{margin:0;color:#93f7ff;font-size:12px;letter-spacing:.08em;text-transform:uppercase}
      .step-list{display:grid;gap:8px}
      .step{display:flex;gap:12px;align-items:flex-start;border:1px solid rgba(125,211,252,.14);border-radius:4px;padding:12px;background:rgba(5,12,24,.35)}
      .step span{width:24px;height:24px;border-radius:50%;border:1px solid rgba(125,211,252,.35);display:grid;place-items:center;color:var(--ao-muted);flex:0 0 auto}
      .step span::after{content:"";width:8px;height:8px;border-radius:50%;background:rgba(125,211,252,.35)}
      .step p{margin:3px 0 0;color:var(--ao-muted)}
      .step.done span{background:rgba(20,184,166,.16);border-color:rgba(94,234,212,.45);color:#5eead4}
      .step.done span::after{content:"OK";width:auto;height:auto;background:transparent;font-size:9px;font-weight:900}
      .step.active span{border-color:#fbbf24}
      .step.active span::after{background:#fbbf24}
      .step.failed span{border-color:#fb7185}
      .step.failed span::after{background:#fb7185}
      .result-card{padding:18px}
      .result-card h2{margin:0 0 8px}
      .result-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
      .ai-check-button{font:inherit}
      .hidden{display:none}
      .incoming-card .analysis-summary{margin:10px 0;padding:8px;border:1px solid var(--ao-border);border-radius:4px;background:rgba(2,6,23,.3)}
      .analysis-result{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
      .analysis-badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;background:rgba(0,212,255,.12);color:var(--ao-cyan);border:1px solid rgba(0,212,255,.2)}
      .analysis-badge.framework{background:rgba(167,139,250,.12);color:#a78bfa;border-color:rgba(167,139,250,.2)}
      .analysis-badge.inventory{background:rgba(52,211,153,.12);color:#34d399;border-color:rgba(52,211,153,.2)}
      .analysis-badge.target{background:rgba(251,191,36,.12);color:#fbbf24;border-color:rgba(251,191,36,.2)}
      .analysis-badge.database{background:rgba(96,165,250,.12);color:#60a5fa;border-color:rgba(96,165,250,.2)}
      .analysis-badge.risk{background:rgba(255,99,112,.12);border-color:rgba(255,99,112,.2)}
      .analysis-action{font-size:12px;color:var(--ao-muted)}
      .analysis-error{color:var(--ao-danger);font-size:12px}
      .analyze-button{font:inherit;background:rgba(0,212,255,.15);border-color:rgba(0,212,255,.3)}
      .history-section{
        border:1px solid rgba(0,242,255,.2);
        border-radius:4px;
        background:#0d1c2d;
        padding:12px;
      }
      .section-title-row{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:10px}
      .section-title-row h3{margin:0;color:#93f7ff;font-size:12px;letter-spacing:.08em;text-transform:uppercase}
      .section-title-row span{color:#7f99b2;font-size:11px}
      .history-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
      .history-card{border:1px solid rgba(0,242,255,.16);border-radius:4px;background:#122131;padding:10px;min-width:0}
      .history-card-head{display:flex;justify-content:space-between;gap:8px;align-items:flex-start;margin-bottom:6px}
      .history-card .status-pill{display:inline-flex;border:1px solid rgba(0,242,255,.22);border-radius:4px;padding:2px 6px;color:#7f99b2;background:#010f1f;font-size:10px;font-weight:800;white-space:nowrap}
      .history-card .status-pill.ok{color:#00ff9f;border-color:rgba(0,255,159,.35);background:rgba(0,255,159,.12)}
      .history-card .status-pill.warn{color:#ffc857;border-color:rgba(255,200,87,.35);background:rgba(255,200,87,.12)}
      .history-card .status-pill.danger{color:#ff5f7a;border-color:rgba(255,95,122,.35);background:rgba(255,95,122,.12)}
      .history-card strong{color:#e0f4ff;font-size:12px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .history-card p{margin:0 0 6px;color:#9eb9d4;font-size:11px}
      .history-card code{display:block;color:#7f99b2;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .history-actions{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
      @media (max-width:1350px){
        .upload-primary{grid-template-columns:minmax(0,1fr) 320px}
        .processing-queue{grid-column:span 7}
        .progress-card{grid-column:span 5}
        .drop-zone{min-height:280px}
      }
      @media (max-width:1100px){
        .upload-primary{grid-template-columns:1fr}
        .upload-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
        .pipeline-lower-grid{grid-template-columns:1fr}
        .processing-queue,.progress-card{grid-column:span 1}
        .history-grid{grid-template-columns:1fr}
      }
      @media (max-width: 700px){.upload-header,.upload-head,.safety-head{display:block}.safety-pill{display:inline-flex;margin-top:12px}.picker-row>*{width:100%;justify-content:center}.safety-grid{grid-template-columns:1fr}}
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
        const ANALYSIS_ACTION_LABELS = {
          "safe": "Ready for staging",
          "manual-sql": "SQL requires manual review",
          "review-required": "Risk - review needed",
          "adaptation-needed": "Framework adaptation required"
        };
        let selectedFiles = [];

        function escapeHtml(value) {
          return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
        }

        function getRiskColor(risk) {
          if (risk === "high") return "var(--ao-danger)";
          if (risk === "medium") return "#facc15";
          return "var(--ao-green)";
        }

        function getActionLabel(recommendedAction) {
          return ANALYSIS_ACTION_LABELS[recommendedAction] || recommendedAction || "Ready";
        }

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
          const aliases = { done: "ready", coding: "staging" };
          status = aliases[status] || status;
          const order = ["uploaded", "scanning", "planning", "staging", "reviewing", "ready"];
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
              <h2>Ready for Testing</h2>
              <p>${body.files?.length || selectedFiles.length} uploaded file(s) were processed safely. Live FiveM resources were not modified.</p>
              <div class="result-actions">
                <a href="${body.plan_url || "#"}">View Plan</a>
                <a href="${body.staging_url || "#"}">View Staging</a>
                <a href="${body.review_url || "#"}">View Review</a>
                <a href="/reports/daily">Open Daily Digest</a>
                <button class="primary-button ai-check-button" type="button" data-path="${body.incoming_path || ""}">Run AI Integration Check</button>
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

        async function runAiCheck(path, button) {
          if (!path) return;
          const original = button ? button.textContent : "";
          if (button) {
            button.disabled = true;
            button.textContent = "Running AI check...";
          }
          resultCard.classList.remove("hidden");
          resultCard.innerHTML = "<h2>AI Integration Check</h2><p>Running bounded report-only analysis. No files will be modified.</p>";
          try {
            const response = await fetch("/api/ai-task", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                provider: "auto",
                instruction: `Review ${path} as an incoming FiveM script. Use memory/playbooks/fivem-script-integration-checklist.md. Report framework, dependencies, SQL/config risks, staging-only recommendations, and next action. Do not edit files.`
              }),
            });
            const body = await response.json();
            if (!response.ok) throw new Error(body.detail || body.error || "AI check failed.");
            if (body.status === "failed") throw new Error(body.stderr || body.stdout || "AI check failed.");
            resultCard.innerHTML = `
              <h2>AI Integration Check Complete</h2>
              <p>Provider used: ${body.provider_used || "unknown"}</p>
              <div class="result-actions">
                <a href="${body.report_url || "#"}">Open AI report</a>
                <a href="/reviews">Open Reviews</a>
              </div>
            `;
          } catch (error) {
            resultCard.innerHTML = `<h2>AI Integration Check Failed</h2><p>${String(error.message || error)}</p>`;
          } finally {
            if (button) {
              button.disabled = false;
              button.textContent = original;
            }
          }
        }

        document.addEventListener("click", event => {
          const button = event.target.closest(".ai-check-button");
          if (!button) return;
          runAiCheck(button.dataset.path, button);
        });

        async function runAnalyze(scriptName, button) {
          if (!scriptName) return;
          const original = button ? button.textContent : "";
          if (button) {
            button.disabled = true;
            button.textContent = "Analyzing...";
          }
          const summaryEl = document.getElementById("analysis-" + scriptName);
          try {
            const response = await fetch("/api/incoming/" + encodeURIComponent(scriptName) + "/analyze", {
              method: "POST",
            });
            const body = await response.json();
            if (!response.ok) throw new Error(body.detail || body.error || "Analysis failed.");

            if (body.status === "success" && body.summary) {
              const s = body.summary;
              const actionText = getActionLabel(s.recommended_action);

              if (summaryEl) {
                summaryEl.innerHTML = `
                  <div class="analysis-result">
                    <span class="analysis-badge framework">${escapeHtml(s.framework)}</span>
                    <span class="analysis-badge inventory">${escapeHtml(s.inventory)}</span>
                    <span class="analysis-badge target">${escapeHtml(s.target)}</span>
                    <span class="analysis-badge database">${escapeHtml(s.database)}</span>
                    <span class="analysis-badge risk" style="color:${getRiskColor(s.risk)}">Risk: ${escapeHtml(s.risk)}</span>
                    <span class="analysis-action">${escapeHtml(actionText)}</span>
                  </div>
                `;
              }
              if (button) {
                button.textContent = "Analyzed";
              }
            } else {
              throw new Error(body.error || "Analysis failed");
            }
          } catch (error) {
            if (summaryEl) {
              summaryEl.innerHTML = `<span class="analysis-error">Error: ${String(error.message || error)}</span>`;
            }
            if (button) {
              button.textContent = original;
              button.disabled = false;
            }
          }
        }

        document.addEventListener("click", event => {
          const button = event.target.closest(".analyze-button");
          if (!button) return;
          runAnalyze(button.dataset.script, button);
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


@app.get("/api/reports")
def api_reports(limit: int = Query(default=80, ge=1, le=200)) -> dict[str, Any]:
    return {"reports": _report_entries(limit)}


@app.get("/api/reports/read")
def api_report_read(path: str = Query(..., min_length=1)) -> dict[str, Any]:
    report_path = _safe_workspace_file(path, "reports")
    return {
        "path": _relative_to_base(report_path),
        "name": report_path.name,
        "content": _read_text_preview(report_path),
        "updated_at": datetime.fromtimestamp(report_path.stat().st_mtime, timezone.utc).isoformat(),
    }


@app.get("/reports/view", response_class=HTMLResponse)
def report_file_view(path: str = Query(..., min_length=1)) -> str:
    report_path = _safe_workspace_file(path, "reports")
    content_text = _read_text_preview(report_path)
    rel = _relative_to_base(report_path)
    content = f"""
      <section class="agent-panel">
        <div class="card-title-row">
          <h2>{esc(report_path.name)}</h2>
          {_status_pill("read-only")}
        </div>
        <p class="subtle-id">{esc(rel)} · {esc(_format_timestamp(datetime.fromtimestamp(report_path.stat().st_mtime, timezone.utc).isoformat()))}</p>
        <div class="agent-actions">
          <a class="button" href="/reviews">Back to Reviews</a>
          <a class="button secondary" href="/staging">Open Staging</a>
        </div>
      </section>
      <section class="agent-panel report-view">
        <h2>Report Content</h2>
        <pre>{esc(content_text)}</pre>
      </section>
    """
    return app_view_html("Report", "reviews", content, subtitle=rel)


@app.get("/api/staging")
def api_staging() -> dict[str, Any]:
    entries = []
    for entry in _staging_entries():
        copy = dict(entry)
        copy["path"] = _relative_to_base(Path(str(copy["path"])))
        copy["url"] = f"/staging/{copy['task_id']}"
        entries.append(copy)
    return {"staging": entries}


@app.post("/api/staging/{resource}/create")
def api_staging_create(resource: str) -> dict[str, Any]:
    """Create a staging-safe copy of an incoming resource."""
    safe_resource = _safe_resource_name(resource)
    incoming_dir = _incoming_resource_dir(safe_resource)
    staging_dir = _staging_resource_dir(safe_resource)

    if staging_dir.exists():
        raise HTTPException(status_code=409, detail="Staging copy already exists")

    shutil.copytree(incoming_dir, staging_dir)

    analysis_report = _latest_analysis_report_path(safe_resource)
    patch_plan = _patch_plan_json_path(safe_resource)
    risk_level = _compute_analysis_risk(safe_resource)
    now = _utc_now()
    stage_info = {
        "resource": safe_resource,
        "timestamp": now,
        "original_incoming_path": _relative_to_base(incoming_dir),
        "staging_path": _relative_to_base(staging_dir),
        "analysis_report_path": _relative_to_base(analysis_report) if analysis_report else None,
        "patch_plan_path": _relative_to_base(patch_plan) if patch_plan else None,
        "status": "STAGED",
        "staged_by": "dashboard-v2",
        "risk_level": risk_level,
        "approved_at": None,
    }
    _write_stage_info(safe_resource, stage_info)

    diff = _build_staging_diff(safe_resource)
    orch_stage_dir = _orchestrator_staging_dir(safe_resource)
    orch_stage_dir.mkdir(parents=True, exist_ok=True)
    (orch_stage_dir / "diff.json").write_text(json.dumps(diff, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "status": "success",
        "resource": safe_resource,
        "staging_path": _relative_to_base(staging_dir),
        "stage_info_path": _relative_to_base(orch_stage_dir / "stage-info.json"),
        "diff_path": _relative_to_base(orch_stage_dir / "diff.json"),
        "staging_status": diff.get("status", "STAGED"),
    }


@app.get("/api/staging/{resource}/diff")
def api_staging_diff(resource: str) -> dict[str, Any]:
    safe_resource = _safe_resource_name(resource)
    diff = _build_staging_diff(safe_resource)
    stage_info = _read_stage_info(safe_resource) or {}
    # Keep stage status synchronized with current diff state for UI badges.
    if stage_info:
        if str(stage_info.get("status", "")).upper() != "APPROVED":
            stage_info["status"] = diff["status"]
            _write_stage_info(safe_resource, stage_info)
    orch_stage_dir = _orchestrator_staging_dir(safe_resource)
    orch_stage_dir.mkdir(parents=True, exist_ok=True)
    (orch_stage_dir / "diff.json").write_text(json.dumps(diff, indent=2, sort_keys=True), encoding="utf-8")
    return diff


@app.post("/api/staging/{resource}/approve")
def api_staging_approve(resource: str) -> dict[str, Any]:
    safe_resource = _safe_resource_name(resource)
    stage_info = _read_stage_info(safe_resource)
    if not stage_info:
        raise HTTPException(status_code=404, detail="Staging info not found")
    stage_info["status"] = "APPROVED"
    stage_info["approved_at"] = _utc_now()
    _write_stage_info(safe_resource, stage_info)
    return {
        "status": "success",
        "resource": safe_resource,
        "staging_status": "APPROVED",
        "approved_at": stage_info["approved_at"],
    }


@app.delete("/api/staging/{resource}")
def api_staging_delete(resource: str) -> dict[str, Any]:
    safe_resource = _safe_resource_name(resource)
    staging_dir = _staging_resource_dir(safe_resource)
    orch_staging_dir = _orchestrator_staging_dir(safe_resource)

    if not staging_dir.exists() and not orch_staging_dir.exists():
        raise HTTPException(status_code=404, detail="Staging copy not found")

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    if orch_staging_dir.exists():
        shutil.rmtree(orch_staging_dir)

    return {
        "status": "success",
        "resource": safe_resource,
        "deleted": True,
    }


@app.get("/api/incoming")
def api_incoming() -> dict[str, Any]:
    return {"incoming": _incoming_entries()}


@app.get("/api/upload-jobs")
def api_upload_jobs() -> dict[str, Any]:
    return {"jobs": _upload_jobs()}


@app.post("/api/ai-task")
def api_ai_task(payload: AITaskRequest) -> dict[str, Any]:
    provider = payload.provider.strip().lower() or "auto"
    if provider not in {"auto", "codex", "gemini", "opencode"}:
        raise HTTPException(status_code=400, detail="Invalid AI provider.")
    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Instruction is required.")
    command = ["/home/agentzero/scripts/ai-task"]
    if provider != "auto":
        command.extend(["--provider", provider])
    command.append(instruction[:4000])
    env = os.environ.copy()
    env.setdefault("AI_TASK_TIMEOUT_SECONDS", "75")
    try:
        completed = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=260,
            check=False,
            env=env,
        )
        result = {"stdout": completed.stdout, "stderr": completed.stderr, "exit_code": completed.returncode}
    except subprocess.TimeoutExpired as error:
        result = {
            "stdout": error.stdout or "",
            "stderr": (error.stderr or "") + "\nAI task router timed out.",
            "exit_code": 124,
        }
    output = (result.get("stdout") or "").strip()
    report_path = ""
    provider_used = "none"
    for line in output.splitlines():
        if line.startswith("Provider used:"):
            provider_used = line.split(":", 1)[1].strip()
        if line.startswith(str(BASE_DIR / "reports")):
            report_path = line.strip()
    report_url = ""
    if report_path:
        try:
            rel = Path(report_path).resolve().relative_to(BASE_DIR.resolve()).as_posix()
            report_url = f"/reports/view?path={quote(rel)}"
        except ValueError:
            report_url = ""
    if int(result.get("exit_code", 1)) != 0:
        return {
            "status": "failed",
            "provider_used": provider_used,
            "report_path": report_path,
            "report_url": report_url,
            "stdout": output,
            "stderr": result.get("stderr", ""),
            "exit_code": result.get("exit_code"),
        }
    return {
        "status": "complete",
        "provider_used": provider_used,
        "report_path": report_path,
        "report_url": report_url,
        "exit_code": result.get("exit_code"),
    }


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


# AGENTOS ANALYZE UPLOAD START

def _safe_incoming_script_name(script_name: str) -> str:
    """Validate incoming script folder name used by analyze endpoints."""
    value = _safe_named_item(script_name.strip(), "script name")
    if value in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid script name.")
    return value


def _resolve_incoming_script_dir(script_name: str) -> Path:
    """
    Resolve script directory under incoming/ and enforce containment.
    This is the canonical path guard for analyze endpoints.
    """
    incoming_root = (BASE_DIR / "incoming").resolve()
    script_path = (incoming_root / script_name).resolve()
    if incoming_root not in script_path.parents:
        raise HTTPException(status_code=400, detail="Script path must stay under incoming/.")
    if not script_path.exists():
        raise HTTPException(status_code=404, detail=f"Script not found: {script_name}")
    if not script_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {script_name}")
    return script_path


def _build_analysis_report_path(script_name: str) -> Path:
    """
    Build a unique report file path.
    Keep reports append-only to avoid accidental overwrite during same-second requests.
    """
    reports_dir = BASE_DIR / "reports" / "analysis"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    unique = uuid4().hex[:8]
    return reports_dir / f"analysis-{script_name}-{timestamp}-{unique}.json"


def _analyze_fivem_script(script_name: str) -> dict[str, Any]:
    """Analyze a FiveM script in the incoming folder (read-only)."""
    if not BUILDER_SCANNER_AVAILABLE:
        return {
            "error": "Builder scanner not available",
            "script_path": None,
            "status": "error",
        }

    try:
        script_path = _resolve_incoming_script_dir(script_name)
    except HTTPException as error:
        return {"error": str(error.detail), "script_path": None, "status": "error"}

    try:
        config = PlannerConfig()
        scanner = ScriptScanner(config)
        # ScriptScanner resolves relative paths from agents root, not incoming root.
        # Pass an explicit incoming-relative path so valid incoming resources are accepted
        # while scanner/path guards still block traversal and escaped locations.
        scanner_target = (Path("incoming") / script_name).as_posix()
        result = scanner.scan(scanner_target)

        result["status"] = "analyzed"
        result["analyzed_at"] = datetime.now(timezone.utc).isoformat()

        return result
    except Exception as e:
        return {
            "error": str(e),
            "script_path": str(script_path),
            "status": "error",
        }


def _save_analysis_report(script_name: str, analysis: dict[str, Any]) -> Path:
    """Save analysis report to reports folder."""
    report_file = _build_analysis_report_path(script_name)

    report_data = {
        "script_name": script_name,
        "analyzed_at": analysis.get("analyzed_at", datetime.now(timezone.utc).isoformat()),
        "status": analysis.get("status", "unknown"),
        "script_path": analysis.get("script_path"),
        "files_count": len(analysis.get("files", [])),
        "markers": analysis.get("markers", {}),
        "findings": analysis.get("findings", []),
        "dependencies": analysis.get("dependencies", []),
        "full_analysis": analysis,
    }

    report_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    return report_file


def _generate_analysis_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    """Generate a human-readable summary of the analysis."""
    markers = analysis.get("markers", {})

    framework = "standalone"
    if "QBCore" in markers.get("framework", {}):
        framework = "QBCore"
    elif "ESX" in markers.get("framework", {}):
        framework = "ESX"
    elif "Qbox" in markers.get("framework", {}):
        framework = "Qbox"

    inventory = "none"
    if "qb-inventory" in markers.get("inventory", {}):
        inventory = "qb-inventory"
    elif "ox_inventory" in markers.get("inventory", {}):
        inventory = "ox_inventory"
    elif "ps-inventory" in markers.get("inventory", {}):
        inventory = "ps-inventory"

    target = "none"
    if "qb-target" in markers.get("target", {}):
        target = "qb-target"
    elif "ox_target" in markers.get("target", {}):
        target = "ox_target"

    database = "none"
    if "oxmysql" in markers.get("database", {}):
        database = "oxmysql"
    elif "mysql-async" in markers.get("database", {}):
        database = "mysql-async"
    elif "ghmattimysql" in markers.get("database", {}):
        database = "ghmattimysql"

    findings = analysis.get("findings", [])
    risk_level = "low"
    for finding in findings:
        if finding.get("severity") == "high":
            risk_level = "high"
            break
        elif finding.get("severity") == "medium" and risk_level != "high":
            risk_level = "medium"

    sql_files = analysis.get("sql_files", [])
    has_sql = len(sql_files) > 0

    recommended = "safe"
    if has_sql:
        recommended = "manual-sql"
    if risk_level == "high":
        recommended = "review-required"
    if framework == "ESX":
        recommended = "adaptation-needed"

    return {
        "framework": framework,
        "inventory": inventory,
        "target": target,
        "database": database,
        "risk": risk_level,
        "has_sql": has_sql,
        "recommended_action": recommended,
    }


@app.post("/api/incoming/{script_name}/analyze")
async def analyze_incoming_script(script_name: str) -> dict[str, Any]:
    """Analyze a FiveM script in the incoming folder (read-only, no server modifications)."""
    safe_name = _safe_incoming_script_name(script_name)
    _resolve_incoming_script_dir(safe_name)

    # Scanner reads many files; run in worker thread to avoid blocking event loop.
    analysis = await run_in_threadpool(_analyze_fivem_script, safe_name)

    if analysis.get("error"):
        return {
            "status": "error",
            "error": analysis.get("error"),
            "script_name": safe_name,
        }

    report_path = await run_in_threadpool(_save_analysis_report, safe_name, analysis)
    summary = _generate_analysis_summary(analysis)

    return {
        "status": "success",
        "script_name": safe_name,
        "report_path": str(report_path),
        "summary": summary,
        "files_count": len(analysis.get("files", [])),
        "findings_count": len(analysis.get("findings", [])),
    }


@app.get("/api/incoming/{script_name}/analysis_report")
async def get_analysis_report(script_name: str) -> dict[str, Any]:
    """Get the latest analysis report for a script."""
    safe_name = _safe_incoming_script_name(script_name)

    reports_dir = BASE_DIR / "reports" / "analysis"
    if not reports_dir.is_dir():
        return {"status": "no_reports", "message": "No analysis reports found"}

    reports = sorted(
        reports_dir.glob(f"analysis-{safe_name}-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not reports:
        return {"status": "not_analyzed", "message": f"No analysis found for {safe_name}"}

    try:
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        summary = _generate_analysis_summary(report.get("full_analysis", {}))
        return {
            "status": "found",
            "report_path": str(reports[0]),
            "analyzed_at": report.get("analyzed_at"),
            "summary": summary,
            "full_report": report,
        }
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "error", "error": str(e)}


# AGENTOS ANALYZE UPLOAD END

# PATCH PLAN GENERATION START
import re as patch_re
from typing import Any as PatchAny

try:
    from orchestrator.patch_plan_generator import (
        get_patch_plan_generator,
        generate_patch_plan_background,
    )
    PATCH_PLAN_GENERATOR_AVAILABLE = True
    PATCH_PLAN_IMPORT_ERROR = ""
except Exception as exc:
    PATCH_PLAN_GENERATOR_AVAILABLE = False
    PATCH_PLAN_IMPORT_ERROR = str(exc)
    get_patch_plan_generator = None
    generate_patch_plan_background = None


def _safe_resource_id(resource_id: str) -> str:
    safe = patch_re.sub(r"[^A-Za-z0-9_\-]", "", resource_id)
    if safe != resource_id:
        return ""
    return safe


def _latest_analysis_report_for_resource(resource_id: str) -> Path | None:
    reports_dir = (BASE_DIR / "reports" / "analysis").resolve()
    if not reports_dir.is_dir():
        return None
    reports = sorted(
        reports_dir.glob(f"analysis-{resource_id}-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


@app.post("/api/analysis/{resource_id}/generate-patch-plan")
async def generate_patch_plan(resource_id: str, force: bool = False) -> dict[str, PatchAny]:
    """Trigger patch plan generation for an analyzed resource."""
    if not PATCH_PLAN_GENERATOR_AVAILABLE:
        detail = "Patch plan generator not available"
        if PATCH_PLAN_IMPORT_ERROR:
            detail += f": {PATCH_PLAN_IMPORT_ERROR}"
        raise HTTPException(status_code=500, detail=detail)

    safe_name = _safe_resource_id(resource_id)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid resource_id")

    incoming_dir = BASE_DIR / "incoming" / safe_name
    if not incoming_dir.exists():
        raise HTTPException(status_code=404, detail=f"Resource {safe_name} not found")

    report_path = _latest_analysis_report_for_resource(safe_name)
    if not report_path:
        raise HTTPException(status_code=400, detail="No analysis exists for this resource")
    try:
        json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Malformed analysis report for this resource")

    generator = get_patch_plan_generator()
    result = generator.generate(safe_name, force=force)
    return result


@app.get("/api/analysis/{resource_id}/patch-plan/json")
async def get_patch_plan_json(resource_id: str) -> dict[str, PatchAny]:
    """Get patch plan in JSON format."""
    if not PATCH_PLAN_GENERATOR_AVAILABLE:
        detail = "Patch plan generator not available"
        if PATCH_PLAN_IMPORT_ERROR:
            detail += f": {PATCH_PLAN_IMPORT_ERROR}"
        raise HTTPException(status_code=500, detail=detail)

    safe_name = _safe_resource_id(resource_id)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid resource_id")

    generator = get_patch_plan_generator()
    result = generator.get_patch_plan(safe_name, format="json")
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/analysis/{resource_id}/patch-plan/md")
async def get_patch_plan_md(resource_id: str) -> dict[str, PatchAny]:
    """Get patch plan in Markdown format."""
    if not PATCH_PLAN_GENERATOR_AVAILABLE:
        detail = "Patch plan generator not available"
        if PATCH_PLAN_IMPORT_ERROR:
            detail += f": {PATCH_PLAN_IMPORT_ERROR}"
        raise HTTPException(status_code=500, detail=detail)

    safe_name = _safe_resource_id(resource_id)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid resource_id")

    generator = get_patch_plan_generator()
    md_content = generator.get_patch_plan(safe_name, format="md")
    if isinstance(md_content, dict) and "error" in md_content:
        raise HTTPException(status_code=404, detail=md_content["error"])
    return {"content": md_content, "format": "markdown"}


@app.get("/api/analysis/{resource_id}/patch-plan/status")
async def get_patch_plan_status(resource_id: str) -> dict[str, PatchAny]:
    """Get patch plan generation status."""
    if not PATCH_PLAN_GENERATOR_AVAILABLE:
        detail = "Patch plan generator not available"
        if PATCH_PLAN_IMPORT_ERROR:
            detail += f": {PATCH_PLAN_IMPORT_ERROR}"
        raise HTTPException(status_code=500, detail=detail)

    safe_name = _safe_resource_id(resource_id)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid resource_id")

    generator = get_patch_plan_generator()
    status = generator.get_status(safe_name)
    if status.get("status") == "pending":
        # Keep status endpoint explicit when no plan exists yet.
        return {
            **status,
            "message": "No patch plan generated yet",
        }
    return status


# PATCH PLAN GENERATION END


# AGENTOS PROMPT HANDOFF START
PROMPTS_DIR = BASE_DIR / "orchestrator" / "prompts"
PROMPTS_ARCHIVE_DIR = PROMPTS_DIR / "archive"
OPENCODE_PROMPT_LATEST = PROMPTS_DIR / "opencode-next.md"
CODEX_AUDIT_PROMPT_LATEST = PROMPTS_DIR / "codex-audit-next.md"


def _ensure_prompt_layout() -> None:
    PROMPTS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    if not OPENCODE_PROMPT_LATEST.exists():
        OPENCODE_PROMPT_LATEST.write_text("", encoding="utf-8")
    if not CODEX_AUDIT_PROMPT_LATEST.exists():
        CODEX_AUDIT_PROMPT_LATEST.write_text("", encoding="utf-8")


def _safe_patch_plan_path(resource_id: str) -> Path:
    safe_name = _safe_resource_id(resource_id)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid resource_id")
    patch_root = (BASE_DIR / "orchestrator" / "archive").resolve()
    candidate = (patch_root / safe_name / "patch-plan.json").resolve()
    try:
        candidate.relative_to(patch_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid resource path") from exc
    return candidate


def _archive_existing_prompt(latest_path: Path, resource_id: str, prompt_type: str) -> None:
    if not latest_path.exists():
        return
    existing = latest_path.read_text(encoding="utf-8").strip()
    if not existing:
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_name = f"{resource_id}_{prompt_type}_{timestamp}.md"
    archive_path = PROMPTS_ARCHIVE_DIR / archive_name
    archive_path.write_text(existing, encoding="utf-8")


def _build_opencode_prompt(resource_id: str, patch_plan: dict[str, Any], generated_at: str) -> str:
    risks = patch_plan.get("risk_summary") or {}
    migration = patch_plan.get("migration_targets") or {}
    phases = patch_plan.get("phases") or []
    high_risks = risks.get("high", [])
    medium_risks = risks.get("medium", [])

    return f"""# OpenCode Implementation Prompt

Resource: {resource_id}
Generated At (UTC): {generated_at}
Source Patch Plan: orchestrator/archive/{resource_id}/patch-plan.json

Implement the patch plan for this FiveM resource with strict safety controls.

Safety constraints (mandatory):
- Staging-only modifications; do not modify live FiveM server files.
- Create backups before editing any script files.
- Use AGENT FIX START and AGENT FIX END markers around major generated changes.
- Run syntax validation checks for touched files before completing.
- Provide a changed-files summary with brief rationale for each change.
- Do NOT run git push.
- Do NOT run txAdmin restart.
- Do NOT perform live server edits.

Detected risks from patch plan:
- High risk findings: {json.dumps(high_risks, ensure_ascii=True)}
- Medium risk findings: {json.dumps(medium_risks, ensure_ascii=True)}

Migration targets:
{json.dumps(migration, indent=2, ensure_ascii=True)}

Execution scope:
- Follow patch-plan phases and proposed edits only.
- If a step is ambiguous, stop and report assumptions before applying changes.

Patch-plan phases:
{json.dumps(phases, indent=2, ensure_ascii=True)}
"""


def _build_codex_audit_prompt(resource_id: str, patch_plan: dict[str, Any], generated_at: str) -> str:
    return f"""# Codex Stabilization Audit Prompt

Resource: {resource_id}
Generated At (UTC): {generated_at}
Source Patch Plan: orchestrator/archive/{resource_id}/patch-plan.json

Audit OpenCode implementation results against the patch plan.

Audit requirements (mandatory):
- Verify AGENT FIX START / AGENT FIX END markers exist around major generated edits.
- Verify no live server modifications were made.
- Verify no txAdmin restart, apply, or staging automation was triggered.
- Verify syntax checks passed for changed files.
- Verify changed-files summary is present and accurate.
- Verify implementation remains compliant with patch-plan scope.

Security checks:
- Confirm no path traversal or unsafe file writes were introduced.
- Confirm no secrets, env files, caches, backups, or runtime artifacts were committed.

Deliverable:
- List findings by severity (critical/high/medium/low).
- Include precise file references and minimal remediation actions.
- Mark whether patch-plan compliance is PASS or FAIL with reasons.

Patch-plan metadata:
{json.dumps(patch_plan.get("metadata", {}), indent=2, ensure_ascii=True)}
"""


def _write_generated_prompts(resource_id: str, patch_plan: dict[str, Any]) -> dict[str, Any]:
    _ensure_prompt_layout()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _archive_existing_prompt(OPENCODE_PROMPT_LATEST, resource_id, "opencode")
    _archive_existing_prompt(CODEX_AUDIT_PROMPT_LATEST, resource_id, "codex")

    opencode_prompt = _build_opencode_prompt(resource_id, patch_plan, generated_at)
    codex_prompt = _build_codex_audit_prompt(resource_id, patch_plan, generated_at)

    OPENCODE_PROMPT_LATEST.write_text(opencode_prompt, encoding="utf-8")
    CODEX_AUDIT_PROMPT_LATEST.write_text(codex_prompt, encoding="utf-8")

    archive_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    opencode_archive = PROMPTS_ARCHIVE_DIR / f"{resource_id}_opencode_{archive_timestamp}.md"
    codex_archive = PROMPTS_ARCHIVE_DIR / f"{resource_id}_codex_{archive_timestamp}.md"
    opencode_archive.write_text(opencode_prompt, encoding="utf-8")
    codex_archive.write_text(codex_prompt, encoding="utf-8")

    return {
        "status": "success",
        "resource_id": resource_id,
        "generated_at": generated_at,
        "latest": {
            "opencode": str(OPENCODE_PROMPT_LATEST),
            "codex_audit": str(CODEX_AUDIT_PROMPT_LATEST),
        },
        "archive": {
            "opencode": str(opencode_archive),
            "codex_audit": str(codex_archive),
        },
    }


def _read_prompt_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt file not found: {path.name}")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise HTTPException(status_code=404, detail=f"Prompt file is empty: {path.name}")
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"path": str(path), "generated_at": mtime, "content": content}


@app.post("/api/patch-plan/{resource_id}/generate-opencode-prompt")
async def generate_opencode_prompt(resource_id: str) -> dict[str, Any]:
    patch_plan_path = _safe_patch_plan_path(resource_id)
    if not patch_plan_path.exists():
        raise HTTPException(status_code=404, detail="Patch plan not found for resource")
    try:
        patch_plan = json.loads(patch_plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Malformed patch plan: {exc}") from exc
    return _write_generated_prompts(_safe_resource_id(resource_id), patch_plan)


@app.get("/api/prompts/opencode-next")
async def get_opencode_prompt_latest() -> dict[str, Any]:
    return _read_prompt_file(OPENCODE_PROMPT_LATEST)


@app.get("/api/prompts/codex-audit-next")
async def get_codex_audit_prompt_latest() -> dict[str, Any]:
    return _read_prompt_file(CODEX_AUDIT_PROMPT_LATEST)


def _prompt_view_page(title: str, subtitle: str, prompt_data: dict[str, Any], source_label: str) -> str:
    content = f"""
    <section class="ao-card">
        <h2>{esc(title)}</h2>
        <p><strong>Resource:</strong> {esc(source_label)}</p>
        <p><strong>Generated:</strong> {esc(prompt_data.get("generated_at", "unknown"))}</p>
        <div class="index-actions">
            <button class="button" onclick="copyPrompt()">Copy</button>
            <a class="button secondary" href="/dashboard-v2">Back to Dashboard V2</a>
        </div>
        <pre id="prompt-content" style="max-height:65vh;overflow:auto;white-space:pre-wrap;background:#050914;border:1px solid #2a3348;padding:14px;border-radius:8px;color:#e7edf8;">{esc(prompt_data.get("content", ""))}</pre>
    </section>
    """
    extra_js = """
    <script>
    function copyPrompt() {
        const text = document.getElementById("prompt-content")?.textContent || "";
        navigator.clipboard.writeText(text).then(() => alert("Prompt copied."));
    }
    </script>
    """
    return render_layout(title, "dashboard-v2", content, "", extra_js, subtitle=subtitle)


@app.get("/dashboard-v2/opencode-prompt", response_class=HTMLResponse)
def view_opencode_prompt_page() -> str:
    data = _read_prompt_file(OPENCODE_PROMPT_LATEST)
    match = re.search(r"^Resource:\s*([A-Za-z0-9_-]+)\s*$", data["content"], re.MULTILINE)
    resource_name = match.group(1) if match else "unknown"
    return _prompt_view_page("OpenCode Prompt", "Latest OpenCode implementation prompt", data, resource_name)


@app.get("/dashboard-v2/codex-audit-prompt", response_class=HTMLResponse)
def view_codex_prompt_page() -> str:
    data = _read_prompt_file(CODEX_AUDIT_PROMPT_LATEST)
    match = re.search(r"^Resource:\s*([A-Za-z0-9_-]+)\s*$", data["content"], re.MULTILINE)
    resource_name = match.group(1) if match else "unknown"
    return _prompt_view_page("Codex Audit Prompt", "Latest Codex stabilization audit prompt", data, resource_name)
# AGENTOS PROMPT HANDOFF END


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
