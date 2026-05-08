# AI Prompt Handoff Workflow

This folder is the file-based handoff point for the AgentOS AI development cycle.

## Standard cycle

1. Gemini plans architecture.
2. Save Gemini's full plan to `gemini-plan-latest.md`.
3. Save Gemini's OpenCode implementation prompt to `opencode-next.md`.
4. Save Gemini's Codex stabilization prompt to `codex-audit-next.md`.
5. OpenCode implements from `opencode-next.md`.
6. Codex audits from `codex-audit-next.md`.
7. Archive old prompts after each cycle.

## Files

- `gemini-plan-latest.md`: latest full Gemini plan.
- `opencode-next.md`: latest implementation prompt for OpenCode.
- `codex-audit-next.md`: latest stabilization/audit prompt for Codex.
- `archive/`: timestamped snapshots of prior prompt files.

## Helper script

Use `scripts/save-ai-cycle-prompts.sh` to archive prior prompt files and load new ones.
