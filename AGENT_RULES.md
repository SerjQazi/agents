# AgentOS Safety Rules

This file defines the safety policies and permission rules for the AgentOS orchestrator.

## Permission Levels

| Level | Description | Requires Approval |
|-------|-------------|-------------------|
| SAFE | Read-only, analysis, validation | No |
| LOW | Create/modify files in /home/agentzero/agents | No |
| MEDIUM | Delete files, modify git state, run scripts | Yes |
| HIGH | Git push, deploy, restart services, install packages | Yes |
| CRITICAL | sudo, rm -rf, drop database, systemctl restart, curl\|bash | Yes + Manual |

## Prohibited Actions

The following actions are **NEVER** executed automatically and require explicit human approval:

- `sudo` commands
- `rm -rf` recursive deletes
- Database DROP/CREATE/ALTER operations
- `systemctl restart` or `systemctl stop` on critical services
- `curl | bash` or any remote script execution
- Direct git push to production branches (main, master, production)
- Package installation (`apt`, `pip`, `npm install -g`)
- Service restarts on live systems

## Allowed Actions (Auto-Approved in Dry-Run)

- File read operations
- Code analysis and syntax validation
- Project structure scanning
- Generating reports and summaries
- Creating local files in /home/agentzero/agents (non-destructive)
- Local script execution in dry-run mode (logged only)

## Cost Strategy

| Tool | Best For | Cost Tier |
|------|----------|-----------|
| Gemini | Planning, architecture, scaffolding | Low |
| OpenCode | Bulk implementation, feature development | Medium |
| Codex | Final review, surgical fixes, complex problems | High |
| Ollama/Local | Log parsing, summaries, lightweight tasks | Free |
| Local Scripts | Git operations, deploy actions, service checks | Free |

## Approval Workflow

1. **Task created** → Status: pending
2. **Plan generated** → Status: ready, shows steps with risk levels
3. **Preview execution** → Shows each step's tool, risk, files affected, approval needed
4. **Execute**:
   - SAFE/LOW risk → Auto-complete (or dry-run log)
   - MEDIUM/HIGH/CRITICAL → Pause → Status: paused, approval_required: true
5. **Human approval** → Step executes or is rejected
6. **Completion** → Status: completed

## Risk Detection Patterns

### Critical
- `sudo`, `rm -rf`, `drop database`, `systemctl restart`, `curl | bash`

### High
- `push`, `git push`, `deploy`, `restart service`, `install package`, `modify database`

### Medium
- `delete file`, `rename file`, `create directory`, `modify git`, `run script`, `execute command`

### Low
- `create file`, `modify file`, `add configuration`, `update existing code`, `write file`

### Safe
- `read file`, `list directory`, `search code`, `generate plan`, `validate syntax`, `analyze`, `check`, `scan`

## File Restrictions

- **Read allowed**: Anywhere in /home/agentzero/agents
- **Write allowed**: /home/agentzero/agents (except .env, secrets, credentials)
- **NEVER read/write**: Paths outside /home/agentzero/agents

## Update Policy

This rules file can be updated by human operators. Changes take effect on next orchestrator startup.