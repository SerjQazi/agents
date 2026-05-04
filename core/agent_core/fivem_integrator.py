#!/usr/bin/env python3
"""Create read-only FiveM script integration compatibility reports."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path


DEFAULT_SERVER = Path("~/fivem-server/txData/QBCore_F16AC8.base").expanduser()
DEFAULT_OUT = Path("~/agents/reports").expanduser()

KEY_RESOURCES = [
    "qb-core",
    "qb-inventory",
    "qb-target",
    "qb-menu",
    "qb-input",
    "oxmysql",
    "ox_lib",
    "illenium-appearance",
    "pma-voice",
]

MARKERS = {
    "framework": {
        "QBCore": ["qb-core", "QBCore", "GetCoreObject", "exports['qb-core']"],
        "ESX": ["es_extended", "ESX.GetPlayerFromId", "getSharedObject"],
        "Qbox": ["qbx_core", "exports.qbx_core", "exports['qbx_core']"],
    },
    "inventory": {
        "qb-inventory": ["qb-inventory", "GetItemByName", "Player.Functions.AddItem"],
        "ox_inventory": ["ox_inventory", "exports.ox_inventory", "exports['ox_inventory']"],
        "ps-inventory": ["ps-inventory", "exports['ps-inventory']"],
    },
    "target": {
        "qb-target": ["qb-target", "exports['qb-target']", "AddTargetEntity"],
        "ox_target": ["ox_target", "exports.ox_target", "exports['ox_target']"],
    },
    "database": {
        "oxmysql": ["oxmysql", "MySQL.query", "MySQL.insert", "MySQL.update", "MySQL.scalar"],
        "mysql-async": ["mysql-async", "MySQL.Async"],
        "ghmattimysql": ["ghmattimysql", "exports.ghmattimysql"],
    },
}

TEXT_EXTS = {
    ".lua",
    ".js",
    ".json",
    ".cfg",
    ".sql",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".xml",
    ".yml",
    ".yaml",
}


def has_manifest(path: Path) -> bool:
    return (path / "fxmanifest.lua").is_file() or (path / "__resource.lua").is_file()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def scan_script(script_path: Path) -> dict:
    files = []
    text_parts = []

    for file_path in sorted(script_path.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(script_path)
        files.append(str(relative))
        if file_path.suffix.lower() in TEXT_EXTS or file_path.name in {
            "fxmanifest.lua",
            "__resource.lua",
        }:
            text_parts.append(read_text(file_path))

    combined = "\n".join(text_parts)
    assumptions = {}
    evidence = {}

    for category, options in MARKERS.items():
        assumptions[category] = []
        evidence[category] = {}
        for name, markers in options.items():
            hits = sorted({marker for marker in markers if marker in combined})
            if hits:
                assumptions[category].append(name)
                evidence[category][name] = hits

    return {
        "files": files,
        "assumptions": assumptions,
        "evidence": evidence,
        "has_manifest": has_manifest(script_path),
    }


def scan_server_resources(server_path: Path) -> set[str]:
    resources_path = server_path / "resources"
    if not resources_path.exists():
        raise FileNotFoundError(f"Resources folder not found: {resources_path}")

    names = set()
    for path in resources_path.rglob("*"):
        if path.is_dir() and has_manifest(path):
            names.add(path.name)
    return names


def compare_assumptions(assumptions: dict[str, list[str]], resources: set[str]) -> list[str]:
    risks = []

    if "ESX" in assumptions["framework"]:
        risks.append("Script appears ESX-based and needs QBCore compatibility work.")
    if "Qbox" in assumptions["framework"] and "qb-core" in resources:
        risks.append("Script references Qbox while the server profile is QBCore.")
    if "QBCore" in assumptions["framework"] and "qb-core" not in resources:
        risks.append("Script expects QBCore, but qb-core was not found in server resources.")

    if "ox_inventory" in assumptions["inventory"] and "ox_inventory" not in resources:
        risks.append("Script expects ox_inventory, but this server uses qb-inventory.")
    if "ps-inventory" in assumptions["inventory"] and "ps-inventory" not in resources:
        risks.append("Script expects ps-inventory, but ps-inventory was not found.")
    if "qb-inventory" in assumptions["inventory"] and "qb-inventory" not in resources:
        risks.append("Script expects qb-inventory, but qb-inventory was not found.")

    if "ox_target" in assumptions["target"] and "ox_target" not in resources:
        risks.append("Script expects ox_target, but this server uses qb-target.")
    if "qb-target" in assumptions["target"] and "qb-target" not in resources:
        risks.append("Script expects qb-target, but qb-target was not found.")

    if "mysql-async" in assumptions["database"] and "oxmysql" in resources:
        risks.append("Script uses mysql-async patterns and should be adapted to oxmysql.")
    if "ghmattimysql" in assumptions["database"] and "oxmysql" in resources:
        risks.append("Script uses ghmattimysql patterns and should be adapted to oxmysql.")
    if "oxmysql" in assumptions["database"] and "oxmysql" not in resources:
        risks.append("Script expects oxmysql, but oxmysql was not found.")

    return risks


def adaptation_plan(assumptions: dict[str, list[str]], resources: set[str], risks: list[str]) -> list[str]:
    plan = [
        "Keep the first pass read-only; produce this report before editing.",
        "Do not edit qb-core directly.",
        "Backup the incoming script folder before any changes.",
        "Use AGENT FIX START and AGENT FIX END markers around major generated edits.",
    ]

    if "ESX" in assumptions["framework"]:
        plan.append("Add or convert framework access to QBCore inside the incoming script.")
    if "ox_inventory" in assumptions["inventory"] and "qb-inventory" in resources:
        plan.append("Create a qb-inventory compatibility adapter for item checks and item mutations.")
    if "ox_target" in assumptions["target"] and "qb-target" in resources:
        plan.append("Map ox_target registrations to qb-target equivalents inside the incoming script.")
    if any(db in assumptions["database"] for db in ["mysql-async", "ghmattimysql"]):
        plan.append("Convert database calls to oxmysql syntax only after reviewing query behavior.")
    if "ox_lib" in assumptions.get("framework", []) and "ox_lib" not in resources:
        plan.append("Remove or replace ox_lib dependencies, or ask before adding ox_lib to the server.")
    if risks:
        plan.append("Stop for approval before schema, inventory core, money, permissions, or player data changes.")

    return plan


def suggested_code_fixes(assumptions: dict[str, list[str]], resources: set[str]) -> list[dict[str, str]]:
    fixes = [
        {
            "title": "ESX to QBCore framework access",
            "reason": "replace ESX player lookup with QBCore player lookup inside the incoming script",
            "applies": "ESX" in assumptions["framework"] and "qb-core" in resources,
            "body": """local QBCore = exports['qb-core']:GetCoreObject()

