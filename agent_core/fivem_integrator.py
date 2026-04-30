#!/usr/bin/env python3
"""Create read-only FiveM script integration compatibility reports."""

from __future__ import annotations

import argparse
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


def render_report(script_path: Path, server_path: Path, scan: dict, resources: set[str]) -> str:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="FiveM incoming script compatibility scanner")
    parser.add_argument("--script", required=True, help="Incoming script folder")
    parser.add_argument("--server", default=str(DEFAULT_SERVER), help="FiveM server base folder")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Reports folder")
    args = parser.parse_args()

    script_path = Path(args.script).expanduser().resolve()
    server_path = Path(args.server).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()

    if not script_path.is_dir():
        raise SystemExit(f"Script folder not found: {script_path}")
    if not server_path.is_dir():
        raise SystemExit(f"Server folder not found: {server_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    scan = scan_script(script_path)
    resources = scan_server_resources(server_path)
    report = render_report(script_path, server_path, scan, resources)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_file = out_dir / f"integration-report-{script_path.name}-{timestamp}.md"
    report_file.write_text(report, encoding="utf-8")

    print(f"Report created: {report_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
