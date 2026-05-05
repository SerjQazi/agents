# Aider Advanced Fallback Workflow

Codex remains the primary coding agent. Use Aider only when Codex is unavailable and the task can be constrained to a small, obvious patch.

## When to Use Codex vs Aider

Use Codex for broad repo analysis, architecture changes, cross-module refactors, database schema work, inventory core changes, money, permissions, player data, and anything involving live FiveM resources.

Use Aider for small fallback edits in safe areas:

- `staging/**`
- `apps/*/**`
- `scripts/**`

Do not use Aider to edit `qb-core`, `incoming`, `backups`, `reports`, root-level framework copies, core server files, `.env` files, tokens, credentials, or live FiveM resources.

## Safe Launch Commands

Interactive scoped session:

```bash
/home/agentzero/scripts/aider-agent
```

Target a specific staging file:

```bash
/home/agentzero/scripts/aider-agent --scope staging/coding-123 client.lua
```

Target an app subtree:

```bash
/home/agentzero/scripts/aider-agent --scope apps/coding_agent app.py storage.py
```

Run a one-shot natural language task:

```bash
/home/agentzero/scripts/aider-task --scope staging/coding-123 --file client.lua -- "Fix the Lua syntax error only"
```

The one-shot task runner logs requests and output to:

```text
/home/agentzero/logs/aider-tasks.log
```

## Timeout Avoidance

This server is CPU-only with about 8GB RAM. Keep Aider away from full-repo scans.

Recommended defaults used by the wrappers:

```bash
--subtree-only
--aiderignore /home/agentzero/agents/.aiderignore
--map-tokens 512
--map-refresh manual
--map-multiplier-no-files 1
--max-chat-history-tokens 2048
--timeout 120
--no-auto-commits
--no-auto-lint
--no-auto-test
--no-suggest-shell-commands
--no-detect-urls
```

For weaker CPU-only runs, make the scope smaller before raising limits:

```bash
AIDER_MAP_TOKENS=256 AIDER_TIMEOUT=90 /home/agentzero/scripts/aider-agent --scope staging/coding-123 client.lua
```

Avoid asking Aider to "scan the repo", "find all usages", or "refactor the app". Give it exact files and a concrete instruction.

## Safely Applying Changes

1. Keep edits in `staging`, `apps/*`, or `scripts/*`.
2. Review the diff:

```bash
git diff --stat
git diff
```

3. Run focused checks only. Do not restart services from Aider.
4. Commit Aider work separately from Codex work:

```bash
/home/agentzero/scripts/aider-push --no-push --tag
```

The commit message is always prefixed with `AIDER:` and can append `[fallback-agent]`.

## Guardrails

The repo has a deny-by-default `.aiderignore`. It allows only:

- `staging/**`
- `apps/*/**`
- `scripts/**`

The wrapper scripts also validate scopes before launching Aider. These safeguards are there to keep fallback edits separate from live FiveM resources and core framework files.
