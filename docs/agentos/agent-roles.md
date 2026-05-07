# AgentOS Agent Roles (Phase 1)

Phase 1 introduces lightweight, file-based agent role definitions that the orchestrator/router can optionally reference when routing steps. This is intentionally minimal: no UI changes, no automation expansion, and no database changes.

Role definitions live in `orchestrator/roles/` as `.yaml` files containing JSON objects (JSON is YAML 1.2 compatible). They are loaded by `orchestrator/roles_loader.py`.

## Roles

Each role file includes the same required fields:
`id`, `name`, `description`, `responsibilities`, `preferred_model`, `fallback_model`, `cost_tier`, `allowed_actions`, `requires_approval_for`, `inputs`, `outputs`, `validation_expectations`, `handoff_to`, `safety_notes`.

### planner
Use for: turning a request into a safe plan, identifying risks, and defining approval checkpoints.

### architect
Use for: module boundaries, interfaces, integration strategy, and minimal-change designs.

### builder
Use for: implementing scoped features and file changes, keeping diffs focused.

### reviewer
Use for: final correctness/risk review and surgical fixes.

### fivem_integrator
Use for: FiveM/QBCore compatibility assessment, adapters, and reports.
Hard rules: do not edit `qb-core` directly; stop and request approval before any money/inventory/permissions/player-data changes.

### system_agent
Use for: environment diagnostics and safe operational guidance.
Hard rule: privileged actions (for example `sudo`, `systemctl`, service restarts) must be explicitly approved.

### maintenance_agent
Use for: task-scoped cleanup, docs updates, lightweight validation runs.

### git_agent
Use for: local git state/diff reporting and commit/branch management only when explicitly requested.
Hard rule: never `git push` without an explicit request.

### deployment_agent
Use for: deployment runbooks and checklists. Phase 1 defaults to manual/approval-gated actions.

### memory_agent
Use for: durable summaries/decision logs and structured handoff notes.
Hard rule: never store secrets (tokens, credentials, private keys).

## Model/Tool Guidance

In AgentOS routing, `preferred_model` is treated as a *tool hint* where possible.

- Gemini (`gemini`): planning, architecture, design tradeoffs, step decomposition.
- OpenCode (`opencode`): bulk implementation, file creation, straightforward feature work.
- Codex (`codex`): high-signal review, debugging, surgical fixes, higher-risk reasoning tasks.
- Ollama/local (`ollama`): summaries, log parsing, lightweight offline analysis, fast triage.
- Local scripts (`local_script`): repo-local scripts and automation (git helpers, deploy scripts).
- Manual (`manual`): actions that must not execute automatically (production deploys, privileged ops).

If a role’s `preferred_model` does not map to a known tool type, the router keeps its existing behavior (Phase 1 is “best effort”).

## Approval Boundaries (Phase 1)

Treat these as approval-gated:
- Privileged operations: `sudo`, `systemctl`, service restarts.
- Destructive operations: deletes, force operations, history rewrites, `rm -rf`.
- Package installs and environment mutation.
- Database schema/data changes.
- Deployments / production changes.
- `git push` (and anything that publishes externally).

## How It Connects To The Orchestrator

- `orchestrator/roles_loader.py` loads and validates role files.
- `orchestrator/router.py` optionally uses roles:
  - Attaches `role_id` metadata to routed steps when it can confidently match a role.
  - If the role’s `preferred_model` matches an existing `ToolType`, it uses that as the tool hint.
  - If roles fail to load or don’t match, routing remains unchanged.

## Commands

Validate and print loaded roles:
```bash
python3 -m orchestrator.roles_loader --validate
```

List role ids:
```bash
python3 -m orchestrator.roles_loader --list
```

Recommend a role for a task description:
```bash
python3 -m orchestrator.roles_loader --recommend "Integrate a new FiveM resource and write a compatibility report"
```

Or via orchestrator CLI:
```bash
python3 orchestrator/run.py roles --validate
```

