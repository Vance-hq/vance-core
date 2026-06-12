# agents/dev

Claude Code subprocess runner, Git operations, and Vercel deployments.

## Capabilities

| Action | Description |
|---|---|
| `run_claude_code` | Spawn `claude` CLI with a task prompt in a target repo |
| `git_push` | Stage, commit, and push changes to GitHub |
| `deploy` | Trigger a Vercel deployment via API |

## Running locally

```bash
DEV_AGENT_SECRET=xxx python -m agents.dev.main
```

## Security notes

- The Claude Code binary path is configured via `CLAUDE_CODE_BIN` env var.
- Subprocess commands must not accept raw shell strings from task payloads.
- Git operations require `GITHUB_TOKEN` scoped to the target repos only.
- Subprocesses run with `DEV_SUBPROCESS_TIMEOUT_S` timeout to prevent hanging tasks.
