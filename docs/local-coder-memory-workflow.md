# Local Coder Memory Workflow

Codex is the primary coding agent. Local Ollama is a fallback path for small, narrow tasks when Codex is offline or unavailable. The fallback works by injecting Codex-written playbooks, safety rules, and examples into a bounded prompt.

## Roles

- Codex writes and updates files in `memory/playbooks`, `memory/rules`, and `memory/examples`.
- Ollama executes narrow review tasks using one playbook, one target file, and one task string.
- Runtime prompts load only the selected playbook, safety rules, local LLM limits, and the truncated target file. Examples stay in memory for future playbook updates.
- The local model never edits live files directly.
- The local model never pushes to Git.
- Generated output is saved as a report for manual or later Codex review.

## Script

Use the general task runner when you want a named playbook:

```bash
/home/agentzero/scripts/coder-task <playbook-name> <file-path> "<task>"
```

The same commands are symlinked into `/home/agentzero/.local/bin`, so they can be run directly when that directory is on `PATH`:

```bash
coder-task <playbook-name> <file-path> "<task>"
```

Use the simple review command for a short errors-and-suggestions report:

```bash
coder-review <file>
```

Use the simple fix command for patch-style suggestions:

```bash
coder-fix <file>
```

The script defaults to `qwen2.5-coder:3b`. Override it only when needed:

```bash
OLLAMA_MODEL=qwen2.5-coder:3b /home/agentzero/scripts/coder-task git-safe-workflow scripts/git_helper.sh "Review this helper for safe push workflow risks."
```

Reports are written to:

```text
/home/agentzero/agents/reports/coder-task-<timestamp>.md
```

`coder-review` and `coder-fix` print their reports to the terminal. They do not edit files.

## Safe Mode

The offline wrappers call Ollama's local generate API directly and are bounded for the 4 vCPU / 8GB RAM CPU-only VM:

- Default model: `qwen2.5-coder:3b`
- Default review/fix file limit: first `2000` bytes
- Default task file limit: first `3000` bytes
- Default review/fix timeout: `240` seconds
- Default task timeout: `240` seconds
- Default review output cap: `60` tokens
- Default fix output cap: `90` tokens
- Default task output cap: `60` tokens
- Default context cap: `1024` tokens

Override only when needed:

```bash
CODER_MAX_FILE_BYTES=1200 CODER_TIMEOUT_SECONDS=180 CODER_NUM_PREDICT=40 CODER_NUM_CTX=1024 /home/agentzero/scripts/coder-review scripts/git_helper.sh
```

## Quick Test

```bash
/home/agentzero/scripts/coder-task git-safe-workflow scripts/git_helper.sh "Summarize what this script does and identify any safety risks. Do not suggest running push."
```

```bash
coder-review scripts/git_helper.sh
```

```bash
coder-fix scripts/git_helper.sh
```

## Operating Model

Keep local tasks small:

- Good: identify ESX references in one Lua file.
- Good: review one upload script for likely path or permission issues.
- Good: suggest a small UI patch for one component.
- Good: run one local Ollama command at a time.
- Bad: refactor the repo.
- Bad: infer architecture across many files.
- Bad: edit, commit, push, or restart services.
- Bad: launch several Ollama coding tasks in parallel on this VM.

When a report looks useful, review it manually or ask Codex to inspect it before applying any change.

On this CPU-only VM, even small `qwen2.5-coder:3b` review prompts can take several minutes. Keep file windows and output caps low when using it interactively.

## Offline Requirement

These commands use the local Ollama API directly. They do not require Aider or Codex.
