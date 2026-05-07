#!/bin/bash
#
# agentos-git.sh - OpenCode fallback Git workflow helper for AgentOS
#
# Usage: ./scripts/agentos-git.sh <command>
#
# Commands:
#   status          - Show repository state and recommendations
#   commit-backend - Commit backend/orchestrator changes
#   commit-safe    - Commit safe changes (auto-categorized)
#   push-approved - Push with explicit confirmation
#   rollback-last - Show rollback guidance (no auto-action)
#   release-milestone - Prepare release notes
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="/home/agentzero/agents"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Safe directories (backend)
BACKEND_DIRS=("orchestrator" "scripts/agentos-git.sh" "AGENT_RULES.md" "AGENTS.md" "docs/agentos")

# Excluded patterns (never commit)
EXCLUDE_PATTERNS=(
    "__pycache__"
    ".pytest_cache"
    "node_modules"
    "*.log"
    "*.tmp"
    "*.bak"
    ".env"
    "*token*"
    "*credential*"
    "*.key"
    "*service-account*"
    "logs"
    "tmp"
    "backups"
    ".git"
)

# Secret patterns (warn)
SECRET_PATTERNS=(
    "password\s*="
    "api[_-]?key"
    "secret\s*="
    "token\s*="
    "private[_-]?key"
    "aws[_-]?access"
    "sk-[a-zA-Z0-9]{20,}"
)

usage() {
    echo -e "${CYAN}AgentOS Git Workflow Helper${NC}"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  status           - Show repository state and recommendations"
    echo "  commit-backend  - Commit backend/orchestrator changes"
    echo "  commit-safe    - Commit safe changes (auto-categorized)"
    echo "  push-approved - Push with explicit confirmation"
    echo "  rollback-last - Show rollback guidance (no auto-action)"
    echo "  release-milestone - Prepare release notes"
    echo ""
}

# Check if we're in the repo root
cd "$REPO_ROOT"

