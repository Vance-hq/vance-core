# agents/analytics

Revenue metrics, funnel analysis, and cohort reporting.

## Capabilities

| Action | Description |
|---|---|
| `revenue_report` | MRR, ARR, churn from Stripe |
| `funnel_analysis` | Conversion funnel breakdown from PostHog |
| `cohort_report` | Retention cohort analysis |

## Running locally

```bash
ANALYTICS_AGENT_SECRET=xxx python -m agents.analytics.main
```

## Data sources

- **Stripe** — subscription revenue, MRR, churn events
- **PostHog** — funnel events, user retention, session data
- Reports are cached in Redis for `ANALYTICS_REPORT_CACHE_TTL_S` seconds.
