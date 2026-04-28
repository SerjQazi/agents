#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/git_helper.sh push "commit message"
  ./scripts/git_helper.sh branch "branch-name"
  ./scripts/git_helper.sh status
USAGE
}

require_git_repo() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Error: not inside a git repository" >&2
    exit 1
  fi
}

current_branch() {
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$branch" == "HEAD" ]]; then
    echo "Error: detached HEAD; switch to a branch before pushing" >&2
    exit 1
  fi
  printf '%s\n' "$branch"
}

remote_exists() {
  git remote get-url origin >/dev/null 2>&1
}

refuse_sensitive_paths() {
  local blocked
  blocked="$(
    git diff --cached --name-only | grep -E '(^|/)(\.env($|\.)|.*token.*|.*credential.*|.*secret.*|\.venv/|venv/|env/)' || true
  )"

  if [[ -n "$blocked" ]]; then
    echo "Refusing to commit likely secrets, credentials, or virtualenv files:" >&2
    printf '%s\n' "$blocked" >&2
    echo "Unstage/remove those files before pushing." >&2
    exit 1
  fi
}

cmd_status() {
  require_git_repo
  echo "Current branch:"
  current_branch
  echo
  echo "Status:"
  git status --short
  echo
  echo "Remotes:"
  git remote -v
}

cmd_push() {
  require_git_repo

  if ! remote_exists; then
    echo "Error: remote 'origin' is not configured" >&2
    exit 1
  fi

  local branch message
  branch="$(current_branch)"
  message="${1:-Agent update}"

  echo "Current branch: $branch"
  echo
  git status
  echo
  echo "Changed files:"
  git status --short
  echo

  git add -A

  if git diff --cached --quiet; then
    echo "No changes to commit"
  else
    refuse_sensitive_paths
    git commit -m "$message"
  fi

  if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    git push origin "$branch"
  else
    git push -u origin "$branch"
  fi
}

validate_branch_name() {
  local branch="${1:-}"

  if [[ -z "$branch" ]]; then
    echo "Error: branch name cannot be empty" >&2
    exit 1
  fi

  if [[ "$branch" =~ [[:space:]] ]]; then
    echo "Error: branch name cannot contain spaces" >&2
    exit 1
  fi

  branch="${branch#refs/heads/}"

  if ! git check-ref-format --branch "$branch" >/dev/null 2>&1; then
    echo "Error: invalid branch name: $branch" >&2
    exit 1
  fi

  printf '%s\n' "$branch"
}

cmd_branch() {
  require_git_repo

  if [[ "$#" -ne 1 ]]; then
    echo "Error: provide exactly one branch name" >&2
    exit 1
  fi

  local branch
  branch="$(validate_branch_name "${1:-}")"

  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git checkout "$branch"
    return
  fi

  if remote_exists && git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    git checkout --track "origin/$branch"
    return
  fi

  git checkout -b "$branch"
}

main() {
  local command="${1:-}"
  shift || true

  case "$command" in
    push)
      cmd_push "${*:-Agent update}"
      ;;
    branch)
      cmd_branch "$@"
      ;;
    status)
      cmd_status
      ;;
    ""|-h|--help|help)
      usage
      ;;
    *)
      echo "Error: unknown command: $command" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
