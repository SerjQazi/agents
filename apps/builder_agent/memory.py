"""Default memory notes and retrieval helpers."""

from __future__ import annotations

from .config import BuilderConfig
from .storage import Storage


DEFAULT_RULES = {
    "never_modify_qb_core_without_approval": "Do not modify qb-core unless the user explicitly approves it.",
    "prefer_backups_first": "Create backups before any approved apply operation.",
    "agent_fix_markers": "Use AGENT FIX START and AGENT FIX END comments around major generated changes.",
    "never_run_sql": "Never run SQL automatically; report SQL files and require explicit approval.",
    "never_restart_fivem": "Never restart FiveM automatically.",
    "never_push_git": "Never push to Git automatically unless explicitly asked.",
    "default_plan_only": "Default to plan-only/read-only behavior.",
}

DEFAULT_MAPPINGS = {
    "ESX_to_QBCore": "Map ESX player and framework access to QBCore APIs inside the script, not qb-core.",
    "mysql_async_to_oxmysql": "Replace mysql-async patterns with oxmysql only after reviewing query behavior.",
    "ox_target_to_qb_target": "Map ox_target registrations to qb-target equivalents when server uses qb-target.",
    "ox_inventory_to_qb_inventory": "Map inventory item checks and mutations to QBCore/qb-inventory patterns.",
}


def seed_default_memory(storage: Storage, config: BuilderConfig) -> None:
    for key, value in DEFAULT_RULES.items():
        storage.upsert_memory_note("rule", key, value, "builder-agent-default")

    for key, value in DEFAULT_MAPPINGS.items():
        storage.upsert_memory_note("mapping", key, value, "builder-agent-default")

    storage.upsert_memory_note("path", "agents_repo", str(config.agents_root), "builder-agent-default")
    storage.upsert_memory_note("path", "incoming_scripts", str(config.incoming_dir), "builder-agent-default")
    storage.upsert_memory_note("path", "server_resources", str(config.server_resources), "builder-agent-default")
    storage.upsert_memory_note("path", "reports", str(config.reports_dir), "builder-agent-default")

