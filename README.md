# claw-bot-agents

Local agent prototypes and a clean FastAPI backend for an Ubuntu server.

The older prototype files `bubbles.py` and `mailman.py` are still present and
unchanged. The new backend lives in `agent_core/` with `api.py` as the FastAPI
entrypoint.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the backend

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Then open:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/system`
- `http://127.0.0.1:8000/agents`

## Notes

- The backend assumes Ollama may be available locally at
  `http://127.0.0.1:11434`.
- Ollama is not required for the current endpoints.
- No external paid APIs are called.
- The maintenance agent only suggests commands. It does not execute them.
- The coding agent returns planning guidance only. It does not edit files.
