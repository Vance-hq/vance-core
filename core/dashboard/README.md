# core/dashboard

Local control UI — agent status, log viewer, task queue overrides.

## Stack

Next.js 14 (TypeScript). Runs locally at `http://localhost:3000`.

## Screens (Phase 6)

- **Overview** — live agent health grid, queue depth, recent tasks
- **Logs** — structured log stream from all agents
- **Tasks** — manual task injection, retry dead-letter queue
- **Settings** — env var viewer (no editing — use `.env` directly)

## Running

```bash
cd core/dashboard
npm install
npm run dev
```

Requires `NEXT_PUBLIC_ORCHESTRATOR_URL` to point to the running orchestrator.
