# AgentOS Checkpoint - 2026-05-04

## Repo State

- Repository: `/home/agentzero/agents`
- Current commit: `7ad411d1d3dcd02f0deb6884bd6c7c9ae2d5d097`
- Current branch: `master`
- Final git status before report creation: clean

After this report was created, `git status` should show this file as untracked or modified until it is committed.

## Major Changes Today

- AgentOS repo restructure:
  - Organized app code into clearer top-level folders: `apps/`, `bots/`, `cli/`, and `core/`.
  - Preserved compatibility shims at legacy root paths where needed.
- App rename and compatibility shims:
  - Main AgentOS app source now lives at `apps/agentos_agent/app.py`.
  - `api.py` remains as a compatibility shim.
  - `agentos_app.py` remains as a compatibility shim for the current systemd `uvicorn agentos_app:app` command.
  - Root compatibility packages remain for `builder_agent`, `coding_agent`, and `agent_core`.
- Agent registry and `/agents` page:
  - Added a maintainable agent registry for known agents and tools.
  - Added `/agents` page with full agent/tool details.
  - Sidebar Agents section was grouped by role for readability.
- Ops Cheat Sheet page:
  - Added `/ops` page for frequently used Linux, service, Git, agent, and troubleshooting commands.
  - Added search, category filtering, copy buttons with clipboard fallback, badges, warnings, and expandable details.
- Builder Agent and Coding Agent status:
  - Both dashboards remain reachable and running under systemd.
- `.gitignore` runtime cleanup:
  - Confirmed Python cache ignores.
  - Added `memory/*.sqlite`.

## Service Status

### agentos

- Unit: `agentos.service`
- Loaded: `/etc/systemd/system/agentos.service`
- Enabled: yes
- Status: active running
- Main process: `uvicorn agentos_app:app --host 0.0.0.0 --port 8080`

### builder-agent

- Unit: `builder-agent.service`
- Loaded: `/etc/systemd/system/builder-agent.service`
- Enabled: yes
- Status: active running
- Main process: `uvicorn builder_agent.app:app --host 100.68.10.125 --port 8010`

### coding-agent

- Unit: `coding-agent.service`
- Loaded: `/etc/systemd/system/coding-agent.service`
- Enabled: yes
- Status: active running
- Main process: `uvicorn coding_agent.app:app --host 127.0.0.1 --port 8020`

## Auto-Start Status

- `agentos`: enabled
- `builder-agent`: enabled
- `coding-agent`: enabled

## Endpoint Health Checks

- AgentOS 8080: `AgentOS 200`
- Builder 8010: `Builder 200`
- Coding 8020: `Coding 200`

## Remaining Warnings

- `memory/builder-agent-memory.sqlite` is still tracked by Git. The new `.gitignore` rule prevents new matching files from being added, but it does not untrack files already in the repository.
- `coding-agent` logs include a harmless `/favicon.ico` `404`; the main endpoint and health endpoint respond successfully.
- Compatibility shims still exist intentionally:
  - `api.py`
  - `agentos_app.py`
  - `builder_agent/__init__.py`
  - `coding_agent/__init__.py`
  - `agent_core/__init__.py`
  - `bubbles.py`
  - `mailman.py`
  - `fivem-agent`

## Suggested Next Session Plan

1. Safely untrack `memory/builder-agent-memory.sqlite` if desired, without deleting the local file.
2. Update systemd `ExecStart` commands to use the new app paths after confirming compatibility.
3. Add service control buttons in AgentOS for approved start, stop, restart, and status workflows.
4. Improve `coding_agent` from the current placeholder/dashboard behavior into a real scanner.

## Commands To Resume Tomorrow

```bash
cd /home/agentzero/agents
git status
git log --oneline -5
systemctl status agentos
systemctl status builder-agent
systemctl status coding-agent
systemctl is-enabled agentos builder-agent coding-agent
curl -s -o /dev/null -w "AgentOS %{http_code}\n" http://100.68.10.125:8080
curl -s -o /dev/null -w "Builder %{http_code}\n" http://100.68.10.125:8010
curl -s -o /dev/null -w "Coding %{http_code}\n" http://127.0.0.1:8020
```

