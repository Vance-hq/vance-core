import os


class MarketingConfig:
    PORT: int = int(os.getenv("MARKETING_AGENT_PORT", "8100"))
    SECRET: str = os.getenv("MARKETING_AGENT_SECRET", "")
    DEFAULT_TONE: str = os.getenv("MARKETING_DEFAULT_TONE", "direct-response")
    MAX_COPY_TOKENS: int = int(os.getenv("MARKETING_MAX_COPY_TOKENS", "2048"))
    SEQUENCE_MAX_STEPS: int = int(os.getenv("MARKETING_SEQUENCE_MAX_STEPS", "7"))
