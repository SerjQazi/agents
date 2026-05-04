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

DEPENDENCY_NEEDLES = {
    "mysql-async": ["mysql-async", "MySQL.Async"],
    "oxmysql": ["oxmysql", "MySQL.query", "MySQL.insert", "MySQL.update", "MySQL.scalar", "exports.oxmysql"],
    "es_extended": ["es_extended", "esx:getSharedObject", "ESX."],
    "qb-core": ["qb-core", "QBCore", "exports['qb-core']"],
    "ox_lib": ["ox_lib", "@ox_lib", "lib."],
    "qb-target": ["qb-target", "exports['qb-target']"],
    "ox_target": ["ox_target", "exports.ox_target", "exports['ox_target']"],
}

PATTERN_RULES = {
    "ESX.GetPlayerData": {
        "needles": ["ESX.GetPlayerData", "ESX.PlayerData"],
        "type": "framework",
        "problem": "ESX player data API is not compatible with QBCore.",
        "fix_strategy": "Map ESX.PlayerData or ESX.GetPlayerData usage to QBCore.PlayerData and QBCore functions.",
    },
    "TriggerServerEvent": {
        "needles": ["TriggerServerEvent"],
        "type": "event",
        "problem": "Client-to-server event usage needs validation for QBCore event names and payloads.",
        "fix_strategy": "Review event names, payload shape, and server handlers before staging compatibility changes.",
    },
    "RegisterNetEvent": {
        "needles": ["RegisterNetEvent"],
        "type": "event",
        "problem": "Network event registration may need namespace or payload adaptation.",
        "fix_strategy": "Keep event handlers local to the resource unless a QBCore event mapping is required.",
    },
    "database queries": {
        "needles": ["MySQL.Async", "MySQL.query", "MySQL.insert", "MySQL.update", "MySQL.scalar", "execute(", "fetchAll("],
        "type": "database",
        "problem": "Database query API or SQL file detected.",
        "fix_strategy": "Stage mysql-async to oxmysql API changes only; never execute SQL automatically.",
    },
    "inventory usage": {
        "needles": ["xPlayer.addInventoryItem", "xPlayer.removeInventoryItem", "Player.Functions.AddItem", "Player.Functions.RemoveItem", "ESX.Items"],
        "type": "inventory",
        "problem": "Inventory API usage may not match QBCore inventory.",
        "fix_strategy": "Map ESX inventory calls to qb-inventory or ps-inventory through a compatibility adapter.",
    },
    "targeting systems": {
        "needles": ["ox_target", "qb-target", "AddTargetEntity", "AddBoxZone", "exports.ox_target", "exports['qb-target']"],
        "type": "targeting",
        "problem": "Targeting API usage needs server target-system alignment.",
        "fix_strategy": "Map ox_target exports/options to qb-target equivalents in staged files.",
    },
}

