# Default Code Review Playbook

Use this playbook for a short review of one file.

## Scope

- Review only the provided file contents.
- Report likely errors, bugs, unsafe behavior, and practical suggestions.
- Do not rewrite the file.
- Do not infer hidden repo architecture.
- Do not request broad refactors.
- Prefer concrete findings tied to visible code.

## Output Format

Return only:

1. Errors
2. Suggestions

If there are no clear errors, write `Errors: none found in provided file`.
Keep the report short.
