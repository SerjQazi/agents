# FiveM Rules

- Never edit `qb-core` directly.
- Do not modify live FiveM resources unless explicitly approved.
- Prefer compatibility adapters inside incoming script folders over core framework edits.
- Incoming third-party scripts belong in `~/agents/incoming`.
- Compatibility reports belong in `~/agents/reports`.
- Backups belong in `~/agents/backups`.
- Backup files before modifying any script resource.
- Use `AGENT FIX START` and `AGENT FIX END` markers around major generated changes when Codex later applies edits.
- Stop and ask before database schema, inventory core, money, permissions, or player data changes.
- Profile and report compatibility first; do not auto-fix incoming scripts unless explicitly requested.
