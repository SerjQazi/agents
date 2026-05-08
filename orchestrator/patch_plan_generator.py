"""Patch Plan Generator - Generates migration/adaptation plans for FiveM scripts."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class PatchPlanStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EffortLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DetectionType(str, Enum):
    DATABASE = "database"
    FRAMEWORK = "framework"
    TARGET_SYSTEM = "target_system"
    LEGACY_QBCORE_EXPORTS = "legacy_qbcore_exports"
    DEPRECATED_EVENT = "deprecated_event"
    SQL_REVIEW_REQUIRED = "sql_review_required"
    DEPENDENCY_CONFLICT = "dependency_conflict"
    MANIFEST_ISSUE = "manifest_issue"
    WEAPON_INVENTORY_INTEGRATION_RISK = "weapon_inventory_integration_risk"


@dataclass
class Detection:
    detection_type: DetectionType
    from_item: str
    to_item: str
    recommendation: str
    risk_assessment: RiskLevel
    estimated_effort: EffortLevel
    files_likely_requiring_edits: list[str] = field(default_factory=list)
    severity: str = "medium"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class PatchPlan:
    resource_id: str
    generated_at: str
    overview: str
    detected_frameworks: list[str]
    dependency_map: dict[str, str]
    migration_targets: list[dict[str, Any]]
    sql_warnings: list[str]
    risk_assessment_summary: str
    estimated_effort_summary: str
    recommended_human_review_points: list[str]
    safety_warnings: list[str]
    status: PatchPlanStatus = PatchPlanStatus.PENDING
    error_message: str | None = None


class PatchPlanGenerator:
    """Generator for FiveM script migration/adaptation patch plans."""

    DEPENDENCY_ALIASES = {
        "mysql-async": "oxmysql",
        "ghmattimysql": "oxmysql",
        "ESX": "QBCore",
        "ox_target": "qb-target",
        "ox_inventory": "qb-inventory",
    }

    DATABASE_PATTERNS = {
        "mysql-async": [
            r"MySQL\.Async\.execute",
            r"MySQL\.Async\.fetch",
            r"MySQL\.Async\.insert",
            r"exports?\['\"]mysql-async['\"]",
        ],
        "ghmattimysql": [
            r"exports?\['\"]ghmattimysql['\"]",
            r"GHMATTIMYSQL",
            r"Database\.execute",
            r"Database\.fetch",
        ],
        "oxmysql": [
            r"MySQL\.query",
            r"MySQL\.execute",
            r"exports?\['\"]oxmysql['\"]",
        ],
    }

    FRAMEWORK_PATTERNS = {
        "QBCore": [
            r"exports?\['\"]qb-core['\"]",
            r"GetCoreObject",
            r"QBCore\.Functions",
        ],
        "ESX": [
            r"es_extended",
            r"ESX\.GetPlayer",
            r"ESX\.RegisterServerCallback",
        ],
        "Qbox": [
            r"qbx_core",
            r"exports\['\"]qbx_core['\"]",
        ],
    }

    TARGET_PATTERNS = {
        "qb-target": [
            r"AddTargetEntity",
            r"AddBoxZone",
            r"AddPolyZone",
            r"exports?\['\"]qb-target['\"]",
        ],
        "ox_target": [
            r"exports\['\"]ox_target['\"]",
            r"AddTargetBox",
            r"AddTargetPoly",
        ],
    }

    INVENTORY_PATTERNS = {
        "qb-inventory": [
            "qb-inventory",
            "GetItemByName",
            "Player.Functions.AddItem",
            "Player.Functions.RemoveItem",
        ],
        "ox_inventory": [
            "ox_inventory",
            "exports\['\"]ox_inventory['\"]",
        ],
    }

    DEPRECATED_EVENT_PATTERNS = [
        r"AddEventHandler\(['\"]playerDropped",
        r"SetTimeout\s*\(\s*\d+",
        r"TriggerServerEvent\(['\"]esx_:",
        r"TriggerClientEvent\(['\"]esx_:",
        r"RegisterNetEvent",
        r"RegisterServerEvent",
        r"local\s+\w+\s*=\s*nil\s*--\s*(?:client|server)",
    ]

    LEGACY_QBCORE_EXPORTS = [
        r"QBCore\.Functions\.GetPlayer",
        r"QBCore\.Functions\.CreateBus",
        r"TriggerCallback",
        r"RegisterCallback",
    ]

    def __init__(
        self,
        base_dir: Path | None = None,
        archive_dir: Path | None = None,
        incoming_dir: Path | None = None,
    ):
        self.base_dir = base_dir or Path("/home/agentzero/agents")
        self.archive_dir = archive_dir or (self.base_dir / "orchestrator" / "archive")
        self.incoming_dir = incoming_dir or (self.base_dir / "incoming")
        self._status: dict[str, PatchPlanStatus] = {}
        self._results: dict[str, PatchPlan] = {}
        self._lock = threading.Lock()

    def _get_status(self, resource_id: str) -> PatchPlanStatus:
        with self._lock:
            return self._status.get(resource_id, PatchPlanStatus.PENDING)

    def _set_status(self, resource_id: str, status: PatchPlanStatus) -> None:
        with self._lock:
            self._status[resource_id] = status

    def get_status(self, resource_id: str) -> dict[str, Any]:
        return {
            "resource_id": resource_id,
            "status": self._get_status(resource_id).value,
        }

    def get_patch_plan(self, resource_id: str, format: str = "json") -> dict[str, Any] | str:
        safe = self._safe_resource_id(resource_id)
        result = self._results.get(safe)
        if result is None:
            result = self._load_patch_plan_from_disk(safe)
            if result is not None:
                with self._lock:
                    self._results[safe] = result
                    if self._status.get(safe) != PatchPlanStatus.IN_PROGRESS:
                        self._status[safe] = PatchPlanStatus.COMPLETED
        if not result:
            return (
                {"error": "Patch plan not found"}
                if format == "json"
                else "# Patch Plan Not Found\n\nNo patch plan has been generated yet."
            )

        if format == "json":
            return self._to_jsonable(result)
        else:
            return self._to_markdown(result)

    def _load_patch_plan_from_disk(self, resource_id: str) -> PatchPlan | None:
        archive_dir = self._resolve_archive_dir(resource_id)
        json_path = archive_dir / "patch-plan.json"
        if not json_path.is_file():
            return None
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            return PatchPlan(
                resource_id=str(data.get("resource_id", resource_id)),
                generated_at=str(data.get("generated_at", datetime.now(timezone.utc).isoformat())),
                overview=str(data.get("overview", "")),
                detected_frameworks=list(data.get("detected_frameworks", [])),
                dependency_map=dict(data.get("dependency_map", {})),
                migration_targets=list(data.get("migration_targets", [])),
                sql_warnings=list(data.get("sql_warnings", [])),
                risk_assessment_summary=str(data.get("risk_assessment_summary", "")),
                estimated_effort_summary=str(data.get("estimated_effort_summary", "")),
                recommended_human_review_points=list(data.get("recommended_human_review_points", [])),
                safety_warnings=list(data.get("safety_warnings", [])),
                status=PatchPlanStatus.COMPLETED,
            )
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return None

    def _to_jsonable(self, plan: PatchPlan) -> dict[str, Any]:
        return {
            "resource_id": plan.resource_id,
            "generated_at": plan.generated_at,
            "overview": plan.overview,
            "detected_frameworks": plan.detected_frameworks,
            "dependency_map": plan.dependency_map,
            "migration_targets": plan.migration_targets,
            "sql_warnings": plan.sql_warnings,
            "risk_assessment_summary": plan.risk_assessment_summary,
            "estimated_effort_summary": plan.estimated_effort_summary,
            "recommended_human_review_points": plan.recommended_human_review_points,
            "safety_warnings": plan.safety_warnings,
        }

    def _to_markdown(self, plan: PatchPlan) -> str:
        md = [
            f"# Patch Plan for {plan.resource_id}",
            "",
            f"**Generated At:** {plan.generated_at}",
            "",
            "## Overview",
            plan.overview,
            "",
            "## Detected Frameworks",
        ]
        for fw in plan.detected_frameworks:
            md.append(f"- {fw}")

        md.extend(["", "## Dependency Map"])
        for src, tgt in plan.dependency_map.items():
            md.append(f"- `{src}` -> `{tgt}`")

        md.extend(["", "## Migration Targets"])

        for mt in plan.migration_targets:
            detection_type = mt.get("type", "unknown")
            md.append(f"\n### {detection_type}: {mt.get('from')} to {mt.get('to')}")
            md.append(f"- **Recommendation:** {mt.get('recommendation', 'N/A')}")
            md.append(f"- **Risk Assessment:** {mt.get('risk_assessment', 'N/A')}")
            md.append(f"- **Estimated Effort:** {mt.get('estimated_effort', 'N/A')}")
            files = mt.get("files_likely_requiring_edits", [])
            if files:
                md.append("- **Files Likely Requiring Edits:**")
                for f in files:
                    md.append(f"  - `{f}`")

        if plan.sql_warnings:
            md.extend(["", "## SQL Warnings"])
            for w in plan.sql_warnings:
                md.append(f"- {w}")

        md.extend(["", "## Risk Assessment Summary", plan.risk_assessment_summary])
        md.extend(["", "## Estimated Effort Summary", plan.estimated_effort_summary])

        if plan.recommended_human_review_points:
            md.extend(["", "## Recommended Human Review Points"])
            for p in plan.recommended_human_review_points:
                md.append(f"- {p}")

        md.extend(["", "## Safety Warnings"])
        md.extend([
            "- **STRICTLY read-only.**",
            "- NO live modifications.",
            "- NO staging apply.",
            "- NO auto patching.",
            "- NO txAdmin restart.",
            "- NO git push.",
        ])

        return "\n".join(md)

    def _safe_resource_id(self, resource_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_\-]", "", resource_id)
        if safe != resource_id:
            raise ValueError(f"Invalid resource_id: {resource_id}")
        return safe

    def _resolve_resource_dir(self, resource_id: str) -> Path:
        safe = self._safe_resource_id(resource_id)
        incoming_root = self.incoming_dir.resolve()
        script_dir = (incoming_root / safe).resolve()
        if incoming_root not in script_dir.parents:
            raise ValueError(f"Resolved script path escaped incoming root: {safe}")
        if not script_dir.exists():
            raise FileNotFoundError(f"Incoming script folder not found: {safe}")
        if not script_dir.is_dir():
            raise FileNotFoundError(f"Incoming script path is not a directory: {safe}")
        return script_dir

    def _resolve_archive_dir(self, resource_id: str) -> Path:
        safe = self._safe_resource_id(resource_id)
        archive_root = self.archive_dir.resolve()
        archive_path = (archive_root / safe).resolve()
        if archive_root not in archive_path.parents:
            raise ValueError(f"Resolved archive path escaped archive root: {safe}")
        archive_path.mkdir(parents=True, exist_ok=True)
        return archive_path

    def _load_latest_analysis_report(self, resource_id: str) -> dict[str, Any] | None:
        """
        Load latest analysis report for a resource from reports/analysis.
        This keeps patch plans grounded in real analysis artifacts when available.
        """
        reports_dir = (self.base_dir / "reports" / "analysis").resolve()
        if not reports_dir.is_dir():
            return None
        candidates = sorted(
            reports_dir.glob(f"analysis-{resource_id}-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return None
        try:
            return json.loads(candidates[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def generate(
        self,
        resource_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Generate a patch plan for a resource. Thread-safe and can run in background."""
        safe = self._safe_resource_id(resource_id)

        with self._lock:
            if safe in self._status and not force:
                if self._status[safe] == PatchPlanStatus.IN_PROGRESS:
                    return {
                        "status": "already_running",
                        "message": "Patch plan generation already in progress",
                    }
                if (
                    safe in self._results
                    and self._status[safe] == PatchPlanStatus.COMPLETED
                    and not force
                ):
                    return {
                        "status": "exists",
                        "message": "Patch plan already exists (use force=true to regenerate)",
                    }

            self._status[safe] = PatchPlanStatus.IN_PROGRESS

        try:
            patch_plan = self._generate_patch_plan(safe)

            with self._lock:
                self._results[safe] = patch_plan
                self._status[safe] = PatchPlanStatus.COMPLETED

            self._save_patch_plan(safe, patch_plan)

            return {
                "status": "success",
                "message": "Patch plan generated successfully",
            }

        except Exception as e:
            with self._lock:
                self._status[safe] = PatchPlanStatus.FAILED

            return {"status": "error", "error": str(e)}

    def _generate_patch_plan(self, resource_id: str) -> PatchPlan:
        script_dir = self._resolve_resource_dir(resource_id)
        analysis_report = self._load_latest_analysis_report(resource_id)

        detections = []
        files_analyzed: list[str] = []
        all_content = ""

        for path in sorted(script_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".lua", ".js", ".json", ".cfg", ".sql"}:
                relative = path.relative_to(script_dir).as_posix()
                files_analyzed.append(relative)
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    all_content += f"\n--- {relative} ---\n{content}"
                except Exception:
                    pass

        detections.extend(self._detect_database_migration(all_content, files_analyzed))
        detections.extend(self._detect_framework(all_content, files_analyzed))
        detections.extend(self._detect_target_system(all_content, files_analyzed))
        detections.extend(self._detect_legacy_qbcore_exports(all_content, files_analyzed))
        detections.extend(self._detect_deprecated_events(all_content, files_analyzed))
        detections.extend(self._detect_sql_usage(all_content, files_analyzed))
        detections.extend(self._detect_dependency_conflicts(all_content, files_analyzed))
        detections.extend(self._detect_manifest_issues(script_dir, files_analyzed))
        detections.extend(self._detect_weapon_inventory_risks(all_content, files_analyzed))

        return self._build_patch_plan(resource_id, detections, files_analyzed, analysis_report)

    def _detect_database_migration(
        self, content: str, files: list[str]
    ) -> list[Detection]:
        detections = []

        for db_type, patterns in self.DATABASE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    to_item = self.DEPENDENCY_ALIASES.get(db_type, "oxmysql")
                    if db_type != "oxmysql":
                        detections.append(
                            Detection(
                                detection_type=DetectionType.DATABASE,
                                from_item=db_type,
                                to_item=to_item,
                                recommendation=(
                                    f"Migrate from {db_type} to {to_item}. "
                                    "Update MySQL.query calls and remove mysql-async dependency."
                                ),
                                risk_assessment=self._assess_risk(db_type),
                                estimated_effort=self._assess_effort(content, db_type),
                                files_likely_requiring_edits=self._find_files_with_pattern(
                                    files, content, db_type
                                ),
                            )
                        )
                    break

        return detections

    def _detect_framework(
        self, content: str, files: list[str]
    ) -> list[Detection]:
        detections = []
        detected = set()

        for fw_type, patterns in self.FRAMEWORK_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    detected.add(fw_type)
                    break

        return detections

    def _detect_target_system(
        self, content: str, files: list[str]
    ) -> list[Detection]:
        detections = []

        for tgt_type, patterns in self.TARGET_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    to_item = self.DEPENDENCY_ALIASES.get(tgt_type, tgt_type)
                    if tgt_type not in ("ox_target",):
                        detections.append(
                            Detection(
                                detection_type=DetectionType.TARGET_SYSTEM,
                                from_item=tgt_type,
                                to_item=to_item,
                                recommendation=(
                                    f"Consider migrating from {tgt_type} to "
                                    f"{to_item} if target system compatibility needed."
                                ),
                                risk_assessment=RiskLevel.MEDIUM,
                                estimated_effort=EffortLevel.MEDIUM,
                                files_likely_requiring_edits=self._find_files_with_pattern(
                                    files, content, tgt_type
                                ),
                            )
                        )
                    break

        return detections

    def _detect_legacy_qbcore_exports(
        self, content: str, files: list[str]
    ) -> list[Detection]:
        detections = []

        for pattern in self.LEGACY_QBCORE_EXPORTS:
            if re.search(pattern, content, re.IGNORECASE):
                detections.append(
                    Detection(
                        detection_type=DetectionType.LEGACY_QBCORE_EXPORTS,
                        from_item="legacy_qbcore_exports",
                        to_item="qbus_qbcore_exports",
                        recommendation=(
                            "Legacy QBCore export detected. Update to use qbus-core exports "
                            "for compatibility with QBox or newer QBCore versions."
                        ),
                        risk_assessment=RiskLevel.MEDIUM,
                        estimated_effort=EffortLevel.LOW,
                        files_likely_requiring_edits=self._find_files_with_pattern(
                            files, content, pattern
                        ),
                    )
                )

        return detections

    def _detect_deprecated_events(
        self, content: str, files: list[str]
    ) -> list[Detection]:
        detections = []

        deprecated_patterns = [
            (r"RegisterNetEvent", "RegisterNetEvent is deprecated", "use RegisterNetEvent instead"),
            (r"RegisterServerEvent", "RegisterServerEvent is deprecated", "use RegisterNetEvent"),
        ]

        for pattern, desc, rec in deprecated_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                detections.append(
                    Detection(
                        detection_type=DetectionType.DEPRECATED_EVENT,
                        from_item=pattern,
                        to_item="proper_event_handler",
                        recommendation=f"{desc}. {rec}.",
                        risk_assessment=RiskLevel.LOW,
                        estimated_effort=EffortLevel.LOW,
                        files_likely_requiring_edits=self._find_files_with_pattern(
                            files, content, pattern
                        ),
                    )
                )

        return detections

    def _detect_sql_usage(
        self, content: str, files: list[str]
    ) -> list[Detection]:
        detections = []

        sql_patterns = [
            r"CREATE TABLE",
            r"ALTER TABLE",
            r"DROP TABLE",
            r"INSERT INTO",
            r"UPDATE\s+\w+\s+SET",
            r"DELETE FROM",
        ]

        has_sql = False
        for pattern in sql_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                has_sql = True
                break

        if has_sql:
            detections.append(
                Detection(
                    detection_type=DetectionType.SQL_REVIEW_REQUIRED,
                    from_item="sql_statements",
                    to_item="migration_needed",
                    recommendation=(
                        "SQL statements detected. Review for compatibility with "
                        "oxmysql and ensure proper table prefix handling."
                    ),
                    risk_assessment=RiskLevel.MEDIUM,
                    estimated_effort=EffortLevel.MEDIUM,
                    files_likely_requiring_edits=self._find_sql_files(files),
                )
            )

        return detections

    def _detect_dependency_conflicts(
        self, content: str, files: list[str]
    ) -> list[Detection]:
        detections = []
        deps_found: set[str] = set()

        all_deps = {}
        all_deps.update(self.DATABASE_PATTERNS)
        all_deps.update(self.FRAMEWORK_PATTERNS)
        all_deps.update(self.TARGET_PATTERNS)

        for dep_category, patterns in all_deps.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    deps_found.add(dep_category)

        if len(deps_found) > 1:
            detections.append(
                Detection(
                    detection_type=DetectionType.DEPENDENCY_CONFLICT,
                    from_item=", ".join(sorted(deps_found)),
                    to_item="resolve_conflicts",
                    recommendation=(
                        "Multiple dependencies detected. Verify compatibility "
                        "between frameworks and resolve any conflicts."
                    ),
                    risk_assessment=RiskLevel.MEDIUM,
                    estimated_effort=EffortLevel.MEDIUM,
                )
            )

        return detections

    def _detect_manifest_issues(
        self, script_dir: Path, files: list[str]
    ) -> list[Detection]:
        detections = []

        manifest = script_dir / "fxmanifest.lua"
        if manifest.exists():
            try:
                content = manifest.read_text(encoding="utf-8", errors="ignore")

                if "lua54 'yes'" not in content and "lua54 'true'" not in content:
                    detections.append(
                        Detection(
                            detection_type=DetectionType.MANIFEST_ISSUE,
                            from_item="missing_lua54",
                            to_item="lua54",
                            recommendation=(
                                "fxmanifest.lua does not specify lua54. "
                                "Add `lua54 'yes'` for Lua 5.4 compatibility."
                            ),
                            risk_assessment=RiskLevel.LOW,
                            estimated_effort=EffortLevel.LOW,
                            files_likely_requiring_edits=["fxmanifest.lua"],
                        )
                    )

            except Exception:
                pass

        return detections

    def _detect_weapon_inventory_risks(
        self, content: str, files: list[str]
    ) -> list[Detection]:
        detections = []

        inv_patterns = [
            r"qb-inventory",
            r"qb-weapons",
            r"GetWeaponName",
            r"GiveWeapon",
        ]

        found = []
        for pattern in inv_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                found.append(pattern)

        if len(found) >= 2:
            detections.append(
                Detection(
                    detection_type=DetectionType.WEAPON_INVENTORY_INTEGRATION_RISK,
                    from_item="weapon_inventory_integration",
                    to_item="verify_compatibility",
                    recommendation=(
                        "Weapon and inventory integration detected. "
                        "Verify qb-weapons compatibility with "
                        "qb-inventory or ox_inventory."
                    ),
                    risk_assessment=RiskLevel.MEDIUM,
                    estimated_effort=EffortLevel.MEDIUM,
                    files_likely_requiring_edits=self._find_files_with_pattern(
                        files, content, "weapon"
                    ),
                )
            )

        return detections

    def _assess_risk(self, db_type: str) -> RiskLevel:
        if db_type in ("mysql-async", "ghmattimysql"):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _assess_effort(self, content: str, db_type: str) -> EffortLevel:
        count = len(re.findall(r"MySQL\.", content, re.IGNORECASE))
        if count > 50:
            return EffortLevel.HIGH
        elif count > 20:
            return EffortLevel.MEDIUM
        return EffortLevel.LOW

    def _find_files_with_pattern(
        self, files: list[str], content: str, pattern: str
    ) -> list[str]:
        matches = []
        regex = re.compile(pattern, re.IGNORECASE)
        for f in files:
            if f.endswith((".lua", ".js")):
                try:
                    file_path = self.incoming_dir / self._safe_resource_id("") / f
                    if file_path.exists():
                        file_content = file_path.read_text(
                            encoding="utf-8", errors="ignore"
                        )
                        if regex.search(file_content):
                            matches.append(f)
                except Exception:
                    pass
        return list(set(matches))[:10]

    def _find_sql_files(self, files: list[str]) -> list[str]:
        return [f for f in files if f.endswith(".sql")]

    def _build_patch_plan(
        self,
        resource_id: str,
        detections: list[Detection],
        files_analyzed: list[str],
        analysis_report: dict[str, Any] | None = None,
    ) -> PatchPlan:
        analysis = (analysis_report or {}).get("full_analysis", {})
        analysis_markers = analysis.get("markers", {})
        analysis_dependencies = analysis.get("dependencies", [])
        analysis_summary_text = analysis.get("summary_text")

        frameworks = list(
            set(
                d.from_item
                for d in detections
                if d.detection_type == DetectionType.FRAMEWORK
            )
        )
        if not frameworks:
            marker_frameworks = sorted(list((analysis_markers.get("framework") or {}).keys()))
            frameworks = marker_frameworks if marker_frameworks else ["QBCore (auto-detect)"]

        dependency_map = {}
        for d in detections:
            if d.from_item in self.DEPENDENCY_ALIASES:
                dependency_map[d.from_item] = self.DEPENDENCY_ALIASES[d.from_item]
        # Include analysis dependencies to ground the plan in prior scan data.
        for dep in analysis_dependencies:
            if dep in self.DEPENDENCY_ALIASES:
                dependency_map[dep] = self.DEPENDENCY_ALIASES[dep]

        migration_targets = []
        for d in detections:
            migration_targets.append(
                {
                    "type": d.detection_type.value,
                    "from": d.from_item,
                    "to": d.to_item,
                    "recommendation": d.recommendation,
                    "risk_assessment": d.risk_assessment.value,
                    "estimated_effort": d.estimated_effort.value,
                    "files_likely_requiring_edits": d.files_likely_requiring_edits,
                }
            )

        sql_warnings = []
        for d in detections:
            if d.detection_type == DetectionType.SQL_REVIEW_REQUIRED:
                sql_warnings.append(
                    f"SQL statements in {len(d.files_likely_requiring_edits)} file(s) "
                    "require review for oxmysql compatibility."
                )

        risk_counts = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 0, RiskLevel.HIGH: 0}
        for d in detections:
            risk_counts[d.risk_assessment] += 1

        if risk_counts[RiskLevel.HIGH] > 0:
            risk_summary = "HIGH risk items detected - manual review strongly recommended"
        elif risk_counts[RiskLevel.MEDIUM] > 0:
            risk_summary = "MEDIUM risk items detected - review recommended"
        else:
            risk_summary = "LOW risk - primarily informational findings"

        effort_counts = {EffortLevel.LOW: 0, EffortLevel.MEDIUM: 0, EffortLevel.HIGH: 0}
        for d in detections:
            effort_counts[d.estimated_effort] += 1

        if effort_counts[EffortLevel.HIGH] > 0:
            effort_summary = f"HIGH effort required ({effort_counts[EffortLevel.HIGH]} items)"
        elif effort_counts[EffortLevel.MEDIUM] > 0:
            effort_summary = f"MEDIUM effort required ({effort_counts[EffortLevel.MEDIUM]} items)"
        else:
            effort_summary = f"LOW effort primarily ({effort_counts[EffortLevel.LOW]} items)"

        review_points = []
        if any(d.detection_type == DetectionType.DATABASE for d in detections):
            review_points.append("Review database migration from mysql-async/ghmattimysql to oxmysql")
        if any(d.detection_type == DetectionType.WEAPON_INVENTORY_INTEGRATION_RISK for d in detections):
            review_points.append("Verify weapon-inventory integration compatibility")
        if any(d.detection_type == DetectionType.SQL_REVIEW_REQUIRED for d in detections):
            review_points.append("Review SQL statements for oxmysql compatibility")
        if sql_warnings:
            review_points.append("Verify database table prefixes don't conflict with existing tables")

        overview = (
            f"Patch plan for {resource_id}. "
            f"Analyzed {len(files_analyzed)} files. "
            f"Found {len(detections)} migration targets."
        )
        if analysis_summary_text:
            overview += f" Analysis context: {analysis_summary_text}"

        return PatchPlan(
            resource_id=resource_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            overview=overview,
            detected_frameworks=frameworks if frameworks else ["QBCore"],
            dependency_map=dependency_map,
            migration_targets=migration_targets,
            sql_warnings=sql_warnings,
            risk_assessment_summary=risk_summary,
            estimated_effort_summary=effort_summary,
            recommended_human_review_points=review_points,
            safety_warnings=[
                "STRICTLY read-only. No live modifications.",
                "NO staging apply. NO auto patching.",
                "NO txAdmin restart. NO git push.",
            ],
            status=PatchPlanStatus.COMPLETED,
        )

    def _save_patch_plan(self, resource_id: str, plan: PatchPlan) -> None:
        archive_dir = self._resolve_archive_dir(resource_id)

        json_path = archive_dir / "patch-plan.json"
        json_data = self._to_jsonable(plan)
        json_path.write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        md_path = archive_dir / "patch-plan.md"
        md_path.write_text(self._to_markdown(plan), encoding="utf-8")


_patch_plan_generator: PatchPlanGenerator | None = None


def get_patch_plan_generator() -> PatchPlanGenerator:
    global _patch_plan_generator
    if _patch_plan_generator is None:
        _patch_plan_generator = PatchPlanGenerator()
    return _patch_plan_generator


def generate_patch_plan_background(resource_id: str) -> dict[str, Any]:
    """Generate patch plan in background thread."""
    generator = get_patch_plan_generator()
    thread = threading.Thread(target=generator.generate, args=(resource_id,))
    thread.start()
    return {"status": "accepted", "message": "Patch plan generation started in background"}
