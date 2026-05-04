"""Read-only folder scanner for coding_agent."""

from __future__ import annotations

from pathlib import Path


def scan_folder(path: str | Path) -> list[str]:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if root.is_file():
        return [str(root)]
    return [str(item) for item in sorted(root.rglob("*")) if item.is_file()]
