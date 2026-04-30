#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/agentzero/fivem-server/txData/QBCore_F16AC8.base/resources"

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

  commit_message="chore: update server resources"
  metadata_only=true
  for area in "${top_level_areas[@]}"; do
    if [[ "$area" != "README.md" && "$area" != ".gitignore" ]]; then
      metadata_only=false
      break
    fi
  done

  if [[ "$metadata_only" == true ]]; then
    commit_message="chore: update repo metadata"
  fi

  echo "Commit message: $commit_message"
  git commit -m "$commit_message"
fi

git push
echo
git status