MAPPING_RULES = {
    "local ESX = exports['es_extended']:getSharedObject()": "local QBCore = exports['qb-core']:GetCoreObject()",
    "exports['es_extended']:getSharedObject()": "exports['qb-core']:GetCoreObject()",
    "esx:getSharedObject": "exports['qb-core']:GetCoreObject()",
    "ESX.GetPlayerFromId": "QBCore.Functions.GetPlayer",
    "ESX.ShowNotification": "QBCore.Functions.Notify",
    "ESX.PlayerData": "QBCore.PlayerData",
    "ESX.GetPlayerData": "QBCore.Functions.GetPlayerData",
    "player.identifier": "player.PlayerData.citizenid",
    "mysql-async": "oxmysql",
    "MySQL.Async": "MySQL",
    "exports.ox_target": "exports['qb-target']",
    "exports['ox_target']": "exports['qb-target']",
    "ox_target": "qb-target",
    "xPlayer.addInventoryItem": "Player.Functions.AddItem",
    "xPlayer.removeInventoryItem": "Player.Functions.RemoveItem",
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
        file_text: dict[str, str] = {}

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
                content = self._read_text(path)
                text_files_read.append(relative)
                file_text[relative] = content
                text_chunks.append(f"\n--- {relative} ---\n{content}")

        combined = "\n".join(text_chunks)
        markers = self._detect_markers(combined)
        dependencies = self._parse_dependencies(manifest_text)
        integration_analysis = self._integration_analysis(files, file_text, sql_files, dependencies, markers)
        findings = self._build_findings(target, files, sql_files, manifest_text, dependencies, markers, integration_analysis)

        return {
            "script_path": str(target),
            "files": files,
            "text_files_read": text_files_read,
            "sql_files": sql_files,
            "manifest": "fxmanifest.lua" if (target / "fxmanifest.lua").is_file() else "__resource.lua" if (target / "__resource.lua").is_file() else None,
            "dependencies": dependencies,
            "markers": markers,
            "patterns": integration_analysis.get("patterns", {}),
            "mapping_rules": MAPPING_RULES,
            "integration_analysis": integration_analysis,
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
        integration_analysis: dict[str, Any],
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
        for issue in integration_analysis.get("issues", [])[:20]:
            findings.append(
                {
                    "category": issue.get("type", "integration"),
                    "severity": self._issue_severity(issue.get("type", "")),
                    "message": f"{issue.get('file', 'unknown')}: {issue.get('problem', '')}",
                    "evidence": {"fix_strategy": issue.get("fix_strategy", "")},
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

    def _integration_analysis(
        self,
        files: list[str],
        file_text: dict[str, str],
        sql_files: list[str],
        dependencies: list[str],
        markers: dict[str, dict[str, list[str]]],
    ) -> dict[str, Any]:
        detected_dependencies = sorted(
            {
                dependency
                for dependency, needles in DEPENDENCY_NEEDLES.items()
                if dependency in dependencies or any(needle in content for needle in needles for content in file_text.values())
            }
        )
        framework = self._framework_detected(markers, detected_dependencies, file_text)
        patterns: dict[str, list[str]] = {}
        issues: list[dict[str, str]] = []
        for relative, content in file_text.items():
            for pattern_name, rule in PATTERN_RULES.items():
                if any(needle in content for needle in rule["needles"]):
                    patterns.setdefault(pattern_name, []).append(relative)
                    issues.append(
                        {
                            "type": str(rule["type"]),
                            "file": relative,
                            "problem": str(rule["problem"]),
                            "fix_strategy": str(rule["fix_strategy"]),
                        }
                    )
            for source, target in MAPPING_RULES.items():
                if source in content:
                    issues.append(
                        {
                            "type": "mapping",
                            "file": relative,
                            "problem": f"Legacy or non-target API `{source}` detected.",
                            "fix_strategy": f"Map `{source}` to `{target}` inside staged output.",
                        }
                    )
        for sql_file in sql_files:
            issues.append(
                {
                    "type": "database",
                    "file": sql_file,
                    "problem": "SQL file is present in the script package.",
                    "fix_strategy": "Report SQL for manual review; do not execute it automatically.",
                }
            )
        risk_level = self._risk_level(issues, sql_files, framework)
        recommended_actions = self._recommended_actions(framework, detected_dependencies, issues)
        return {
            "framework_detected": framework,
            "target_framework": "QBCore",
            "files_scanned": files,
            "dependencies_detected": detected_dependencies,
            "patterns": patterns,
            "issues": issues,
            "risk_level": risk_level,
            "recommended_actions": recommended_actions,
        }

    def _framework_detected(
        self,
        markers: dict[str, dict[str, list[str]]],
        dependencies: list[str],
        file_text: dict[str, str],
    ) -> str:
        if "ESX" in markers.get("framework", {}) or "es_extended" in dependencies:
            return "ESX"
        if "QBCore" in markers.get("framework", {}) or "qb-core" in dependencies:
            return "QBCore"
        combined = "\n".join(file_text.values())
        if any(token in combined for token in ["ESX.", "esx:getSharedObject"]):
            return "ESX"
        if any(token in combined for token in ["QBCore", "exports['qb-core']"]):
            return "QBCore"
        return "standalone"

    def _risk_level(self, issues: list[dict[str, str]], sql_files: list[str], framework: str) -> str:
        issue_types = {issue.get("type", "") for issue in issues}
        if sql_files or "database" in issue_types:
            return "high"
        if framework == "ESX" or {"framework", "inventory", "targeting"} & issue_types:
            return "medium"
        return "low"

    def _recommended_actions(self, framework: str, dependencies: list[str], issues: list[dict[str, str]]) -> list[str]:
        actions = ["Generate staged compatibility patches only under /home/agentzero/agents/staging."]
        if framework == "ESX":
            actions.append("Convert ESX object/player data calls to QBCore equivalents.")
        if "mysql-async" in dependencies:
            actions.append("Replace mysql-async usage with oxmysql-compatible calls.")
        if "ox_target" in dependencies:
            actions.append("Map ox_target usage to qb-target exports/options.")
        if any(issue.get("type") == "inventory" for issue in issues):
            actions.append("Route ESX inventory calls through qb-inventory or ps-inventory compatibility.")
        actions.append("Wrap every generated code edit with AGENT FIX START and AGENT FIX END comments.")
        return actions

    def _issue_severity(self, issue_type: str) -> str:
        if issue_type == "database":
            return "high"
        if issue_type in {"framework", "inventory", "targeting", "mapping"}:
            return "medium"
        return "info"

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
