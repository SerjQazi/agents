"""Read-only FiveM incoming script scanner."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import PlannerConfig


TEXT_EXTS = {".lua", ".js", ".json", ".cfg", ".sql", ".md", ".txt", ".html", ".css", ".xml", ".yml", ".yaml"}
MAX_FILE_BYTES = 256_000

MARKERS = {
    "framework": {
        "QBCore": ["qb-core", "QBCore", "GetCoreObject", "exports['qb-core']"],
        "ESX": ["es_extended", "ESX.GetPlayerFromId", "getSharedObject", "ESX.RegisterServerCallback"],
        "Qbox": ["qbx_core", "exports.qbx_core", "exports['qbx_core']"],
    },
    "database": {
        "oxmysql": ["oxmysql", "MySQL.query", "MySQL.insert", "MySQL.update", "MySQL.scalar"],
        "mysql-async": ["mysql-async", "MySQL.Async"],
        "ghmattimysql": ["ghmattimysql", "exports.ghmattimysql"],
    },
    "target": {
        "qb-target": ["qb-target", "exports['qb-target']", "AddTargetEntity", "AddBoxZone"],
        "ox_target": ["ox_target", "exports.ox_target", "exports['ox_target']"],
    },
    "inventory": {
        "qb-inventory": ["qb-inventory", "GetItemByName", "Player.Functions.AddItem", "Player.Functions.RemoveItem"],
        "ox_inventory": ["ox_inventory", "exports.ox_inventory", "exports['ox_inventory']"],
        "ps-inventory": ["ps-inventory", "exports['ps-inventory']"],
    },
}


class ScriptScanner:
    def __init__(self, config: PlannerConfig) -> None:
        self.config = config

    def resolve_script_path(self, script_path: str | None) -> Path | None:
        if not script_path:
            return None
        raw = Path(script_path).expanduser()
        if raw.is_absolute():
            candidate = raw.resolve()
        else:
            candidate = (self.config.agents_root / raw).resolve()

        incoming_root = self.config.incoming_dir.resolve()
        if candidate != incoming_root and incoming_root not in candidate.parents:
            raise ValueError(f"Script path must stay inside {incoming_root}")
        if not candidate.exists() or not candidate.is_dir():
            raise FileNotFoundError(f"Incoming script folder not found: {candidate}")
        return candidate

    def scan(self, script_path: str | None) -> dict[str, Any]:
        target = self.resolve_script_path(script_path)
        if target is None:
            return {
                "script_path": None,
                "files": [],
                "text_files_read": [],
                "sql_files": [],
                "manifest": None,
                "dependencies": [],
                "markers": {},
                "findings": [
                    {
                        "category": "task",
                        "severity": "info",
                        "message": "No script path supplied; task will use prompt and memory only.",
                        "evidence": {},
                    }
                ],
                "summary_text": "No script folder was provided.",
            }

        files: list[str] = []
        text_files_read: list[str] = []
        sql_files: list[str] = []
        manifest_text = ""
        text_chunks: list[str] = []

        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(target).as_posix()
            files.append(relative)
            if path.suffix.lower() == ".sql":
                sql_files.append(relative)
            if path.name in {"fxmanifest.lua", "__resource.lua"}:
                manifest_text = self._read_text(path)
            if path.suffix.lower() in TEXT_EXTS or path.name in {"fxmanifest.lua", "__resource.lua"}:
                text_files_read.append(relative)
                text_chunks.append(f"\n--- {relative} ---\n{self._read_text(path)}")

        combined = "\n".join(text_chunks)
        markers = self._detect_markers(combined)
        dependencies = self._parse_dependencies(manifest_text)
        findings = self._build_findings(target, files, sql_files, manifest_text, dependencies, markers)

        return {
            "script_path": str(target),
            "files": files,
            "text_files_read": text_files_read,
            "sql_files": sql_files,
            "manifest": "fxmanifest.lua" if (target / "fxmanifest.lua").is_file() else "__resource.lua" if (target / "__resource.lua").is_file() else None,
            "dependencies": dependencies,
            "markers": markers,
            "findings": findings,
            "summary_text": self._summary_text(target, files, sql_files, dependencies, markers),
        }

    def _read_text(self, path: Path) -> str:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                return path.read_text(encoding="utf-8", errors="ignore")[:MAX_FILE_BYTES]
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def _detect_markers(self, combined: str) -> dict[str, dict[str, list[str]]]:
        result: dict[str, dict[str, list[str]]] = {}
        for category, options in MARKERS.items():
            result[category] = {}
            for name, needles in options.items():
                hits = sorted({needle for needle in needles if needle in combined})
                if hits:
                    result[category][name] = hits
        return result

    def _parse_dependencies(self, manifest_text: str) -> list[str]:
        if not manifest_text:
            return []
        deps = set()
        dependency_block = re.findall(r"dependencies\s*{([^}]+)}", manifest_text, flags=re.DOTALL)
        for block in dependency_block:
            for match in re.findall(r"['\"]([^'\"]+)['\"]", block):
                deps.add(match)
        for match in re.findall(r"dependency\s+['\"]([^'\"]+)['\"]", manifest_text):
            deps.add(match)
        return sorted(deps)

    def _build_findings(
        self,
        target: Path,
        files: list[str],
        sql_files: list[str],
        manifest_text: str,
        dependencies: list[str],
        markers: dict[str, dict[str, list[str]]],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        if not manifest_text:
            findings.append(
                {
                    "category": "manifest",
                    "severity": "warning",
                    "message": "No fxmanifest.lua or __resource.lua found.",
                    "evidence": {"script_path": str(target)},
                }
            )
        if sql_files:
            findings.append(
                {
                    "category": "database",
                    "severity": "high",
                    "message": "SQL files found. Planner Agent must not run SQL automatically.",
                    "evidence": {"sql_files": sql_files},
                }
            )
        if "ESX" in markers.get("framework", {}):
            findings.append(
                {
                    "category": "framework",
                    "severity": "medium",
                    "message": "ESX markers found; likely needs QBCore adaptation.",
                    "evidence": markers["framework"]["ESX"],
                }
            )
        if "mysql-async" in markers.get("database", {}):
            findings.append(
                {
                    "category": "database",
                    "severity": "medium",
                    "message": "mysql-async markers found; likely needs oxmysql adaptation.",
                    "evidence": markers["database"]["mysql-async"],
                }
            )
        if "ox_target" in markers.get("target", {}):
            findings.append(
                {
                    "category": "target",
                    "severity": "medium",
                    "message": "ox_target markers found; may need qb-target mapping.",
                    "evidence": markers["target"]["ox_target"],
                }
            )
        findings.append(
            {
                "category": "scan",
                "severity": "info",
                "message": f"Read-only scan found {len(files)} files and {len(dependencies)} manifest dependencies.",
                "evidence": {"file_count": len(files), "dependencies": dependencies},
            }
        )
        return findings

    def _summary_text(
        self,
        target: Path,
        files: list[str],
        sql_files: list[str],
        dependencies: list[str],
        markers: dict[str, dict[str, list[str]]],
    ) -> str:
        marker_names = []
        for category, options in markers.items():
            for name in options:
                marker_names.append(f"{category}:{name}")
        return (
            f"Script: {target.name}\n"
            f"Files: {len(files)}\n"
            f"SQL files: {len(sql_files)}\n"
            f"Dependencies: {', '.join(dependencies) if dependencies else 'none detected'}\n"
            f"Markers: {', '.join(marker_names) if marker_names else 'none detected'}"
        )

