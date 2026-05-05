# Staging Review Example

## Input Task

Review a staging report for whether it is safe to apply.

## Good Output Shape

Summary:
The staged change is small and limited to one client event handler. It does not modify core framework files or database behavior.

Safe indicators:

- Only files inside the incoming resource are mentioned.
- No `.env`, token, or credential content appears.
- No Git push or service restart is requested.
- The change includes a manual verification step.

Needs review:

- Any money, inventory, permissions, or player data changes.
- Missing backup path.
- Patch touching shared framework resources.

Recommendation:
Have Codex inspect the exact patch before applying it. If approved, back up the resource first and apply only the reviewed file changes.
