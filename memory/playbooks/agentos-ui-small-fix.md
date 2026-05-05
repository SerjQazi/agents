# AgentOS UI Small Fix Playbook

Use this playbook for narrow frontend fixes in a single UI file.

## Scope

- Inspect only the provided file.
- Suggest a small, localized change.
- Do not redesign the whole page.
- Do not add new dependencies unless the task explicitly asks for one.
- Do not invent backend APIs.
- Preserve existing component patterns, naming, and styling conventions.

## UI Rules

- Keep controls stable in size so hover, loading, or dynamic text does not shift layout.
- Avoid text overlap on mobile and desktop.
- Use existing icons/components if they are already imported or clearly available.
- Keep operational dashboards dense, calm, and scannable.
- Do not add marketing-style hero sections for tools or dashboards.
- Do not place cards inside cards.
- Prefer direct fixes to spacing, state handling, accessibility labels, disabled states, and responsive constraints.

## Output Format

Return:

1. UI issue identified.
2. Minimal change recommended.
3. Patch-style snippet or exact replacement block.
4. Verification checklist for desktop and mobile.

Keep the patch suggestion small enough for manual review.
