# AI Fallback Routing

`ai-task` is the single command for bounded fallback AI work from `/home/agentzero/agents`.

```bash
ai-task "Review staging/coding-123 and list SQL/config/live-resource risks only."
```

The installed command is `/home/agentzero/scripts/ai-task`, with a convenience symlink at `/home/agentzero/.local/bin/ai-task`.

The command writes a report to:

```text
reports/ai-task-<timestamp>.md
```

It also prints the provider that returned usable output.

## Fallback Order

Default mode is `auto`:

1. Codex via `codex exec`
2. Gemini CLI via `gemini --prompt`
3. OpenCode via `opencode run`

A provider is considered failed if:

- its command is missing
- it exits non-zero
- it times out
- it returns empty output

Each provider gets a small timeout. The default is `120` seconds:

```bash
AI_TASK_TIMEOUT_SECONDS=90 ai-task "Summarize this staged review."
```

The wrapper does not load the full repo into the prompt. It sends the instruction plus safety constraints and relies on the selected provider's own repo access rules.

## Safety Rules

Every routed prompt includes these constraints:

- work only inside `/home/agentzero/agents`
- do not modify live FiveM resources
- do not touch `qb-core`
- do not run SQL
- do not push Git
- do not restart services
- keep output bounded
- avoid full-repo scanning unless explicitly required

Codex runs with a read-only sandbox. Gemini runs in plan approval mode. OpenCode uses the project `script-integration-reviewer` agent by default.

## Force A Provider

Use a flag:

```bash
ai-task --provider codex "Explain the current staging review."
ai-task --provider gemini "Create a short integration checklist."
ai-task --provider opencode "Review docs for fallback workflow gaps."
```

Or use an environment variable:

```bash
AI_TASK_PROVIDER=gemini ai-task "Summarize reports/reviews."
```

Valid providers:

- `auto`
- `codex`
- `gemini`
- `opencode`

## Model Overrides

Gemini CLI:

```bash
AI_TASK_GEMINI_MODEL=gemini-2.5-flash ai-task --provider gemini "Report only."
```

OpenCode:

```bash
AI_TASK_OPENCODE_MODEL=gemini/gemini-2.5-flash ai-task --provider opencode "Report only."
AI_TASK_OPENCODE_MODEL=openrouter/google/gemini-2.5-pro ai-task --provider opencode "Report only."
```

## Debug Failures

Check whether the commands exist:

```bash
command -v codex
command -v gemini
command -v opencode
```

Check auth/provider state:

```bash
codex --version
gemini --version
opencode providers list
opencode models gemini
opencode models openrouter
```

Inspect the generated report. It records:

- requested mode
- provider used
- timeout
- attempt status for each provider
- whether output or stderr was present
- final output or last stderr if all providers failed

If Gemini or OpenCode fails, confirm API keys are available in the shell:

```bash
export GEMINI_API_KEY="..."
export OPENROUTER_API_KEY="..."
```

Do not commit API keys, `.env` files, tokens, or credentials.
