# Agent Workflow Notes

## Git Helpers

- If the user says "push to git", run `./scripts/git_helper.sh push` with a short meaningful commit message.
- If the user says "make new branch <name>", run `./scripts/git_helper.sh branch <name>`.
- If the user asks current repo state, run `./scripts/git_helper.sh status`.
- Before pushing, briefly summarize changed files.
- Never push secrets, `.env` files, tokens, credentials, or virtualenv folders.
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
