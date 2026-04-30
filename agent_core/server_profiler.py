#!/usr/bin/env python3
"""Profile a local FiveM/QBCore server without modifying live resources."""

from __future__ import annotations

import argparse
import json
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
    "qb-weapons",
    "qb-smallresources",
    "qb-multicharacter",
]


def has_manifest(path: Path) -> bool:
    return (path / "fxmanifest.lua").is_file() or (path / "__resource.lua").is_file()


def manifest_name(path: Path) -> str:
    if (path / "fxmanifest.lua").is_file():
        return "fxmanifest.lua"
    if (path / "__resource.lua").is_file():
        return "__resource.lua"
    return ""


def scan_resources(resources_path: Path) -> list[dict[str, str]]:
    resources = []
    for path in resources_path.rglob("*"):
        if path.is_dir() and has_manifest(path):
            parent = path.parent.relative_to(resources_path)
            resources.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "folder": "." if str(parent) == "." else str(parent),
                    "manifest": manifest_name(path),
                }
            )
    return sorted(resources, key=lambda item: (item["name"].lower(), item["path"]))


def build_profile(server_path: Path) -> dict:
    resources_path = server_path / "resources"
    if not resources_path.exists():
        raise FileNotFoundError(f"Resources folder not found: {resources_path}")

    resources = scan_resources(resources_path)
    names = {resource["name"] for resource in resources}
    key_resources = {
        name: {
            "present": name in names,
            "status": "present" if name in names else "missing",
        }
        for name in KEY_RESOURCES
    }

    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "server_path": str(server_path),
        "resources_path": str(resources_path),
        "total_resources": len(resources),
        "stack": {
            "framework": "QBCore",
            "inventory": "qb-inventory",
            "target": "qb-target",
            "menu": "qb-menu",
            "input": "qb-input",
            "database": "oxmysql",
            "voice": "pma-voice",
            "known_missing": ["ox_lib", "illenium-appearance"],
        },
        "key_resources": key_resources,
        "resources": resources,
    }


def render_markdown(profile: dict) -> str:
    lines = [
        "# FiveM Server Profile",
        "",
        f"Generated: {profile['generated']}",
        f"Server: `{profile['server_path']}`",
        f"Resources: `{profile['resources_path']}`",
        f"Total resources: {profile['total_resources']}",
        "",
        "## Stack Summary",
        "",
        "- Framework: QBCore",
        "- Inventory: qb-inventory",
        "- Target: qb-target",
        "- Menu/Input: qb-menu, qb-input",
        "- Database: oxmysql",
        "- Voice: pma-voice",
        "- Known missing: ox_lib, illenium-appearance",
        "",
        "## Key Resources",
    ]

    for name, info in profile["key_resources"].items():
        lines.append(f"- {name}: {info['status']}")

    lines.extend(["", "## All Resources"])
    for resource in profile["resources"]:
        lines.append(
            f"- `{resource['name']}` - `{resource['folder']}` ({resource['manifest']})"
        )

    lines.extend(
        [
            "",
            "## Safety Notes",
            "",
            "- This profile is read-only.",
            "- Do not edit qb-core directly.",
            "- Use compatibility reports before changing incoming scripts.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_reports(profile: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_file = out_dir / "server-profile.json"
    md_file = out_dir / "server-profile.md"
    json_file.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    md_file.write_text(render_markdown(profile), encoding="utf-8")
    return md_file, json_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile a FiveM server resource tree")
    parser.add_argument("--server", default=str(DEFAULT_SERVER), help="FiveM server base folder")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Reports folder")
    args = parser.parse_args()

    server_path = Path(args.server).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()

    profile = build_profile(server_path)
    md_file, json_file = write_reports(profile, out_dir)

    print(f"Server resources scanned: {profile['total_resources']}")
    print(f"Created: {md_file}")
    print(f"Created: {json_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
