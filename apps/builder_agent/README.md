# Builder Agent

Builder Agent is an isolated, local-only, plan-only MVP for FiveM script analysis
and adaptation planning.

It does not replace existing agents, does not modify FiveM resources, does not
run SQL, does not restart FiveM, and does not push Git.

## Run

```bash
cd /home/agentzero/agents
source .venv/bin/activate
uvicorn apps.builder_agent.app:app --host 127.0.0.1 --port 8010
```

Open:

```text
http://127.0.0.1:8010/
```

## Create A Plan-Only Task

```bash
curl -X POST http://127.0.0.1:8010/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Scan incoming script and tell me dependencies.","script_path":"incoming/qb-inventory-new"}'
```

## Storage

- Reports: `/home/agentzero/agents/reports/builder-agent/`
- Logs: `/home/agentzero/agents/logs/builder-agent/`
- Memory: `/home/agentzero/agents/memory/builder-agent-memory.sqlite`
