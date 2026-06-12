# core/memory

Redis-backed session state for the orchestrator. Runs locally.

## Purpose

Stores short-term context between voice commands — e.g. "the Starpio campaign we were just discussing" so follow-up commands don't need full re-statement.

## Usage

```python
from core.memory import MemoryStore

mem = MemoryStore()
mem.set("session-123", "last_campaign", {"name": "Starpio Q3"})
mem.get("session-123", "last_campaign")
```

Keys are namespaced by session ID and expire after `REDIS_TTL_SESSION_S`.
