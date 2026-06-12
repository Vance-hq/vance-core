# agents/outreach

LinkedIn automation, reply detection, and lead scoring.

## Capabilities

| Action | Description |
|---|---|
| `send_connection` | Send a LinkedIn connection request with personalised note |
| `detect_replies` | Poll LinkedIn and Mailcow for new replies; classify intent |
| `score_lead` | LLM-based lead scoring against ICP criteria |

## Running locally

```bash
OUTREACH_AGENT_SECRET=xxx python -m agents.outreach.main
```

## Notes

- LinkedIn credentials must be set in env. Session cookies are cached in Redis.
- Reply detection runs on a configurable poll interval (`OUTREACH_REPLY_POLL_INTERVAL_S`).
- High-score leads (`>= OUTREACH_LEAD_SCORE_THRESHOLD`) are forwarded to the marketing agent for sequencing.
