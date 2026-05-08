# Codex Stabilization Audit Prompt

Resource: qb-inventory-new
Generated At (UTC): 2026-05-08T01:21:33Z
Source Patch Plan: orchestrator/archive/qb-inventory-new/patch-plan.json

Audit OpenCode implementation results against the patch plan.

Audit requirements (mandatory):
- Verify AGENT FIX START / AGENT FIX END markers exist around major generated edits.
- Verify no live server modifications were made.
- Verify no txAdmin restart, apply, or staging automation was triggered.
- Verify syntax checks passed for changed files.
- Verify changed-files summary is present and accurate.
- Verify implementation remains compliant with patch-plan scope.

Security checks:
- Confirm no path traversal or unsafe file writes were introduced.
- Confirm no secrets, env files, caches, backups, or runtime artifacts were committed.

Deliverable:
- List findings by severity (critical/high/medium/low).
- Include precise file references and minimal remediation actions.
- Mark whether patch-plan compliance is PASS or FAIL with reasons.

Patch-plan metadata:
{}
