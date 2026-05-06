# Gemini Fallback Workflow

Codex is primary. Gemini is the secondary cloud fallback for bounded planning, compatibility checks, and report generation. Local Ollama remains emergency-only because this VM is CPU-only with 4 vCPU / 8GB RAM and small qwen prompts can still be slow.

## Operating Rules

- Use Codex for implementation, repo-wide analysis, test repair, and AgentOS pipeline changes.
- Use Gemini only for narrow reports from bounded summaries.
- Use local Ollama only when both Codex and Gemini are unavailable and the task is tiny.
- Never commit API keys, `.env` files, tokens, credentials, or generated secrets.
- Load `GEMINI_API_KEY` from the environment only.
- Do not pass full repositories or live server resources to Gemini.
- Do not use Gemini for direct live server edits.
- Do not let Gemini run SQL, push Git, restart services, or modify FiveM resources.

## Gemini Integration Check

Use the report-only checker for incoming or staged FiveM scripts:

```bash
export GEMINI_API_KEY="your-api-key"
gemini-integration-check incoming/<resource-folder>
gemini-integration-check staging/<task-id>
```

The checker:

- summarizes the folder with shell tools first
- sends only the bounded summary plus memory playbooks and safety rules to Gemini
- writes a report to `reports/gemini-integration-check-<timestamp>.md`
- never edits files
- never pushes Git
- refuses folders outside `/home/agentzero/agents`

The default model is `gemini-2.5-flash`. Override only when needed:

```bash
GEMINI_MODEL=gemini-2.5-flash gemini-integration-check incoming/<resource-folder>
```

## API Key Setup

Create a Gemini API key in Google AI Studio, then set it in the shell environment:

```bash
export GEMINI_API_KEY="your-api-key"
```

Do not store the key in the repo. If a service wrapper is added later, load the key from a protected systemd environment file outside Git.

## Official Client Guidance

The current lightweight path uses the Gemini REST `generateContent` API directly and does not install packages.

Official references:

- Gemini API reference: `https://ai.google.dev/docs/gemini_api_overview/`
- Gemini API quickstart: `https://ai.google.dev/gemini-api/docs/quickstart`
- API key setup: `https://ai.google.dev/gemini-api/docs/api-key`
- Official Gemini CLI repository: `https://github.com/google-gemini/gemini-cli`
- Official Gemini CLI docs: `https://google-gemini.github.io/gemini-cli/docs/get-started/`

If a CLI is needed later, use only Google's official Gemini CLI sources, such as the `@google/gemini-cli` package or the official `google-gemini/gemini-cli` repository. Avoid typosquatted packages, unofficial installer commands, and copied setup snippets from random sites.

## Cleanup Recommendations

These are optional cleanup commands. Do not run them unless the local fallback is confirmed unused and no other service depends on them.

```bash
ollama rm qwen2.5-coder:3b
ollama rm qwen2.5-coder:7b
```

If Aider was installed in a dedicated virtual environment and is no longer needed:

```bash
rm -rf /home/agentzero/aider-venv
```

Do not remove:

- `apps/agentos_agent/`
- `apps/planner_agent/`
- `apps/coding_agent/`
- `apps/shared_layout.py`
- `incoming/`
- `staging/`
- `reports/`
- `memory/playbooks/`
- `memory/rules/`
- `memory/examples/`
- `scripts/git_helper.sh`
- `scripts/push-to-git.sh`
- `scripts/push-to-server.sh`
- AgentOS service files or server tooling

## Test Commands

After `GEMINI_API_KEY` is set:

```bash
gemini-integration-check incoming/test-script
```

```bash
gemini-integration-check staging/<task-id>
```

For syntax-only validation:

```bash
bash -n /home/agentzero/scripts/gemini-integration-check
```

## OpenCode + OpenRouter for Night-Shift / Specialized Tasks

For situations requiring direct interaction with specialized models or when Codex is unavailable, the AgentOS environment provides OpenCode launchers for various OpenRouter models. These are intended for "night-shift" coding or tasks where a particular model's strengths (e.g., fast generation, large context, dedicated coding) are beneficial.

**Available OpenCode Launchers (symlinked to `~/.local/bin/`):**

*   `opencode-models`: Lists recommended models and their use cases.
*   `opencode-sonnet`: Launches with `openrouter/anthropic/claude-sonnet-4.5`.
*   `opencode-claude`: Launches with `openrouter/anthropic/claude-3.7-sonnet`.
*   `opencode-haiku`: Launches with `openrouter/anthropic/claude-3.5-haiku`.
*   `opencode-gemini-pro`: Launches with `openrouter/google/gemini-2.5-pro`.
*   `opencode-gemini`: Launches with `openrouter/google/gemini-2.5-flash`.

**When to Use:** Refer to `docs/opencode-model-launchers.md` for a detailed guide on model selection, use cases, and important safety considerations. These launchers should always be used with the explicit safety reminder: "Work inside `/home/agentzero/agents`. Do not touch live FiveM resources unless explicitly approved."

---

## Agent Roles and AI Memory System

AgentOS leverages a tiered system of AI agents and a shared memory system to optimize development workflows.

**AI Agent Roles:**

*   **Codex (Primary)**: The primary agent for heavy implementation, complex problem-solving, repo-wide analysis, feature development, and test repair.
*   **Gemini CLI (Secondary Fallback)**: Cloud-based agent for bounded planning, compatibility checks, report generation, and UI/UX polish.
*   **OpenCode + OpenRouter (Night-Shift / Specialized Fallback)**: Provides direct access to specialized models for focused code generation, quick experiments, and tackling bounded coding problems when other agents are not efficient or available.
*   **Local Ollama (Emergency-Only)**: Only to be used as a last resort when all other cloud-based models are unavailable for extremely small, critical tasks. Performance is severely degraded due to CPU-only VM resources.

**AI Memory System:**

All AI-assisted work should leave useful records for future learning.

*   **Agent Documentation (`memory/ai-agents/*.md`)**: Defines the role, strengths, weaknesses, and best/avoid tasks for each major AI agent (Codex, Gemini, OpenCode).
*   **Model Routing (`memory/ai-agents/model-routing.md`)**: Provides guidelines for selecting the appropriate AI model or agent based on the task.
*   **Lessons Learned (`memory/ai-agents/lessons-learned.md`)**: A centralized log for key insights, successful patterns, unexpected failures, and model limitations.
*   **Specialized Lessons (`memory/lessons/*.md`)**: Specific markdown files for detailed lessons on particular task categories (e.g., inventory migration, UI dashboard development).

**Recording Lessons Learned:**

*   **`agent-memory-log "<title>" "<lesson>"`**: Use this script to append a timestamped lesson to `memory/ai-agents/lessons-learned.md`.
*   **`agent-session-summary <provider> <summary-file>`**: Use this script to copy a detailed summary file into `reports/session-checkpoints/` and add an index entry to `memory/ai-agents/lessons-learned.md`.

By leveraging this memory system, AgentOS aims to continuously improve its performance and adapt to new challenges based on collective experience.