RegisterNetEvent('example:server:action', function()
    local src = source
    local Player = QBCore.Functions.GetPlayer(src)

    if not Player then
        return
    end

    local citizenid = Player.PlayerData.citizenid
    -- Continue using citizenid or Player.Functions APIs in this resource.
end)""",
        },
        {
            "title": "ox_inventory to qb-inventory item check and remove",
            "reason": "replace ox_inventory item count and removal with QBCore player item APIs",
            "applies": "ox_inventory" in assumptions["inventory"] and "qb-inventory" in resources,
            "body": """local QBCore = exports['qb-core']:GetCoreObject()

RegisterNetEvent('example:server:takeItem', function()
    local src = source
    local Player = QBCore.Functions.GetPlayer(src)

    if not Player then
        return
    end

    local item = Player.Functions.GetItemByName('lockpick')
    if item and item.amount > 0 then
        Player.Functions.RemoveItem('lockpick', 1)
        TriggerClientEvent('inventory:client:ItemBox', src, QBCore.Shared.Items['lockpick'], 'remove')
    end
end)""",
        },
        {
            "title": "ox_target to qb-target box zone",
            "reason": "replace ox_target zone registration with qb-target AddBoxZone",
            "applies": "ox_target" in assumptions["target"] and "qb-target" in resources,
            "body": """CreateThread(function()
    exports['qb-target']:AddBoxZone(
        'test_bad_script_open',
        vector3(0.0, 0.0, 72.0),
        1.5,
        1.5,
        {
            name = 'test_bad_script_open',
            heading = 0.0,
            minZ = 71.0,
            maxZ = 73.0,
        },
        {
            options = {
                {
                    icon = 'fa-solid fa-box',
                    label = 'Open stash',
                    action = function()
                        TriggerEvent('test-bad-script:client:openStash')
                    end,
                },
            },
            distance = 2.0,
        }
    )
end)""",
        },
        {
            "title": "mysql-async to oxmysql query",
            "reason": "replace mysql-async callback query with oxmysql await query",
            "applies": "mysql-async" in assumptions["database"] and "oxmysql" in resources,
            "body": """local rows = MySQL.query.await(
    'SELECT * FROM players WHERE citizenid = ?',
    { citizenid }
)

print(('oxmysql result count: %s'):format(#rows))""",
        },
    ]

    return fixes


def render_suggested_code_fixes(assumptions: dict[str, list[str]], resources: set[str]) -> list[str]:
    lines = [
        "",
        "## Suggested Code Fixes",
        "",
        "These are read-only examples for the incoming script. They are not patches, do not overwrite full files, and must not be applied to qb-core or live server resources.",
    ]

    for fix in suggested_code_fixes(assumptions, resources):
        status = "likely relevant" if fix["applies"] else "example only; matching dependency was not detected with the current server profile"
        lines.extend(
            [
                "",
                f"### {fix['title']}",
                "",
                f"- Status: {status}",
                "- Apply only inside the incoming script after review and backup.",
                "",
                "```lua",
                f"-- AGENT FIX START: {fix['reason']}",
                fix["body"],
                "-- AGENT FIX END",
                "```",
            ]
        )

    return lines


