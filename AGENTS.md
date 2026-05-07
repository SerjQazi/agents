# Agent Workflow Notes

## Git Helpers

- Philosophy: `status -> validate -> summarize -> stage -> commit -> approval -> push`.
- Never push automatically. Never auto-force-push.
- Always show a changed-file summary before staging/committing/pushing.
- Never commit/push secrets, `.env` files, tokens, credentials, or virtualenv folders.

Standard command vocabulary:
- If the user says "repo status", run `./scripts/git_helper.sh repo-status`.
- If the user says "commit backend", run `./scripts/git_helper.sh commit-backend` (runs orchestrator validation first, stages backend/orchestrator only, commits locally, no push).
- If the user says "commit safe", run `./scripts/git_helper.sh commit-safe` (inspects and stages safely, commits locally, no push).
- If the user says "push approved", run `./scripts/git_helper.sh push-approved` (shows latest commit + branch/remote + secret checks, asks final confirmation, then pushes).
- If the user says "rollback last", run `./scripts/git_helper.sh rollback-last` (explains safe rollback options; never auto-force-reset).
- If the user says "release milestone", run `./scripts/git_helper.sh release-milestone` (verifies orchestrator integrity, prepares milestone commit, waits for approval before push).

Legacy compatibility:
- If the user says "push to git", do NOT push automatically. Prefer:
  1) `./scripts/git_helper.sh commit-safe` (or `commit-backend`)
  2) After explicit approval, `./scripts/git_helper.sh push-approved`
- If the user says "make new branch <name>", run `./scripts/git_helper.sh branch <name>`.
- If the user asks current repo state, run `./scripts/git_helper.sh status` (or `repo-status` if they want the full report).
- Do not modify `bubbles.py` or `mailman.py` unless explicitly asked.

## FiveM/QBCore Integration Safety

- Never edit `qb-core` directly.
- Do not modify live FiveM resources unless the user explicitly approves it.
- Prefer compatibility adapters inside incoming script folders over core framework edits.
- Incoming third-party scripts belong in `~/agents/incoming`.
- Compatibility reports belong in `~/agents/reports`.
- Backups belong in `~/agents/backups`.
- Backup files before modifying any script resource.
- Use `AGENT FIX START` and `AGENT FIX END` markers around major generated changes.
- Stop and ask before database schema, inventory core, money, permissions, or player data changes.
- Profile and report compatibility first; do not auto-fix incoming scripts unless explicitly requested.
