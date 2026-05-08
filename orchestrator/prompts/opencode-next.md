# OpenCode Implementation Prompt

Resource: qb-inventory-new
Generated At (UTC): 2026-05-08T01:21:33Z
Source Patch Plan: orchestrator/archive/qb-inventory-new/patch-plan.json

Implement the patch plan for this FiveM resource with strict safety controls.

Safety constraints (mandatory):
- Staging-only modifications; do not modify live FiveM server files.
- Create backups before editing any script files.
- Use AGENT FIX START and AGENT FIX END markers around major generated changes.
- Run syntax validation checks for touched files before completing.
- Provide a changed-files summary with brief rationale for each change.
- Do NOT run git push.
- Do NOT run txAdmin restart.
- Do NOT perform live server edits.

Detected risks from patch plan:
- High risk findings: []
- Medium risk findings: []

Migration targets:
[
  {
    "type": "database",
    "from": "mysql-async",
    "to": "oxmysql",
    "recommendation": "Migrate from mysql-async to oxmysql. Update MySQL.query calls and remove mysql-async dependency.",
    "risk_assessment": "medium",
    "estimated_effort": "low",
    "files_likely_requiring_edits": []
  },
  {
    "type": "target_system",
    "from": "qb-target",
    "to": "qb-target",
    "recommendation": "Consider migrating from qb-target to qb-target if target system compatibility needed.",
    "risk_assessment": "medium",
    "estimated_effort": "medium",
    "files_likely_requiring_edits": []
  },
  {
    "type": "legacy_qbcore_exports",
    "from": "legacy_qbcore_exports",
    "to": "qbus_qbcore_exports",
    "recommendation": "Legacy QBCore export detected. Update to use qbus-core exports for compatibility with QBox or newer QBCore versions.",
    "risk_assessment": "medium",
    "estimated_effort": "low",
    "files_likely_requiring_edits": []
  },
  {
    "type": "legacy_qbcore_exports",
    "from": "legacy_qbcore_exports",
    "to": "qbus_qbcore_exports",
    "recommendation": "Legacy QBCore export detected. Update to use qbus-core exports for compatibility with QBox or newer QBCore versions.",
    "risk_assessment": "medium",
    "estimated_effort": "low",
    "files_likely_requiring_edits": []
  },
  {
    "type": "deprecated_event",
    "from": "RegisterNetEvent",
    "to": "proper_event_handler",
    "recommendation": "RegisterNetEvent is deprecated. use RegisterNetEvent instead.",
    "risk_assessment": "low",
    "estimated_effort": "low",
    "files_likely_requiring_edits": []
  },
  {
    "type": "deprecated_event",
    "from": "RegisterServerEvent",
    "to": "proper_event_handler",
    "recommendation": "RegisterServerEvent is deprecated. use RegisterNetEvent.",
    "risk_assessment": "low",
    "estimated_effort": "low",
    "files_likely_requiring_edits": []
  },
  {
    "type": "sql_review_required",
    "from": "sql_statements",
    "to": "migration_needed",
    "recommendation": "SQL statements detected. Review for compatibility with oxmysql and ensure proper table prefix handling.",
    "risk_assessment": "medium",
    "estimated_effort": "medium",
    "files_likely_requiring_edits": [
      "HPX-inventory.sql"
    ]
  },
  {
    "type": "dependency_conflict",
    "from": "QBCore, mysql-async, qb-target",
    "to": "resolve_conflicts",
    "recommendation": "Multiple dependencies detected. Verify compatibility between frameworks and resolve any conflicts.",
    "risk_assessment": "medium",
    "estimated_effort": "medium",
    "files_likely_requiring_edits": []
  },
  {
    "type": "weapon_inventory_integration_risk",
    "from": "weapon_inventory_integration",
    "to": "verify_compatibility",
    "recommendation": "Weapon and inventory integration detected. Verify qb-weapons compatibility with qb-inventory or ox_inventory.",
    "risk_assessment": "medium",
    "estimated_effort": "medium",
    "files_likely_requiring_edits": []
  }
]

Execution scope:
- Follow patch-plan phases and proposed edits only.
- If a step is ambiguous, stop and report assumptions before applying changes.

Patch-plan phases:
[]
