# agents/_base — BaseAgent

Shared abstract class that every Vance agent inherits.

## Provided by BaseAgent

- FastAPI app wired with `/health` and `/task` endpoints.
- Shared-secret authentication on all inbound requests.
- Structured logging via `shared/logger`.
- Standard response envelope: `{ status, result | error }`.

## Implementing a new agent

```python
from agents._base import BaseAgent
from shared.config.settings import settings

class MyAgent(BaseAgent):
    name = "my-agent"

    async def handle(self, task: dict) -> dict:
        action = task["payload"]["action"]
        # ... implement capability
        return {"done": True}

agent = MyAgent(secret=settings.MY_AGENT_SECRET)
# serve agent.app with uvicorn
```

## Agent contract with the orchestrator

1. Every agent exposes `GET /health` — orchestrator polls this every 30 s.
2. Tasks arrive as `POST /task` with `X-Agent-Secret` header.
3. Agent returns synchronously for short tasks; long tasks should return a job ID and support `GET /task/{id}` polling (implemented per-agent).
