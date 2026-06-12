# agents/marketing

Campaign builder, direct-response copy generator, and email sequencer.

## Capabilities

| Action | Payload fields | Description |
|---|---|---|
| `generate_copy` | `brief`, `tone`, `format` | Generate direct-response copy via LLM |
| `build_sequence` | `goal`, `steps`, `audience` | Build multi-step email drip sequence |
| `create_campaign` | `name`, `product`, `target` | Scaffold a full campaign plan |

## Running locally

```bash
MARKETING_AGENT_SECRET=xxx python -m agents.marketing.main
```

## Phase 1 implementation plan

1. `_generate_copy` — Brunson Hook-Story-Offer prompt template
2. `_build_sequence` — sequence planner with Mailcow delivery integration
3. `_create_campaign` — full campaign scaffold using PostHog event data
