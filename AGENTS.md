# Agent Workflow Notes

## Git Helpers

- If the user says "push to git", run `./scripts/git_helper.sh push` with a short meaningful commit message.
- If the user says "make new branch <name>", run `./scripts/git_helper.sh branch <name>`.
- If the user asks current repo state, run `./scripts/git_helper.sh status`.
- Before pushing, briefly summarize changed files.
- Never push secrets, `.env` files, tokens, credentials, or virtualenv folders.
- Do not modify `bubbles.py` or `mailman.py` unless explicitly asked.
