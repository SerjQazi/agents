# OpenCode Fallback Workflow

OpenCode is installed as a global, API-based fallback coding agent for `/home/agentzero/agents`. It does not require local models. Codex remains primary; Gemini report tooling remains the lightweight cloud fallback for bounded checks.

## Installed Command

```bash
cd /home/agentzero/agents
opencode
```

The `opencode` command resolves to `/home/agentzero/.local/bin/opencode`. An explicit shell alias is also available from `~/.bash_aliases`.

## API Setup

Use environment variables or OpenCode's provider login flow. Do not commit keys.

```bash
export GEMINI_API_KEY="your-google-ai-key"
export OPENROUTER_API_KEY="your-openrouter-key"
```

Project config lives in `opencode.json` and defines API-only providers:

- `gemini/gemini-2.5-pro`
- `gemini/gemini-2.5-flash`
- `openrouter/google/gemini-2.5-pro`
- `openrouter/google/gemini-2.5-flash`
- `openrouter/anthropic/claude-sonnet-4.5`
- `openrouter/openai/gpt-5.1-codex`

Run one model explicitly:

```bash
opencode -m gemini/gemini-2.5-flash
opencode -m openrouter/google/gemini-2.5-pro
```

Inside the TUI, use `/models` to switch providers or `/connect` to add credentials interactively.

## When To Use OpenCode

Use OpenCode when Codex is unavailable and the task needs an interactive coding agent rather than a one-shot report:

- inspect a staged integration plan
- make a small staging-only adapter change
- review a limited AgentOS UI or script helper change
- compare generated staging output against review notes
- produce a short follow-up patch in `staging/`, `apps/`, `scripts/`, `docs/`, or `memory/`

Do not use OpenCode for:

- live FiveM resource edits
- `qb-core` edits
- SQL execution or schema changes
- inventory core, money, permissions, or player-data changes without explicit human approval
- service restarts
- Git pushes
- broad repo refactors

## How It Differs From Gemini CLI

Gemini CLI is best treated as a Google-model command-line assistant. It is useful when the fallback should stay close to Gemini and produce plans or reports.

OpenCode is a multi-model coding agent. It can switch between Gemini, OpenRouter, and other API providers, load project instructions, manage model selection, and use coding tools. Because it can edit files, this repo config sets `edit` and `bash` permissions to `ask`.

Use `gemini-integration-check` for a bounded report from a folder summary. Use OpenCode only when an interactive fallback agent is needed and the work can stay inside safe repo paths.

## Fit In The Script Integration Pipeline

Normal path:

1. User uploads a FiveM script through AgentOS.
2. AgentOS saves it under `incoming/`.
3. Planner Agent identifies framework, dependencies, SQL, config, client, server, shared files, and risks.
4. Coding Agent creates staging-only adapted output under `staging/`.
5. Review Agent summarizes changes and blockers.
6. Human approves apply-to-server.
7. Server test runs after approval.
8. Git push happens only after review and test.

OpenCode fallback path:

1. Start OpenCode from `/home/agentzero/agents`.
2. Select an API model with `/models` or `-m`.
3. Ask it to work from the plan, staging folder, and memory rules.
4. Keep edits staging-only unless the user explicitly approves a safe repo file change.
5. Review `git diff` manually or with Codex before applying anything to the server.

Useful prompt:

```text
Review staging/<task-id> against memory/rules/fivem-rules.md and memory/playbooks/fivem-script-integration-checklist.md. Do not edit files. Report only SQL/config/dependency/live-resource risks and the next safe action.
```

Staging-only coding prompt:

```text
Make the smallest staging-only fix in staging/<task-id>. Do not touch live resources, qb-core, SQL, credentials, or services. Explain the diff and validation command.
```

## Validation

```bash
opencode --version
opencode --help
opencode providers list
```

These commands should work without local models. Model calls require the relevant API key.
