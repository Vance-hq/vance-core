# infra/nginx

Reverse proxy configuration for the Contabo VPS.

## Responsibilities

- TLS termination for webhook endpoint.
- Internal routing: `webhooks.vance.internal` → port 3001.
- Mailcow traffic passthrough (Mailcow manages its own TLS).

## Files (Phase 7)

```
nginx/
├── nginx.conf
└── sites/
    └── vance-webhooks.conf
```
