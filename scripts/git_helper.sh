#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/git_helper.sh repo-status
  ./scripts/git_helper.sh commit-backend
  ./scripts/git_helper.sh commit-safe
  ./scripts/git_helper.sh push-approved [--yes] [--by "name"] [--reason "text"]
  ./scripts/git_helper.sh rollback-last
  ./scripts/git_helper.sh release-milestone

Legacy:
  ./scripts/git_helper.sh push "commit message"     (deprecated; does not push)
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

is_tty() {
  [[ -t 0 && -t 1 ]]
}

confirm_or_exit() {
  local prompt="${1:-Are you sure? Type YES to continue: }"
  local answer

  if ! is_tty; then
    echo "Error: confirmation requires an interactive TTY. Re-run with --yes if you really intend it." >&2
    exit 1
  fi

  read -r -p "$prompt" answer
  if [[ "$answer" != "YES" ]]; then
    echo "Aborted." >&2
    exit 1
  fi
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

detect_possible_secrets() {
  local candidates
  candidates="$(
    git status --porcelain | awk '{print $2}' | grep -E '(^|/)(\.env($|\.)|.*token.*|.*credential.*|.*secret.*|id_rsa|id_ed25519|\.pem$|\.p12$|\.key$)' || true
  )"
  if [[ -n "$candidates" ]]; then
    echo "Possible secrets detected in working tree (review before staging/committing):"
    printf '%s\n' "$candidates"
    echo
  fi
}

detect_junk() {
  local junk
  junk="$(
    git status --porcelain | awk '{print $2}' | grep -E '(^|/)(__pycache__/|\.pytest_cache/|\.mypy_cache/|\.ruff_cache/|\.DS_Store$|node_modules/|dist/|build/|\.venv/|venv/|env/|\.coverage$|.*\.pyc$)' || true
  )"
  if [[ -n "$junk" ]]; then
    echo "Junk/temp/cache files detected (should not be committed):"
    printf '%s\n' "$junk"
    echo
  fi
}

summarize_by_area() {
  local files
  files="$(git status --porcelain | awk '{print $2}' || true)"

  echo "Change summary:"
  echo

  echo "  Orchestrator/backend:"
  echo "$files" | grep -E '^(orchestrator/|core/|agent_core/|apps/(planner_agent|builder_agent|coding_agent|agentos_agent)/)' || echo "  (none)"
  echo

  echo "  Frontend/UI:"
  echo "$files" | grep -E '^(apps/|extensions/|scripts/|docs/.*ui|.*\.css$|.*\.js$|.*\.tsx?$|.*\.vue$)' || echo "  (none)"
  echo

  echo "  Docs/Other:"
  echo "$files" | grep -Ev '^(orchestrator/|core/|agent_core/|apps/(planner_agent|builder_agent|coding_agent|agentos_agent)/|apps/|extensions/|scripts/|docs/.*ui|.*\.css$|.*\.js$|.*\.tsx?$|.*\.vue$)' || echo "  (none)"
  echo
}

