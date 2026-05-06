# Autonomous Script Integration Roadmap

AgentOS is the control center for FiveM script intake, staging, review, and approval. Codex remains the primary implementation agent. Gemini is the cloud fallback for bounded planning and report generation when Codex is unavailable.

## Target Workflow

1. User opens AgentOS at `http://100.68.10.125:8080/`.
2. User drag-and-drops a FiveM script zip or folder into the Upload Pipeline.
3. AgentOS saves the upload under `incoming/` and records the task state.
4. AgentOS shows processing status in the UI: uploaded, planning, coding, review, complete, or blocked.
5. Planner Agent inspects the script summary:
   - framework signals: ESX, QBCore, Qbox, standalone
   - dependencies: `ox_lib`, `ox_inventory`, `qb-inventory`, `qb-target`, `ox_target`, `mysql-async`, `oxmysql`
   - SQL files
   - config files
   - client, server, and shared files
   - risky edits that need human approval
6. Coding Agent creates staging-only adapted output under `staging/`.
7. Review Agent summarizes changes, compatibility risks, manual steps, and test notes.
8. AgentOS shows completion status and the next action:
   - View Plan
   - View Staging
   - View Review
   - Open Daily Coding Digest
9. Human reviews the staging output and approves any apply-to-server action.
10. Server test step runs only after human approval.
11. Git push happens only after review, test, and a clear commit message.

## Safety Gates

- Never modify live FiveM resources during upload, planning, coding, or review.
- Never edit `qb-core` directly.
- Never run SQL automatically.
- Never apply inventory, money, permissions, or player-data changes without explicit human approval.
- Keep third-party incoming scripts under `incoming/`.
- Keep generated adapted output under `staging/`.
- Keep reports under `reports/`.
- Back up any script resource before a human-approved apply step.
- Keep task IDs visible for traceability, but show human-readable status first.

## Agent Responsibilities

Codex:

- Owns repo-level changes, pipeline code, tests, and playbook updates.
- Reviews generated plans and staging output before any risky operation.
- Writes or updates memory playbooks when a workflow becomes repeatable.

Gemini fallback:

- Produces bounded planning and report output from folder summaries.
- Uses memory playbooks and safety rules as prompt context.
- Does not edit files, push Git, restart services, run SQL, or touch live FiveM resources.

Local Ollama emergency path:

- Retained for offline, very small review tasks only.
- Not the preferred fallback on this 4 vCPU / 8GB RAM CPU-only VM.

## Implementation Priorities

1. Keep AgentOS navigation and upload pipeline stable.
2. Improve upload progress visibility and blocked-state messaging.
3. Make Planner reports easy to scan from the UI.
4. Make Coding Agent staging output easy to inspect before apply.
5. Add Review Agent summaries that call out SQL, dependency, and live-resource risks.
6. Add a human approval gate before apply-to-server.
7. Add a post-apply server test step.
8. Push to Git only after successful review and test, with a clear commit message.
