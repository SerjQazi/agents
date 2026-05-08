#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/agentzero/agents"
PROMPTS_DIR="$ROOT_DIR/orchestrator/prompts"
ARCHIVE_DIR="$PROMPTS_DIR/archive"

GEMINI_LATEST="$PROMPTS_DIR/gemini-plan-latest.md"
OPENCODE_LATEST="$PROMPTS_DIR/opencode-next.md"
CODEX_LATEST="$PROMPTS_DIR/codex-audit-next.md"

GEMINI_SRC=""
OPENCODE_SRC=""
CODEX_SRC=""

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/save-ai-cycle-prompts.sh [--gemini PLAN_FILE] [--opencode PROMPT_FILE] [--codex PROMPT_FILE]

Behavior:
  - Ensures orchestrator/prompts and orchestrator/prompts/archive exist
  - Ensures latest prompt files exist
  - Archives non-empty latest prompt files with timestamp suffix
  - Copies provided source files into latest prompt files
  - Prints next-step prompt file paths
USAGE
}

ensure_layout() {
  mkdir -p "$PROMPTS_DIR" "$ARCHIVE_DIR"
  touch "$GEMINI_LATEST" "$OPENCODE_LATEST" "$CODEX_LATEST"
}

archive_if_nonempty() {
  local src="$1"
  local ts="$2"
  if [[ -s "$src" ]]; then
    local base
    base="$(basename "$src" .md)"
    cp "$src" "$ARCHIVE_DIR/${base}-${ts}.md"
  fi
}

copy_if_set() {
  local src="$1"
  local dst="$2"
  if [[ -n "$src" ]]; then
    if [[ ! -f "$src" ]]; then
      echo "Error: source file not found: $src" >&2
      exit 1
    fi
    cp "$src" "$dst"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --gemini)
        GEMINI_SRC="${2:-}"
        shift 2
        ;;
      --opencode)
        OPENCODE_SRC="${2:-}"
        shift 2
        ;;
      --codex)
        CODEX_SRC="${2:-}"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Error: unknown argument: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
  done
}

main() {
  parse_args "$@"
  ensure_layout

  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"

  archive_if_nonempty "$GEMINI_LATEST" "$ts"
  archive_if_nonempty "$OPENCODE_LATEST" "$ts"
  archive_if_nonempty "$CODEX_LATEST" "$ts"

  copy_if_set "$GEMINI_SRC" "$GEMINI_LATEST"
  copy_if_set "$OPENCODE_SRC" "$OPENCODE_LATEST"
  copy_if_set "$CODEX_SRC" "$CODEX_LATEST"

  echo "Prompt handoff files ready:"
  echo "  Gemini plan:   $GEMINI_LATEST"
  echo "  OpenCode next: $OPENCODE_LATEST"
  echo "  Codex audit:   $CODEX_LATEST"
  echo "Archive folder:"
  echo "  $ARCHIVE_DIR"
}

main "$@"
