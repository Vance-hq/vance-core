"""
Central environment-variable loader. Import `settings` everywhere;
never call os.environ directly in application code.
"""

from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    # Anthropic
    ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
    ANTHROPIC_DEFAULT_MODEL: str = os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-6")
    ANTHROPIC_MAX_TOKENS: int = int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192"))
    ANTHROPIC_MAX_RETRIES: int = int(os.getenv("ANTHROPIC_MAX_RETRIES", "3"))
    ANTHROPIC_RETRY_BASE_DELAY_S: float = float(os.getenv("ANTHROPIC_RETRY_BASE_DELAY_S", "1.0"))

    # Redis
    REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    REDIS_DB_SESSION: int = int(os.getenv("REDIS_DB_SESSION", "0"))
    REDIS_DB_QUEUE: int = int(os.getenv("REDIS_DB_QUEUE", "1"))
    REDIS_TTL_SESSION_S: int = int(os.getenv("REDIS_TTL_SESSION_S", "86400"))

    # Postgres
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Orchestrator
    ORCHESTRATOR_HOST: str = os.getenv("ORCHESTRATOR_HOST", "0.0.0.0")
    ORCHESTRATOR_PORT: int = int(os.getenv("ORCHESTRATOR_PORT", "8000"))
    ORCHESTRATOR_SECRET_KEY: str = os.getenv("ORCHESTRATOR_SECRET_KEY", "")
    ORCHESTRATOR_QUEUE_MAX_SIZE: int = int(os.getenv("ORCHESTRATOR_QUEUE_MAX_SIZE", "500"))

    # Webhooks
    VANCE_HOOK_SECRET: str = os.getenv("VANCE_HOOK_SECRET", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # Forge agent
    FORGE_API_URL: str = os.getenv("FORGE_API_URL", "http://localhost:8900")
    FORGE_API_SECRET: str = os.getenv("FORGE_API_SECRET", "")
    FORGE_PIXEL_SERVER_URL: str = os.getenv("FORGE_PIXEL_SERVER_URL", "")
    FORGE_SENDER_POOL: str = os.getenv("FORGE_SENDER_POOL", "[]")
    FORGE_SEED_LIST: str = os.getenv("FORGE_SEED_LIST", "[]")
    FORGE_APOLLO_API_KEY: str = os.getenv("FORGE_APOLLO_API_KEY", "")
    FORGE_HUNTER_API_KEY: str = os.getenv("FORGE_HUNTER_API_KEY", "")
    FORGE_LINKEDIN_COOKIES_PATH: str = os.getenv("FORGE_LINKEDIN_COOKIES_PATH", "/app/.linkedin_cookies.json")

    # Celery (Redis DB 2 for broker, DB 3 for results — separate from session/queue DBs)
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "")

    # SearXNG — web research (replaces SerpAPI)
    SEARXNG_URL: str = os.getenv("SEARXNG_URL", "http://searxng:8080")
    SEARXNG_SECRET_KEY: str = os.getenv("SEARXNG_SECRET_KEY", "")

    # Playwright — browser automation (replaces Apify/Browserless)
    PLAYWRIGHT_BROWSERS_PATH: str = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")

    # LinkedIn credentials (used by outreach agent — Playwright browser automation)
    LINKEDIN_EMAIL: str = os.getenv("LINKEDIN_EMAIL", "")
    LINKEDIN_PASSWORD: str = os.getenv("LINKEDIN_PASSWORD", "")

    # Outreach agent sender alias
    OUTREACH_FROM_EMAIL: str = os.getenv("OUTREACH_FROM_EMAIL", "")
    OUTREACH_FROM_PASSWORD: str = os.getenv("OUTREACH_FROM_PASSWORD", "")

    # Sales agent sender alias
    SALES_FROM_EMAIL: str = os.getenv("SALES_FROM_EMAIL", "")
    SALES_FROM_PASSWORD: str = os.getenv("SALES_FROM_PASSWORD", "")

    # Reviews agent
    YELP_API_KEY: str = os.getenv("YELP_API_KEY", "")
    FACEBOOK_PAGE_ACCESS_TOKEN: str = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    TRUSTED_PLUMBING_GBP_ACCOUNT: str = os.getenv("TRUSTED_PLUMBING_GBP_ACCOUNT", "")
    TRUSTED_PLUMBING_GBP_LOCATION: str = os.getenv("TRUSTED_PLUMBING_GBP_LOCATION", "")
    TRUSTED_PLUMBING_YELP_BUSINESS_ID: str = os.getenv("TRUSTED_PLUMBING_YELP_BUSINESS_ID", "")
    TRUSTED_PLUMBING_FACEBOOK_PAGE_ID: str = os.getenv("TRUSTED_PLUMBING_FACEBOOK_PAGE_ID", "")
    REVIEWS_ALERT_CHANNEL: str = os.getenv("REVIEWS_ALERT_CHANNEL", "#reviews")
    REVIEWS_FROM_EMAIL: str = os.getenv("REVIEWS_FROM_EMAIL", "")
    REVIEWS_FROM_PASSWORD: str = os.getenv("REVIEWS_FROM_PASSWORD", "")

    # Image generation backend (comfyui = self-hosted GPU; replicate = pay-per-use interim)
    IMAGE_BACKEND: str = os.getenv("IMAGE_BACKEND", "replicate")
    REPLICATE_API_TOKEN: str = os.getenv("REPLICATE_API_TOKEN", "")
    COMFYUI_URL: str = os.getenv("COMFYUI_URL", "http://localhost:8188")

    # Unleash — feature flags (replaces LaunchDarkly)
    UNLEASH_URL: str = os.getenv("UNLEASH_URL", "http://unleash:4242/api")
    UNLEASH_API_TOKEN: str = os.getenv("UNLEASH_API_TOKEN", "")

    # Twenty CRM — self-hosted CRM (replaces HubSpot/GHL for internal use)
    TWENTY_CRM_URL: str = os.getenv("TWENTY_CRM_URL", "http://twenty:3000")
    TWENTY_CRM_API_KEY: str = os.getenv("TWENTY_CRM_API_KEY", "")

    # Grafana / Prometheus / Loki — monitoring (replaces Datadog/New Relic)
    GRAFANA_URL: str = os.getenv("GRAFANA_URL", "http://grafana:3000")
    PROMETHEUS_URL: str = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    LOKI_URL: str = os.getenv("LOKI_URL", "http://loki:3100")

    # Outline — knowledge base / wiki (replaces Notion/Confluence)
    OUTLINE_URL: str = os.getenv("OUTLINE_URL", "http://outline:3000")
    OUTLINE_API_TOKEN: str = os.getenv("OUTLINE_API_TOKEN", "")

    # Umami — web analytics (replaces GA on owned properties)
    UMAMI_URL: str = os.getenv("UMAMI_URL", "http://umami:3000")
    UMAMI_WEBSITE_ID: str = os.getenv("UMAMI_WEBSITE_ID", "")

    # Uptime Kuma — uptime monitoring
    UPTIME_KUMA_URL: str = os.getenv("UPTIME_KUMA_URL", "http://uptime-kuma:3001")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")
    LOG_DIR: str = os.getenv("LOG_DIR", "/var/log/vance")

    # Agent endpoints
    MARKETING_AGENT_HOST: str = os.getenv("MARKETING_AGENT_HOST", "10.10.0.2")
    MARKETING_AGENT_PORT: int = int(os.getenv("MARKETING_AGENT_PORT", "8100"))
    MARKETING_AGENT_SECRET: str = os.getenv("MARKETING_AGENT_SECRET", "")

    OUTREACH_AGENT_HOST: str = os.getenv("OUTREACH_AGENT_HOST", "10.10.0.2")
    OUTREACH_AGENT_PORT: int = int(os.getenv("OUTREACH_AGENT_PORT", "8101"))
    OUTREACH_AGENT_SECRET: str = os.getenv("OUTREACH_AGENT_SECRET", "")

    ANALYTICS_AGENT_HOST: str = os.getenv("ANALYTICS_AGENT_HOST", "10.10.0.2")
    ANALYTICS_AGENT_PORT: int = int(os.getenv("ANALYTICS_AGENT_PORT", "8102"))
    ANALYTICS_AGENT_SECRET: str = os.getenv("ANALYTICS_AGENT_SECRET", "")

    DEV_AGENT_HOST: str = os.getenv("DEV_AGENT_HOST", "10.10.0.2")
    DEV_AGENT_PORT: int = int(os.getenv("DEV_AGENT_PORT", "8103"))
    DEV_AGENT_SECRET: str = os.getenv("DEV_AGENT_SECRET", "")

    SECURITY_AGENT_HOST: str = os.getenv("SECURITY_AGENT_HOST", "10.10.0.2")
    SECURITY_AGENT_PORT: int = int(os.getenv("SECURITY_AGENT_PORT", "8104"))
    SECURITY_AGENT_SECRET: str = os.getenv("SECURITY_AGENT_SECRET", "")

    # Backup agent
    BACKUP_ENCRYPTION_KEY: str = os.getenv("BACKUP_ENCRYPTION_KEY", "")
    MAILCOW_API_KEY: str = os.getenv("MAILCOW_API_KEY", "")

    # Mailcow SMTP (pre-installed on VPS)
    MAILCOW_HOST: str = os.getenv("MAILCOW_HOST", "10.10.0.2")
    MAILCOW_DOMAIN: str = os.getenv("MAILCOW_DOMAIN", "")
    MAILCOW_SMTP_PORT: int = int(os.getenv("MAILCOW_SMTP_PORT", "587"))
    MAILCOW_SMTP_USER: str = os.getenv("MAILCOW_SMTP_USER", "")
    MAILCOW_SMTP_PASSWORD: str = os.getenv("MAILCOW_SMTP_PASSWORD", "")

    # Google Places API (free tier: 28,500 calls/month)
    GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")

    # Backblaze B2 (S3-compatible storage, $6/TB)
    B2_KEY_ID: str = os.getenv("B2_KEY_ID", "")
    B2_APPLICATION_KEY: str = os.getenv("B2_APPLICATION_KEY", "")
    B2_ENDPOINT_URL: str = os.getenv("B2_ENDPOINT_URL", "")
    B2_BUCKET_NAME: str = os.getenv("B2_BUCKET_NAME", "vance-reports")

    # LocalRankGrader / LocalOutRank
    GRADER_TRACKER_URL: str = os.getenv("GRADER_TRACKER_URL", "")
    LOCALOUTRANK_TRIAL_URL: str = os.getenv("LOCALOUTRANK_TRIAL_URL", "https://localoutrank.ai/trial")

    # GitHub
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_ORG: str = os.getenv("GITHUB_ORG", "")

    # Vercel
    VERCEL_TOKEN: str = os.getenv("VERCEL_TOKEN", "")
    VERCEL_TEAM_ID: str = os.getenv("VERCEL_TEAM_ID", "")

    # Cloudflare
    CLOUDFLARE_API_TOKEN: str = os.getenv("CLOUDFLARE_API_TOKEN", "")
    CLOUDFLARE_ACCOUNT_ID: str = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")

    # Railway
    RAILWAY_API_TOKEN: str = os.getenv("RAILWAY_API_TOKEN", "")

    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_PROJECT_REF: str = os.getenv("SUPABASE_PROJECT_REF", "")

    # Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")

    # Square
    SQUARE_ACCESS_TOKEN: str = os.getenv("SQUARE_ACCESS_TOKEN", "")
    SQUARE_ENVIRONMENT: str = os.getenv("SQUARE_ENVIRONMENT", "production")

    # QuickBooks (OAuth2 refresh token)
    QB_CLIENT_ID: str = os.getenv("QB_CLIENT_ID", "")
    QB_CLIENT_SECRET: str = os.getenv("QB_CLIENT_SECRET", "")
    QB_REALM_ID: str = os.getenv("QB_REALM_ID", "")
    QB_REFRESH_TOKEN: str = os.getenv("QB_REFRESH_TOKEN", "")

    # Google OAuth2 — shared client credentials across all Google services
    GOOGLE_OAUTH_CLIENT_ID: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_OAUTH_CLIENT_SECRET: str = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")

    # Google Workspace (Gmail, Drive, Docs)
    GOOGLE_WORKSPACE_REFRESH_TOKEN: str = os.getenv("GOOGLE_WORKSPACE_REFRESH_TOKEN", "")

    # Google Analytics (GA4)
    GA4_PROPERTY_ID: str = os.getenv("GA4_PROPERTY_ID", "")
    GA4_REFRESH_TOKEN: str = os.getenv("GA4_REFRESH_TOKEN", "")

    # Google Ads
    GOOGLE_ADS_DEVELOPER_TOKEN: str = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    GOOGLE_ADS_REFRESH_TOKEN: str = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")
    GOOGLE_ADS_CUSTOMER_ID: str = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "")

    # Google Business Profile
    GBP_REFRESH_TOKEN: str = os.getenv("GBP_REFRESH_TOKEN", "")

    # Meta Ads (Facebook/Instagram)
    META_ACCESS_TOKEN: str = os.getenv("META_ACCESS_TOKEN", "")
    META_AD_ACCOUNT_ID: str = os.getenv("META_AD_ACCOUNT_ID", "")

    # Slack
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")

    # Twilio
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")

    # Calendly
    CALENDLY_API_TOKEN: str = os.getenv("CALENDLY_API_TOKEN", "")

    # PostHog — behavioral analytics
    POSTHOG_API_KEY: str = os.getenv("POSTHOG_API_KEY", "")
    POSTHOG_HOST: str = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
    POSTHOG_PROJECT_ID: str = os.getenv("POSTHOG_PROJECT_ID", "")

    # Analytics agent
    ANALYTICS_SLACK_CHANNEL: str = os.getenv("ANALYTICS_SLACK_CHANNEL", "#analytics")
    ANALYTICS_ANOMALY_THRESHOLD: float = float(os.getenv("ANALYTICS_ANOMALY_THRESHOLD", "0.15"))

    # Security agent
    SECURITY_ALERT_CHANNEL: str = os.getenv("SECURITY_ALERT_CHANNEL", "#ops")


@lru_cache(maxsize=1)
def _load() -> Settings:
    return Settings()


settings = _load()