def render_patch_plan(script_path: Path, server_path: Path, scan: dict, resources: set[str]) -> str:
    assumptions = scan["assumptions"]
    risks = compare_assumptions(assumptions, resources)
    plan = adaptation_plan(assumptions, resources, risks)

    lines = [
        "# FiveM Patch Plan",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Staged script: `{script_path}`",
        f"Server: `{server_path}`",
        "",
        "## Summary of Detected Issues",
        "",
        f"- Manifest present at script root: {'yes' if scan['has_manifest'] else 'no'}",
        f"- Files scanned: {len(scan['files'])}",
    ]

    for category, values in assumptions.items():
        lines.append(f"- {category}: {', '.join(values) if values else 'not detected'}")

    lines.extend(["", "## Risk Flags"])
    if risks:
        lines.extend(f"- {risk}" for risk in risks)
    else:
        lines.append("- No obvious high-risk compatibility issues detected.")

    lines.extend(["", "## Adaptation Plan"])
    lines.extend(f"{index}. {item}" for index, item in enumerate(plan, start=1))
    lines.extend(render_suggested_code_fixes(assumptions, resources))

    lines.extend(
        [
            "",
            "## Read-Only Guardrails",
            "",
            "- This plan is not a patch and does not overwrite full files.",
            "- Apply changes only inside the staged script after review.",
            "- Do not modify live FiveM resources.",
            "- Do not edit qb-core directly.",
        ]
    )

    return "\n".join(lines) + "\n"


def render_report(
    script_path: Path,
    server_path: Path,
    scan: dict,
    resources: set[str],
    include_suggestions: bool = False,
) -> str:
    assumptions = scan["assumptions"]
    risks = compare_assumptions(assumptions, resources)
    plan = adaptation_plan(assumptions, resources, risks)

    lines = [
        "# FiveM Integration Report",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Script: `{script_path}`",
        f"Server: `{server_path}`",
        "",
        "## Script Summary",
        "",
        f"- Manifest present at script root: {'yes' if scan['has_manifest'] else 'no'}",
        f"- Files scanned: {len(scan['files'])}",
        "",
        "## Detected Script Assumptions",
    ]

    for category, values in assumptions.items():
        lines.append(f"- {category}: {', '.join(values) if values else 'not detected'}")

    lines.extend(["", "## Evidence"])
    for category, by_name in scan["evidence"].items():
        if not by_name:
            lines.append(f"- {category}: none")
            continue
        for name, markers in by_name.items():
            lines.append(f"- {category}/{name}: {', '.join(markers[:8])}")

    lines.extend(["", "## Server Compatibility"])
    for resource in KEY_RESOURCES:
        lines.append(f"- {resource}: {'present' if resource in resources else 'missing'}")

    lines.extend(["", "## Risk Flags"])
    if risks:
        lines.extend(f"- {risk}" for risk in risks)
    else:
        lines.append("- No obvious high-risk compatibility issues detected.")

    lines.extend(["", "## Adaptation Plan"])
    lines.extend(f"{index}. {item}" for index, item in enumerate(plan, start=1))

    if include_suggestions:
        lines.extend(render_suggested_code_fixes(assumptions, resources))

    lines.extend(["", "## Safety Gates", ""])
    lines.append("- Stop and ask before database schema changes.")
    lines.append("- Stop and ask before inventory core changes.")
    lines.append("- Stop and ask before money, permissions, or player data changes.")
    lines.append("- Prefer adapters inside the incoming script over server core edits.")

    lines.extend(["", "## File List"])
    for file_name in scan["files"][:300]:
        lines.append(f"- {file_name}")
    if len(scan["files"]) > 300:
        lines.append(f"- ... {len(scan['files']) - 300} more files omitted")

    return "\n".join(lines) + "\n"


def ensure_qbcore_init(text: str) -> tuple[str, bool]:
    if "GetCoreObject" in text or "local QBCore" in text:
        return text, False

    init_block = (
        "-- AGENT FIX START: initialize QBCore for staged compatibility work\n"
        "local QBCore = exports['qb-core']:GetCoreObject()\n"
        "-- AGENT FIX END\n\n"
    )
    return init_block + text, True