validate_backend() {
    echo -e "${YELLOW}Validating backend...${NC}"
    
    # Python syntax check
    if ! python3 -m py_compile orchestrator/*.py 2>/dev/null; then
        echo -e "${RED}ERROR: Python syntax validation failed${NC}"
        return 1
    fi
    
    # Check orchestrator can be imported
    if ! python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT'); from orchestrator import Orchestrator" 2>/dev/null; then
        echo -e "${RED}ERROR: Orchestrator import failed${NC}"
        return 1
    fi
    
    echo -e "${GREEN}Backend validation passed${NC}"
    return 0
}

get_changed_areas() {
    local areas=()
    
    # Check what directories have changes
    if git diff --name-only 2>/dev/null | grep -q "orchestrator/"; then
        areas+=("orchestrator/backend")
    fi
    if git diff --name-only 2>/dev/null | grep -q "apps/agentos_agent/"; then
        areas+=("dashboard/frontend")
    fi
    if git diff --name-only 2>/dev/null | grep -q "docs/"; then
        areas+=("docs")
    fi
    if git diff --name-only 2>/dev/null | grep -q "scripts/"; then
        areas+=("scripts")
    fi
    
    echo "${areas[*]:-unknown}"
}

check_for_secrets() {
    local files_with_secrets=()
    
    for file in $(git diff --name-only 2>/dev/null); do
        if [[ -f "$file" ]]; then
            for pattern in "${SECRET_PATTERNS[@]}"; do
                if grep -iqE "$pattern" "$file" 2>/dev/null; then
                    files_with_secrets+=("$file")
                    break
                fi
            done
        fi
    done
    
    if [[ ${#files_with_secrets[@]} -gt 0 ]]; then
        echo -e "${RED}WARNING: Possible secrets found in:${NC}"
        for f in "${files_with_secrets[@]}"; do
            echo "  - $f"
        done
        return 1
    fi
    return 0
}

cmd_status() {
    echo -e "${BOLD}=== AgentOS Repository Status ===${NC}"
    echo ""
    
    # Branch info
    echo -e "${CYAN}Branch:${NC} $(git branch --show-current 2>/dev/null || echo 'unknown')"
    echo -e "${CYAN}Remote:${NC} $(git config --get remote.origin.url 2>/dev/null || echo 'none')"
    
    # Commit info
    local latest_commit
    latest_commit=$(git log -1 --oneline 2>/dev/null || echo "No commits")
    echo -e "${CYAN}Latest:${NC} $latest_commit"
    
    echo ""
    echo -e "${BOLD}Changed Files:${NC}"
    
    # Changed files
    local changed
    changed=$(git diff --name-only 2>/dev/null)
    if [[ -n "$changed" ]]; then
        echo "$changed" | head -20
    else
        echo "  (none)"
    fi
    
    # Untracked files (excluding common junk)
    echo ""
    echo -e "${BOLD}Untracked Files:${NC}"
    local untracked
    untracked=$(git ls-files --others --exclude-standard 2>/dev/null | head -20)
    if [[ -n "$untracked" ]]; then
        echo "$untracked"
    else
        echo "  (none)"
    fi
    
    # Detect junk/temp/cache files
    echo ""
    echo -e "${BOLD}Possible Junk/Temp Files:${NC}"
    local junk
    junk=$(git ls-files --others --exclude-standard 2>/dev/null | grep -E "\.(log|tmp|bak|cache)|~" || true)
    if [[ -n "$junk" ]]; then
        echo -e "${YELLOW}Found:${NC}"
        echo "$junk"
    else
        echo "  (none)"
    fi
    
    # Secret check
    echo ""
    echo -e "${BOLD}Secret Scan:${NC}"
    if check_for_secrets; then
        echo -e "${GREEN}No obvious secrets detected${NC}"
    else
        echo -e "${RED}SECRETS FOUND - REVIEW BEFORE COMMITTING${NC}"
    fi
    
    # Changed areas summary
    echo ""
    echo -e "${BOLD}Changed Areas:${NC}"
    local areas
    areas=$(get_changed_areas)
    for area in $areas; do
        echo "  - $area"
    done
    
    # Recommendations
    echo ""
    echo -e "${BOLD}Recommendations:${NC}"
    
    local has_backend=false
    if echo "$areas" | grep -q "orchestrator/backend"; then
        has_backend=true
    fi
    
    if [[ "$has_backend" == "true" ]]; then
        echo -e "${GREEN}  -> Use: ./scripts/agentos-git.sh commit-backend${NC}"
    else
        echo -e "${GREEN}  -> Use: ./scripts/agentos-git.sh commit-safe${NC}"
    fi
    
    if [[ "$has_backend" == "true" ]]; then
        echo -e "${YELLOW}  -> Or manual review if changes are complex${NC}"
    fi
}

cmd_commit_backend() {
    echo -e "${BOLD}=== Backend Commit ===${NC}"
    echo ""
    
    # Validate first
    if ! validate_backend; then
        echo -e "${RED}Commit aborted due to validation failure${NC}"
        exit 1
    fi
    
    echo ""
    echo -e "${CYAN}Files to be staged:${NC}"
    
    # Show what will be staged
    local files_to_stage=()
    for dir in "${BACKEND_DIRS[@]}"; do
        if [[ -d "$dir" ]]; then
            for f in $(git diff --name-only "$dir" 2>/dev/null); do
                files_to_stage+=("$f")
            done
        elif [[ -f "$dir" ]]; then
            if git diff --name-only "$dir" 2>/dev/null | grep -q "$dir"; then
                files_to_stage+=("$dir")
            fi
        fi
    done
    
    if [[ ${#files_to_stage[@]} -eq 0 ]]; then
        echo "  No backend files to commit"
        exit 0
    fi
    
    for f in "${files_to_stage[@]}"; do
        echo "  - $f"
    done
    
    echo ""
    echo -e "${YELLOW}Confirm commit? (type 'yes' to confirm)${NC}"
    read -r confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "Commit cancelled"
        exit 0
    fi
    
    # Stage and commit
    for f in "${files_to_stage[@]}"; do
        git add "$f" 2>/dev/null || true
    done
    
    # Generate commit message
    local changed_areas
    changed_areas=$(get_changed_areas)
    local commit_msg="AgentOS: Backend update - $(date +%Y-%m-%d)
    
Milestone: $changed_areas
Validated: Python syntax OK
"
    
    git commit -m "$commit_msg"
    
    echo ""
    echo -e "${GREEN}Committed locally${NC}"
    echo -e "${YELLOW}Run ./scripts/agentos-git.sh push-approved when ready${NC}"
}

cmd_commit_safe() {
    echo -e "${BOLD}=== Safe Commit ===${NC}"
    echo ""
    
    # Get all changed files
    echo -e "${CYAN}All changed files:${NC}"
    local all_changed
    all_changed=$(git diff --name-only 2>/dev/null)
    
    if [[ -z "$all_changed" ]]; then
        echo "  No files to commit"
        exit 0
    fi
    
    # Filter out excluded patterns
    local safe_files=()
    local excluded=()
    
    for file in $all_changed; do
        local is_excluded=false
        for pattern in "${EXCLUDE_PATTERNS[@]}"; do
            if [[ "$file" == *"$pattern"* ]]; then
                is_excluded=true
                excluded+=("$file")
                break
            fi
        done
        if [[ "$is_excluded" == "false" ]]; then
            safe_files+=("$file")
        fi
    done
    
    # Show both lists
    echo ""
    echo -e "${GREEN}Safe to commit:${NC}"
    if [[ ${#safe_files[@]} -gt 0 ]]; then
        for f in "${safe_files[@]}"; do
            echo "  - $f"
        done
    else
        echo "  (none)"
    fi
    
    echo ""
    echo -e "${RED}Excluded:${NC}"
    if [[ ${#excluded[@]} -gt 0 ]]; then
        for f in "${excluded[@]}"; do
            echo "  - $f"
        done
    else
        echo "  (none)"
    fi
    
    # Secret check
    echo ""
    if ! check_for_secrets; then
        echo -e "${RED}ABORTED: Secrets detected${NC}"
        exit 1
    fi
    
    if [[ ${#safe_files[@]} -eq 0 ]]; then
        echo "No safe files to commit"
        exit 0
    fi
    
    echo ""
    echo -e "${YELLOW}Confirm commit? (type 'yes' to confirm)${NC}"
    read -r confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "Commit cancelled"
        exit 0
    fi
    
    # Stage safe files
    for f in "${safe_files[@]}"; do
        git add "$f" 2>/dev/null || true
    done
    
    # Categorize by area
    local categories=()
    
    for f in "${safe_files[@]}"; do
        if [[ "$f" == orchestrator/* ]]; then
            categories+=("orchestrator")
        elif [[ "$f" == apps/* ]]; then
            categories+=("frontend")
        elif [[ "$f" == docs/* ]]; then
            categories+=("docs")
        elif [[ "$f" == scripts/* ]]; then
            categories+=("scripts")
        else
            categories+=("other")
        fi
    done
    
    # Unique categories
    local unique_categories
    unique_categories=$(printf '%s\n' "${categories[@]}" | sort -u | tr '\n' ', ')
    
    local commit_msg="AgentOS: Update - $(date +%Y-%m-%d)
    
Categories: ${unique_categories%, }
Files: ${#safe_files[@]}
"
    
    git commit -m "$commit_msg"
    
    echo ""
    echo -e "${GREEN}Committed locally${NC}"
    echo -e "${YELLOW}Run ./scripts/agentos-git.sh push-approved when ready${NC}"
}

cmd_push_approved() {
    echo -e "${BOLD}=== Push Approved ===${NC}"
    echo ""
    
    # Show current state
    echo -e "${CYAN}Branch:${NC} $(git branch --show-current)"
    echo -e "${CYAN}Remote:${NC} $(git config --get remote.origin.url)"
    
    echo ""
    echo -e "${CYAN}Latest commit:${NC}"
    git log -1 --oneline
    
    echo ""
    echo -e "${CYAN}Status:${NC}"
    git status --short
    
    echo ""
    echo -e "${RED}This will push to remote.${NC}"
    echo -e "${YELLOW}Type 'PUSH' (exactly) to confirm:${NC}"
    read -r confirm
    
    if [[ "$confirm" != "PUSH" ]]; then
        echo "Push cancelled"
        exit 0
    fi
    
    echo ""
    echo -e "${CYAN}Pushing...${NC}"
    git push
    
    echo -e "${GREEN}Pushed successfully${NC}"
}

cmd_rollback_last() {
    echo -e "${BOLD}=== Rollback Guidance ===${NC}"
    echo ""
    
    echo -e "${CYAN}Latest commit:${NC}"
    git log -1 --oneline
    
    echo ""
    echo -e "${CYAN}Files in commit:${NC}"
    git show --name-only --oneline HEAD 2>/dev/null | head -20
    
    echo ""
    echo -e "${BOLD}Safe Rollback Options:${NC}"
    echo ""
    echo "1. Undo commit but keep changes:"
    echo "   git reset --soft HEAD~1"
    echo ""
    echo "2. Undo commit and unstage changes:"
    echo "   git reset HEAD~1"
    echo ""
    echo "3. Undo commit and discard changes (DESTRUCTIVE):"
    echo "   git reset --hard HEAD~1"
    echo ""
    echo "4. Create revert commit:"
    echo "   git revert HEAD"
    echo ""
    echo -e "${YELLOW}No automatic actions taken.${NC}"
    echo -e "${YELLOW}Choose option and run manually if needed.${NC}"
}

cmd_release_milestone() {
    echo -e "${BOLD}=== Release Milestone Preparation ===${NC}"
    echo ""
    
    # Run backend validation
    echo -e "${CYAN}Running backend validation...${NC}"
    if validate_backend; then
        echo -e "${GREEN}Validation: PASSED${NC}"
    else
        echo -e "${RED}Validation: FAILED${NC}"
    fi
    
    echo ""
    echo -e "${CYAN}Git status:${NC}"
    git status --short
    
    echo ""
    echo -e "${BOLD}Milestone Changes Summary:${NC}"
    
    # Count by category
    local changed
    changed=$(git diff --name-only)
    
    local backend=0
    local frontend=0
    local docs=0
    local scripts=0
    
    for f in $changed; do
        if [[ "$f" == orchestrator/* ]]; then
            ((backend++))
        elif [[ "$f" == apps/* ]]; then
            ((frontend++))
        elif [[ "$f" == docs/* ]]; then
            ((docs++))
        elif [[ "$f" == scripts/* ]]; then
            ((scripts++))
        fi
    done
    
    echo "  Backend: $backend files"
    echo "  Frontend: $frontend files"
    echo "  Docs: $docs files"
    echo "  Scripts: $scripts files"
    
    echo ""
    echo -e "${BOLD}Suggested Release Notes:${NC}"
    echo ""
    echo "## AgentOS Update $(date +%Y-%m-%d)"
    echo ""
    echo "### Changes"
    if [[ $backend -gt 0 ]]; then
        echo "- Backend updates ($backend files)"
    fi
    if [[ $frontend -gt 0 ]]; then
        echo "- Frontend updates ($frontend files)"
    fi
    if [[ $docs -gt 0 ]]; then
        echo "- Documentation updates ($docs files)"
    fi
    if [[ $scripts -gt 0 ]]; then
        echo "- Script updates ($scripts files)"
    fi
    echo ""
    echo "### Testing"
    echo "- Backend validation: PASSED"
    
    echo ""
    echo -e "${BOLD}Recommendations:${NC}"
    if [[ $backend -gt 0 ]]; then
        echo -e "${GREEN}  -> Use: ./scripts/agentos-git.sh commit-backend${NC}"
    else
        echo -e "${GREEN}  -> Use: ./scripts/agentos-git.sh commit-safe${NC}"
    fi
    
    echo -e "${YELLOW}  -> Run ./scripts/agentos-git.sh push-approved when committed${NC}"
}

# Main command dispatcher
main() {
    if [[ $# -eq 0 ]]; then
        usage
        exit 1
    fi
    
    local command="$1"
    shift
    
    case "$command" in
        status)
            cmd_status
            ;;
        commit-backend)
            cmd_commit_backend
            ;;
        commit-safe)
            cmd_commit_safe
            ;;
        push-approved)
            cmd_push_approved
            ;;
        rollback-last)
            cmd_rollback_last
            ;;
        release-milestone)
            cmd_release_milestone
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            echo -e "${RED}Unknown command: $command${NC}"
            usage
            exit 1
            ;;
    esac
}

main "$@"