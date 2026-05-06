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