def replace_esx_references(text: str) -> tuple[str, bool]:
    updated = text
    changed = False

    patterns = [
        (r"local\s+ESX\s*=\s*exports\[['\"]es_extended['\"]\]:getSharedObject\(\)\s*\n?", ""),
        (r"ESX\.GetPlayerFromId\(([^)]+)\)", r"QBCore.Functions.GetPlayer(\1)"),
        (r"\bplayer\.identifier\b", "Player.PlayerData.citizenid"),
        (r"\bplayer\b", "Player"),
        (r"ESX\.ShowNotification\(([^)]+)\)", r"QBCore.Functions.Notify(\1)"),
    ]

    for pattern, replacement in patterns:
        updated_next = re.sub(pattern, replacement, updated)
        if updated_next != updated:
            updated = updated_next
            changed = True

    if changed and "AGENT FIX START: replace obvious ESX references with QBCore equivalents" not in updated:
        updated = (
            "-- AGENT FIX START: replace obvious ESX references with QBCore equivalents\n"
            "-- Review each QBCore player and notification call before moving this staged resource.\n"
            "-- AGENT FIX END\n"
            + updated
        )

    return updated, changed


def replace_mysql_async(text: str) -> tuple[str, bool]:
    pattern = re.compile(
        r"MySQL\.Async\.fetchAll\(\s*"
        r"(?P<query>'[^']*'|\"[^\"]*\")\s*,\s*"
        r"(?P<params>\{.*?\})\s*,\s*"
        r"function\((?P<result>\w+)\)\s*"
        r"(?P<body>.*?)"
        r"\s*end\s*"
        r"\)",
        re.DOTALL,
    )

    def replacement(match: re.Match) -> str:
        query = match.group("query")
        params = match.group("params")
        result = match.group("result")
        body = match.group("body").strip()
        return (
            "-- AGENT FIX START: convert basic mysql-async fetchAll to oxmysql await query\n"
            f"local {result} = MySQL.query.await(\n"
            f"        {query},\n"
            f"        {params}\n"
            "    )\n"
            f"    {body}\n"
            "-- AGENT FIX END"
        )

    updated, count = pattern.subn(replacement, text)
    return updated, count > 0


def apply_staged_fixes(script_path: Path) -> list[str]:
    plan_file = script_path / "patch-plan.md"
    if not plan_file.is_file():
        raise SystemExit(f"patch-plan.md not found: {plan_file}")

    changed_files = []
    for file_path in sorted(script_path.rglob("*.lua")):
        if not file_path.is_file():
            continue

        original = read_text(file_path)
        if "AGENT FIX START" in original:
            continue

        updated = original
        file_changed = False

        needs_qbcore = "ESX" in updated or "ox_inventory" in updated
        if needs_qbcore:
            updated, changed = ensure_qbcore_init(updated)
            file_changed = file_changed or changed

        updated, changed = replace_esx_references(updated)
        file_changed = file_changed or changed

        updated, changed = replace_mysql_async(updated)
        file_changed = file_changed or changed

        if file_changed and updated != original:
            file_path.write_text(updated, encoding="utf-8")
            changed_files.append(str(file_path.relative_to(script_path)))

    return changed_files


def main() -> int:
    parser = argparse.ArgumentParser(description="FiveM incoming script compatibility scanner")
    parser.add_argument("--script", required=True, help="Incoming script folder")
    parser.add_argument("--server", default=str(DEFAULT_SERVER), help="FiveM server base folder")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Reports folder")
    parser.add_argument("--suggest", action="store_true", help="Add read-only suggested code fixes to the report")
    parser.add_argument("--plan-out", help="Write a read-only patch plan to this markdown file")
    parser.add_argument("--no-report", action="store_true", help="Skip writing the standard integration report")
    parser.add_argument("--apply-staged", action="store_true", help="Apply safe fixes only inside the staged script folder")
    args = parser.parse_args()

    script_path = Path(args.script).expanduser().resolve()
    server_path = Path(args.server).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()

    if not script_path.is_dir():
        raise SystemExit(f"Script folder not found: {script_path}")
    if not server_path.is_dir():
        raise SystemExit(f"Server folder not found: {server_path}")

    if args.apply_staged:
        changed_files = apply_staged_fixes(script_path)
        if changed_files:
            print("Changed staged files:")
            for file_name in changed_files:
                print(f"- {file_name}")
        else:
            print("No staged file changes applied.")
        return 0

    scan = scan_script(script_path)
    resources = scan_server_resources(server_path)

    if args.plan_out:
        plan_file = Path(args.plan_out).expanduser().resolve()
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(render_patch_plan(script_path, server_path, scan, resources), encoding="utf-8")
        print(f"Patch plan created: {plan_file}")

    if args.no_report:
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    report = render_report(script_path, server_path, scan, resources, include_suggestions=args.suggest)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_file = out_dir / f"integration-report-{script_path.name}-{timestamp}.md"
    report_file.write_text(report, encoding="utf-8")

    print(f"Report created: {report_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
