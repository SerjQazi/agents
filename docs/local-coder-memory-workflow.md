# Local Coder Memory Workflow

Deprecated as the primary fallback. Codex remains the primary coding agent, Gemini is the preferred cloud fallback, and local Ollama is now emergency-only for tiny offline checks. The memory/playbook architecture stays useful: Codex-written playbooks, safety rules, and examples still define repeatable workflows for bounded report generation.

## Roles

- Codex writes and updates files in `memory/playbooks`, `memory/rules`, and `memory/examples`.
- Ollama executes narrow emergency review tasks using one playbook, one target file, and one task string.
- Runtime prompts load only the selected playbook, safety rules, local LLM limits, and the truncated target file. Examples stay in memory for future playbook updates.
- The local model never edits live files directly.
- The local model never pushes to Git.
- Generated output is saved as a report for manual or later Codex review.

## Script

These commands are retained for offline emergency use, but they are not the recommended fallback on this 4 vCPU / 8GB RAM CPU-only VM. Use the general task runner only when Codex and Gemini are unavailable and the task is small:

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

Use the FiveM integration checker for an incoming or staged resource folder:

```bash
coder-integration-check <folder>
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

`coder-integration-check` writes a report to:

```text
/home/agentzero/agents/reports/coder-integration-check-<timestamp>.md
```

It does not send every file to Ollama. It first builds a shell-only summary of file tree, manifests, SQL/config/client/server/shared files, and dependency keywords, then sends only that summary plus the integration playbook.

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
- Default integration-check output cap: `140` tokens
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

```bash
coder-integration-check incoming/some-resource
```

```bash
coder-integration-check staging/some-resource
```

## Operating Model

Keep local tasks small:

- Good: identify ESX references in one Lua file.
- Good: review one upload script for likely path or permission issues.
- Good: suggest a small UI patch for one component.
- Good: produce a short FiveM integration checklist from a folder summary.
- Good: run one local Ollama command at a time.
- Bad: refactor the repo.
- Bad: infer architecture across many files.
- Bad: edit, commit, push, or restart services.
- Bad: launch several Ollama coding tasks in parallel on this VM.
- Bad: point the local model at a live FiveM resource and ask it to edit files.

When a report looks useful, review it manually or ask Codex to inspect it before applying any change.

On this CPU-only VM, even small `qwen2.5-coder:3b` review prompts can take several minutes. Keep file windows and output caps low when using it interactively.

## Deprecated Local Fallback

These commands use the local Ollama API directly. They do not require Aider or Codex.

They are intentionally report-only and should not become the main autonomous path again. Prefer AgentOS plus Codex, then Gemini report generation, then local Ollama only as a last resort. Existing `reports/coder-*.md` files are historical diagnostics and can be kept for audit context or removed after review.
