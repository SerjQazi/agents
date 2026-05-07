"""AgentOS Step Router - Routes steps to recommended tools/models."""

import os
import re
from pathlib import Path
from typing import Any

from orchestrator.models import (
    Step,
    ToolType,
    RiskLevel,
    StepStatus,
)


COST_STRATEGY = {
    ToolType.GEMINI: {
        "name": "Gemini",
        "purpose": "Planning & Architecture",
        "cost_tier": "low",
        "best_for": [
            "initial project scaffolding",
            "architecture design",
            "planning tasks",
            "project structure definition",
            "interface planning",
        ],
    },
    ToolType.OPENCODE: {
        "name": "OpenCode",
        "purpose": "Bulk Implementation",
        "cost_tier": "medium",
        "best_for": [
            "code generation",
            "feature development",
            "refactoring",
            "bulk implementation",
            "file creation",
        ],
    },
    ToolType.CODEX: {
        "name": "Codex",
        "purpose": "Final Review & Surgical Fixes",
        "cost_tier": "high",
        "best_for": [
            "complex problem solving",
            "surgical code fixes",
            "final code review",
            "security audits",
            "performance optimization",
        ],
    },
    ToolType.OLLAMA: {
        "name": "Ollama/Local",
        "purpose": "Summaries & Lightweight Tasks",
        "cost_tier": "free",
        "best_for": [
            "log parsing",
            "summaries",
            "documentation review",
            "small code reviews",
            "offline tasks",
        ],
    },
    ToolType.LOCAL_SCRIPT: {
        "name": "Local Scripts",
        "purpose": "Git & Deploy Actions",
        "cost_tier": "free",
        "best_for": [
            "git operations",
            "deploy scripts",
            "file operations",
            "service management",
            "shell commands",
        ],
    },
    ToolType.MANUAL: {
        "name": "Manual",
        "purpose": "Human Actions Required",
        "cost_tier": "n/a",
        "best_for": [
            "approvals",
            "security decisions",
            "database changes",
            "production deployments",
            "sudo operations",
        ],
    },
}


class RulesLoader:
    """Load safety rules from AGENT_RULES.md"""

    def __init__(self, rules_path: str = "/home/agentzero/agents/AGENT_RULES.md"):
        self.rules_path = Path(rules_path)
        self.risk_patterns = {}
        self.prohibited_actions = []
        self.file_restrictions = {}
        self._load_rules()

    def _load_rules(self) -> None:
        if not self.rules_path.exists():
            self._use_default_patterns()
            return

        content = self.rules_path.read_text()

        current_level = None
        for line in content.split("\n"):
            line = line.strip()

            if line.startswith("### Critical"):
                current_level = RiskLevel.CRITICAL
                self.risk_patterns[RiskLevel.CRITICAL] = []
            elif line.startswith("### High"):
                current_level = RiskLevel.HIGH
                self.risk_patterns[RiskLevel.HIGH] = []
            elif line.startswith("### Medium"):
                current_level = RiskLevel.MEDIUM
                self.risk_patterns[RiskLevel.MEDIUM] = []
            elif line.startswith("### Low"):
                current_level = RiskLevel.LOW
                self.risk_patterns[RiskLevel.LOW] = []
            elif line.startswith("### Safe"):
                current_level = RiskLevel.SAFE
                self.risk_patterns[RiskLevel.SAFE] = []
            elif line.startswith("- `") and current_level:
                pattern_line = line.replace("- `", "").replace("`", "").strip()
                for pattern in pattern_line.split(","):
                    p = pattern.strip()
                    if p:
                        self.risk_patterns[current_level].append(p)

            if "Prohibited Actions" in line:
                self._extract_prohibited(content)

    def _extract_prohibited(self, content: str) -> None:
        in_prohibited = False
        for line in content.split("\n"):
            if "Prohibited Actions" in line:
                in_prohibited = True
                continue
            if in_prohibited:
                if line.startswith("##") or not line.strip():
                    break
                if "`" in line:
                    action = line.strip().replace("`", "").rstrip(".")
                    self.prohibited_actions.append(action)

    def _use_default_patterns(self) -> None:
        self.risk_patterns = {
            RiskLevel.CRITICAL: [
                "sudo",
                "rm -rf",
                "drop database",
                "systemctl restart",
                "curl | bash",
            ],
            RiskLevel.HIGH: [
                "push",
                "git push",
                "deploy",
                "restart service",
                "install package",
                "modify database",
                "restart server",
            ],
            RiskLevel.MEDIUM: [
                "delete file",
                "rename file",
                "create directory",
                "modify git",
                "run script",
                "execute command",
                "curl",
            ],
            RiskLevel.LOW: [
                "create file",
                "modify file",
                "add configuration",
                "update existing code",
                "write file",
            ],
            RiskLevel.SAFE: [
                "read file",
                "list directory",
                "search code",
                "generate plan",
                "validate syntax",
                "create report",
                "analyze",
                "check",
                "scan",
            ],
        }

    def get_patterns(self) -> dict:
        return self.risk_patterns

    def get_prohibited(self) -> list[str]:
        return self.prohibited_actions


class StepRouter:
    def __init__(self, rules_path: str = "/home/agentzero/agents/AGENT_RULES.md"):
        self.strategy = COST_STRATEGY
        self.rules_loader = RulesLoader(rules_path)
        self.risk_patterns = self.rules_loader.get_patterns()

    def route_step(self, step_name: str, step_description: str, context: dict = None) -> Step:
        context = context or {}
        description_lower = f"{step_name} {step_description}".lower()

        tool = self._infer_tool(description_lower, context)
        risk = self._assess_risk(description_lower)
        purpose = self.strategy[tool]["purpose"]
        cost = self.strategy[tool]["cost_tier"]

        return Step(
            name=step_name,
            description=step_description,
            tool=tool,
            purpose=purpose,
            risk_level=risk,
            status=StepStatus.PENDING,
            cost_estimate=cost,
        )

    def _infer_tool(self, description: str, context: dict) -> ToolType:
        desc = description.lower()

        for pattern in self.strategy[ToolType.GEMINI]["best_for"]:
            if pattern in desc:
                return ToolType.GEMINI

        for pattern in self.strategy[ToolType.OPENCODE]["best_for"]:
            if pattern in desc:
                return ToolType.OPENCODE

        for pattern in self.strategy[ToolType.CODEX]["best_for"]:
            if pattern in desc:
                return ToolType.CODEX

        for pattern in self.strategy[ToolType.OLLAMA]["best_for"]:
            if pattern in desc:
                return ToolType.OLLAMA

        for pattern in self.strategy[ToolType.LOCAL_SCRIPT]["best_for"]:
            if pattern in desc:
                return ToolType.LOCAL_SCRIPT

        if context.get("requires_approval"):
            return ToolType.MANUAL

        return ToolType.OPENCODE

    def _assess_risk(self, description: str) -> RiskLevel:
        for risk_level, patterns in self.risk_patterns.items():
            for pattern in patterns:
                if pattern in description:
                    return risk_level
        return RiskLevel.SAFE

    def get_strategy_info(self, tool: ToolType) -> dict:
        return self.strategy.get(tool, {})

    def requires_approval(self, step) -> bool:
        return step.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

    def get_all_strategies(self) -> dict:
        return self.strategy

    def reload_rules(self) -> None:
        """Reload rules from AGENT_RULES.md"""
        self.rules_loader = RulesLoader()
        self.risk_patterns = self.rules_loader.get_patterns()