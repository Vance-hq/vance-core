# Vance

Autonomous agent platform powering local business SaaS products.

## Products

| Product | Description | Status |
|---|---|---|
| **Starpio** | Restaurant reservation & table management | 🔨 Building |
| **OneServ** | Job booking for HVAC, plumbing & electrical (< 20 employees) | 🔨 Building |
| **LocalOutrank** | Local SEO & Google Maps ranking automation | 🔨 Building |
| **LocalRankGrader** | Free local SEO grader — entry point for LocalOutrank | 🔨 Building |

## Repository Structure

```
vance-core/
├── products/
│   ├── starpio/          # Restaurant reservation SaaS
│   ├── oneserv/          # Trade contractor job booking SaaS
│   ├── localoutrank/     # Local SEO automation SaaS
│   └── localrankgrader/  # Free grader tool (LocalOutrank funnel entry)
├── shared/               # Shared utilities across all products
└── docs/                 # Architecture and product documentation
```

## Build Order

1. Core products (this)
2. Auth + billing
3. Frontend / landing pages
4. Voice interface
5. Forge outreach engine
6. Infrastructure / ops
