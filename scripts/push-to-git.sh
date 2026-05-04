#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/agentzero/agents"

cd "$REPO_DIR"

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "HEAD" ]]; then
  echo "Error: detached HEAD; switch to a branch before pushing" >&2
  exit 1
fi

echo "Repository: $REPO_DIR"
echo "Branch: $branch"
echo
git status
echo

git add -A

if git diff --cached --quiet; then
  echo "No changes to commit."
else
  blocked="$(
    git diff --cached --name-only |
      grep -Ei '(^|/)(\.env($|\.)|.*token.*|.*credential.*|.*secret.*|\.venv/|venv/|env/)' || true
  )"
  if [[ -n "$blocked" ]]; then
    echo "Refusing to commit likely secrets, credentials, or virtualenv files:" >&2
    printf '%s\n' "$blocked" >&2
    exit 1
  fi

  mapfile -t changed_files < <(git diff --cached --name-only)
  mapfile -t top_level_areas < <(
    printf '%s\n' "${changed_files[@]}" |
      awk -F/ '{ print $1 }' |
      sort -u
  )

  echo "Changed top-level areas:"
  for area in "${top_level_areas[@]}"; do
    echo "- $area"
  done
  echo

  timestamp="$(date -u +%Y%m%d-%H%M%S)"
  commit_message="chore: update agent tooling ${timestamp}"
  if [[ ${#top_level_areas[@]} -eq 1 && "${top_level_areas[0]}" == "scripts" ]]; then
    commit_message="chore: update git helper scripts ${timestamp}"
  fi

  echo "Commit message: $commit_message"
  git commit -m "$commit_message"
fi

if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
  git push origin "$branch"
else
  git push -u origin "$branch"
fi
echo
git status
