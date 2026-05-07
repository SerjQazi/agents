"""AgentOS Role Loader (Phase 1).

File-based role definitions for lightweight task routing. Role files are stored in
`orchestrator/roles/` and are expected to be JSON objects (YAML-compatible) even
if the filename ends in `.yaml`.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "description",
    "responsibilities",
    "preferred_model",
    "fallback_model",
    "cost_tier",
    "allowed_actions",
    "requires_approval_for",
    "inputs",
    "outputs",
    "validation_expectations",
    "handoff_to",
    "safety_notes",
)


@dataclass(frozen=True)
class RoleDefinition:
    id: str
    name: str
    description: str
    responsibilities: list[str]
    preferred_model: str
    fallback_model: str
    cost_tier: str
    allowed_actions: list[str]
    requires_approval_for: list[str]
    inputs: list[str]
    outputs: list[str]
    validation_expectations: list[str]
    handoff_to: list[str]
    safety_notes: list[str]
    source_path: str

    @staticmethod
    def from_dict(data: dict[str, Any], *, source_path: str) -> "RoleDefinition":
        missing = [k for k in REQUIRED_FIELDS if k not in data]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

        def _require_str(key: str) -> str:
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"field '{key}' must be a non-empty string")
            return value.strip()

        def _require_str_list(key: str) -> list[str]:
            value = data.get(key)
            if not isinstance(value, list) or not value:
                raise ValueError(f"field '{key}' must be a non-empty list of strings")
            out: list[str] = []
            for i, item in enumerate(value):
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(f"field '{key}[{i}]' must be a non-empty string")
                out.append(item.strip())
            return out

        return RoleDefinition(
            id=_require_str("id"),
            name=_require_str("name"),
            description=_require_str("description"),
            responsibilities=_require_str_list("responsibilities"),
            preferred_model=_require_str("preferred_model"),
            fallback_model=_require_str("fallback_model"),
            cost_tier=_require_str("cost_tier"),
            allowed_actions=_require_str_list("allowed_actions"),
            requires_approval_for=_require_str_list("requires_approval_for"),
            inputs=_require_str_list("inputs"),
            outputs=_require_str_list("outputs"),
            validation_expectations=_require_str_list("validation_expectations"),
            handoff_to=_require_str_list("handoff_to"),
            safety_notes=_require_str_list("safety_notes"),
            source_path=source_path,
        )


@dataclass(frozen=True)
class RoleLoadError:
    path: str
    error: str


@dataclass(frozen=True)
class RoleRecommendation:
    role_id: str
    score: float
    reason: str


class RoleLoader:
    def __init__(self, roles_dir: str | Path | None = None):
        if roles_dir is None:
            roles_dir = Path(__file__).resolve().parent / "roles"
        self.roles_dir = Path(roles_dir)
        self._roles: dict[str, RoleDefinition] = {}
        self._errors: list[RoleLoadError] = []

    def load_all(self, *, strict: bool = False) -> tuple[dict[str, RoleDefinition], list[RoleLoadError]]:
        self._roles = {}
        self._errors = []

        if not self.roles_dir.exists():
            err = RoleLoadError(path=str(self.roles_dir), error="roles directory not found")
            if strict:
                raise ValueError(err.error)
            self._errors.append(err)
            return self._roles, self._errors

        for path in sorted(self._iter_role_files(self.roles_dir)):
            try:
                role_dict = self._load_role_file(path)
                role = RoleDefinition.from_dict(role_dict, source_path=str(path))
                if role.id in self._roles:
                    raise ValueError(f"duplicate role id '{role.id}'")
                self._roles[role.id] = role
            except Exception as e:  # noqa: BLE001 (intentional: surface parsing/validation errors)
                self._errors.append(RoleLoadError(path=str(path), error=str(e)))
                if strict:
                    raise

        return self._roles, self._errors

    def list_roles(self) -> list[RoleDefinition]:
        if not self._roles and not self._errors:
            self.load_all(strict=False)
        return list(self._roles.values())

    def get_role(self, role_id: str) -> RoleDefinition | None:
        if not self._roles and not self._errors:
            self.load_all(strict=False)
        return self._roles.get(role_id)

    def recommend_role(self, task_description: str) -> RoleRecommendation | None:
        """Lightweight keyword-based role recommendation.

        Returns a recommendation with a 0..1 score, or None if no roles are loaded.
        """
        if not self._roles and not self._errors:
            self.load_all(strict=False)
        if not self._roles:
            return None

        desc = (task_description or "").lower()
        if not desc.strip():
            return None

        scored: list[tuple[float, str, str]] = []
        for role in self._roles.values():
            haystack = " ".join(
                [
                    role.id,
                    role.name,
                    role.description,
                    " ".join(role.responsibilities),
                ]
            ).lower()
            score = self._score_text_match(desc, haystack)
            if score > 0:
                scored.append((score, role.id, f"matched keywords against {role.id}"))

        if not scored:
            return None

        scored.sort(reverse=True, key=lambda t: t[0])
        top_score, top_role_id, reason = scored[0]

        # Normalize into a small-ish range; keep it conservative.
        normalized = min(1.0, max(0.1, top_score))
        return RoleRecommendation(role_id=top_role_id, score=normalized, reason=reason)

    @staticmethod
    def _iter_role_files(roles_dir: Path) -> Iterable[Path]:
        for ext in (".yaml", ".yml", ".json"):
            yield from roles_dir.glob(f"*{ext}")

    @staticmethod
    def _load_role_file(path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8")
        raw = raw.strip()
        if not raw:
            raise ValueError("empty role file")

        # Phase 1: keep dependencies at zero by requiring JSON content.
        # JSON is valid YAML 1.2, so `.yaml` files can contain pure JSON safely.
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(
                "role files must contain JSON objects (YAML-compatible JSON). "
                f"JSON parse error: {e.msg} at line {e.lineno} col {e.colno}"
            ) from e

        if not isinstance(data, dict):
            raise ValueError("role file root must be a JSON object")
        return data

    @staticmethod
    def _score_text_match(needle: str, haystack: str) -> float:
        # Very small heuristic: count distinct keyword hits.
        tokens = [t for t in _tokenize(needle) if len(t) >= 4]
        if not tokens:
            return 0.0
        hits = sum(1 for t in set(tokens) if t in haystack)
        return hits / max(3.0, float(len(set(tokens))))


def _tokenize(text: str) -> list[str]:
    # No regex dependency; keep it simple and predictable.
    out: list[str] = []
    current: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ch in ("_", "-"):
            current.append(ch)
        else:
            if current:
                out.append("".join(current))
                current = []
    if current:
        out.append("".join(current))
    return out


def validate_roles(roles_dir: str | Path | None = None) -> tuple[list[RoleDefinition], list[RoleLoadError]]:
    loader = RoleLoader(roles_dir=roles_dir)
    roles_map, errors = loader.load_all(strict=False)
    roles = list(roles_map.values())
    roles.sort(key=lambda r: r.id)
    return roles, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentOS role loader/validator (Phase 1)")
    parser.add_argument(
        "--roles-dir",
        default=None,
        help="Override roles directory (defaults to orchestrator/roles/ next to this file)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate and print loaded roles",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List role ids",
    )
    parser.add_argument(
        "--recommend",
        default=None,
        help="Recommend a role id for the given task description",
    )

    args = parser.parse_args(argv)

    loader = RoleLoader(roles_dir=args.roles_dir)
    roles_map, errors = loader.load_all(strict=False)

    if args.recommend:
        rec = loader.recommend_role(args.recommend)
        if not rec:
            print("No recommendation available (no roles loaded or no match).")
            return 2
        role = loader.get_role(rec.role_id)
        if role:
            print(f"{role.id} ({role.name}) score={rec.score:.2f} reason={rec.reason}")
        else:
            print(f"{rec.role_id} score={rec.score:.2f} reason={rec.reason}")
        return 0

    if args.list:
        for role_id in sorted(roles_map.keys()):
            print(role_id)
        if errors:
            print(f"\nErrors: {len(errors)} (run with --validate for details)")
        return 0 if not errors else 2

    if args.validate:
        print(f"Roles dir: {loader.roles_dir}")
        print(f"Loaded roles: {len(roles_map)}")
        for role_id in sorted(roles_map.keys()):
            role = roles_map[role_id]
            print(f"- {role.id}: {role.name} ({role.cost_tier}) preferred={role.preferred_model}")

        if errors:
            print("\nRole file errors:")
            for e in errors:
                print(f"- {e.path}: {e.error}")
            return 2
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

