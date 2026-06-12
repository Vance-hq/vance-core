# webhooks

Inbound event handlers for external services. TypeScript / Express.

## Handled events (Phase 6)

| Source | Path | Purpose |
|---|---|---|
| Stripe | `POST /webhooks/stripe` | Subscription lifecycle, payment events |
| Mailcow | `POST /webhooks/mailcow` | Inbound reply forwarding to outreach agent |

## Running

```bash
cd webhooks
npm install
npm run dev
```

## Security

- Stripe webhooks are verified via `STRIPE_WEBHOOK_SECRET` using the official SDK.
- Mailcow callbacks should be secured with `WEBHOOKS_SECRET` as a shared header.
- The webhooks server should sit behind nginx with TLS on the VPS (see `infra/nginx/`).