recommend_grouping() {
  echo "Recommended commit grouping:"
  echo "  1) Orchestrator/backend changes (orchestrator/, core/, agent_core/)"
  echo "  2) Frontend/UI changes (apps/, extensions/, scripts/)"
  echo "  3) Docs changes (docs/)"
  echo
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

cmd_repo_status() {
  require_git_repo

  echo "Current branch:"
  current_branch
  echo

  echo "Changed + untracked files:"
  git status --porcelain
  echo

  detect_junk
  detect_possible_secrets
  summarize_by_area
  recommend_grouping
}

run_backend_validation() {
  echo "Running backend validation:"
  echo "  - python3 -m py_compile orchestrator/*.py orchestrator/execution/*.py"
  python3 -m py_compile orchestrator/*.py orchestrator/execution/*.py
  echo
  echo "  - python3 orchestrator/run.py test"
  python3 orchestrator/run.py test
  echo
}

stage_backend_only() {
  # Only stage orchestrator/backend files. Avoid -A to prevent accidental staging.
  # Exclude generated/persistent state folders.
  git reset -q
  git add -- \
    orchestrator \
    core \
    agent_core \
    apps/planner_agent \
    apps/builder_agent \
    apps/coding_agent \
    apps/agentos_agent \
    ':!orchestrator/tasks/' \
    ':!orchestrator/archive/' \
    ':!orchestrator/approvals/_queue.json' \
    2>/dev/null || true
}

stage_all_safe() {
  # Stage everything except known junk/cache and runtime state.
  # Use git pathspec excludes to avoid relying on shell globbing.
  git reset -q
  git add -A -- \
    . \
    ':!backups/' \
    ':!orchestrator/tasks/' \
    ':!orchestrator/archive/' \
    ':!orchestrator/approvals/_queue.json' \
    ':!**/__pycache__/' \
    ':!**/.pytest_cache/' \
    ':!**/.mypy_cache/' \
    ':!**/.ruff_cache/' \
    ':!**/.DS_Store' \
    ':!**/node_modules/' \
    ':!**/dist/' \
    ':!**/build/' \
    ':!**/.venv/' \
    ':!**/venv/' \
    ':!**/env/' \
    ':!**/*.pyc' \
    ':!tmp_*' \
    2>/dev/null || true
}

milestone_message() {
  local scope="${1:-AgentOS}"
  local summary
  summary="$(git diff --cached --name-only | head -n 20 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')"
  if [[ -z "$summary" ]]; then
    summary="no staged changes"
  fi
  printf '%s: %s\n\nFiles: %s\n' "$scope" "milestone update" "$summary"
}

cmd_commit_backend() {
  require_git_repo

  echo "=== repo status ==="
  cmd_repo_status

  echo "=== validate ==="
  run_backend_validation

  echo "=== stage (backend only) ==="
  stage_backend_only

  if git diff --cached --quiet; then
    echo "No backend/orchestrator changes staged. Nothing to commit."
    return 0
  fi

  refuse_sensitive_paths

  echo "=== summarize (staged) ==="
  git diff --cached --name-status
  echo

  local msg
  msg="$(milestone_message "Backend")"
  echo "Proposed commit message:"
  echo "------------------------"
  echo "$msg"
  echo "------------------------"

  if is_tty; then
    confirm_or_exit "Commit locally? Type YES to commit: "
  else
    echo "Error: commit-backend requires an interactive TTY for confirmation." >&2
    exit 1
  fi

  git commit -m "$(printf '%s\n' "$msg")"
  echo "Committed locally. Not pushed."
}

cmd_commit_safe() {
  require_git_repo

  echo "=== repo status ==="
  cmd_repo_status

  echo "=== stage (safe) ==="
  stage_all_safe

  if git diff --cached --quiet; then
    echo "No changes staged. Nothing to commit."
    return 0
  fi

  refuse_sensitive_paths

  echo "=== summarize (staged) ==="
  git diff --cached --name-status
  echo

  local msg
  msg="$(milestone_message "Repo")"
  echo "Proposed commit message:"
  echo "------------------------"
  echo "$msg"
  echo "------------------------"

  if is_tty; then
    confirm_or_exit "Commit locally? Type YES to commit: "
  else
    echo "Error: commit-safe requires an interactive TTY for confirmation." >&2
    exit 1
  fi

  git commit -m "$(printf '%s\n' "$msg")"
  echo "Committed locally. Not pushed."
}

cmd_push_approved() {
  require_git_repo

  if ! remote_exists; then
    echo "Error: remote 'origin' is not configured" >&2
    exit 1
  fi

  local yes="no"
  local decided_by="${USER:-unknown}"
  local reason=""

  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --yes)
        yes="yes"
        shift
        ;;
      --by)
        decided_by="${2:-$decided_by}"
        shift 2
        ;;
      --reason)
        reason="${2:-}"
        shift 2
        ;;
      *)
        echo "Error: unknown option: $1" >&2
        exit 1
        ;;
    esac
  done

  local branch
  branch="$(current_branch)"

  echo "Latest commit:"
  git --no-pager log -1 --stat
  echo
  echo "Branch + remote:"
  echo "  branch: $branch"
  echo "  origin: $(git remote get-url origin)"
  echo

  echo "Pre-push secret scan (staged only):"
  refuse_sensitive_paths

  if [[ "$yes" != "yes" ]]; then
    confirm_or_exit "Final confirmation required. Type YES to push: "
  fi

  echo "Pushing to origin/$branch ..."
  git push origin "$branch"
  echo "Pushed."
}

cmd_rollback_last() {
  require_git_repo
  echo "Rollback options (no automatic force reset):"
  echo
  echo "Latest commit:"
  git --no-pager log -1 --stat
  echo
  echo "Safe rollback strategies:"
  echo "  1) Revert commit (safe for shared branches):"
  echo "     git revert HEAD"
  echo "  2) Undo last commit but keep changes staged (local only):"
  echo "     git reset --soft HEAD~1"
  echo "  3) Undo last commit and unstage changes (local only):"
  echo "     git reset HEAD~1"
  echo
  echo "Affected files (from latest commit):"
  git --no-pager show --name-only --pretty=format: HEAD
}

cmd_release_milestone() {
  require_git_repo
  echo "=== architecture progress (lightweight) ==="
  echo "Latest commit:"
  git --no-pager log -1 --oneline
  echo
  echo "=== verify orchestrator integrity ==="
  run_backend_validation
  echo "=== prepare milestone commit (no push) ==="
  cmd_commit_backend
  echo
  echo "Release note stub (Phase 1):"
  echo "- Scope: AgentOS milestone"
  echo "- Summary: see latest commit and staged file list"
  echo
  echo "Waiting for explicit approval before any push."
}

cmd_push() {
  require_git_repo

  echo "Deprecated: 'push' no longer pushes automatically."
  echo "Use: ./scripts/git_helper.sh commit-safe (or commit-backend), then ./scripts/git_helper.sh push-approved"
  echo
  local message
  message="${1:-Agent update}"
  echo "Creating a local commit only (no push) with message: $message"
  git status --short
  git add -A
  if git diff --cached --quiet; then
    echo "No changes to commit"
    return 0
  fi
  refuse_sensitive_paths
  git commit -m "$message"
  echo "Committed locally. Not pushed."
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
    repo-status)
      cmd_repo_status
      ;;
    commit-backend)
      cmd_commit_backend
      ;;
    commit-safe)
      cmd_commit_safe
      ;;
    push-approved)
      cmd_push_approved "$@"
      ;;
    rollback-last)
      cmd_rollback_last
      ;;
    release-milestone)
      cmd_release_milestone
      ;;
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
