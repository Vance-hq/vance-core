import os


class AnalyticsConfig:
    PORT: int = int(os.getenv("ANALYTICS_AGENT_PORT", "8102"))
    SECRET: str = os.getenv("ANALYTICS_AGENT_SECRET", "")
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    POSTHOG_API_KEY: str = os.getenv("POSTHOG_API_KEY", "")
    POSTHOG_HOST: str = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
    REPORT_CACHE_TTL_S: int = int(os.getenv("ANALYTICS_REPORT_CACHE_TTL_S", "3600"))
