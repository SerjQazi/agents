#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/agentzero/agents"

cd "$REPO_DIR"

echo "Repository: $REPO_DIR"
echo
git status
echo

git add -A

if git diff --cached --quiet; then
  echo "No changes to commit."
else
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

  commit_message="chore: update agent tooling"
  if [[ ${#top_level_areas[@]} -eq 1 && "${top_level_areas[0]}" == "scripts" ]]; then
    commit_message="chore: update git helper scripts"
  fi

  echo "Commit message: $commit_message"
  git commit -m "$commit_message"
fi

git push
echo
git status
