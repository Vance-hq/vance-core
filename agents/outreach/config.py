import os


class OutreachConfig:
    PORT: int = int(os.getenv("OUTREACH_AGENT_PORT", "8101"))
    SECRET: str = os.getenv("OUTREACH_AGENT_SECRET", "")
    REPLY_POLL_INTERVAL_S: int = int(os.getenv("OUTREACH_REPLY_POLL_INTERVAL_S", "300"))
    LINKEDIN_EMAIL: str = os.getenv("LINKEDIN_EMAIL", "")
    LINKEDIN_PASSWORD: str = os.getenv("LINKEDIN_PASSWORD", "")
    LEAD_SCORE_THRESHOLD: float = float(os.getenv("OUTREACH_LEAD_SCORE_THRESHOLD", "0.65"))
