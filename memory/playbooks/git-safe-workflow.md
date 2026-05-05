# Git Safe Workflow Playbook

Use this playbook for narrow review of Git helper scripts, repo state summaries, or workflow instructions.

## Scope

- Never push to Git.
- Never create commits.
- Never stage files.
- Never reset, checkout, clean, or delete files.
- Produce advice or a report only.
- Respect user changes in the working tree.

## Safety Rules

- Summarize changed files before any future push.
- Do not include secrets, `.env` files, tokens, credentials, generated caches, or virtualenv folders.
- Prefer repo helper scripts when the workflow instructions require them.
- Treat untracked files as user work unless explicitly told otherwise.
- Flag commands that can rewrite history or destroy local changes.

## Output Format

Return:

1. Current workflow interpretation.
2. Safe commands to inspect state.
3. Commands that must not be run automatically.
4. Suggested next human-reviewed step.

If asked for a commit message, suggest one short message but do not commit.
