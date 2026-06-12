import os


class DevConfig:
    PORT: int = int(os.getenv("DEV_AGENT_PORT", "8103"))
    SECRET: str = os.getenv("DEV_AGENT_SECRET", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_ORG: str = os.getenv("GITHUB_ORG", "")
    VERCEL_TOKEN: str = os.getenv("VERCEL_TOKEN", "")
    VERCEL_TEAM_ID: str = os.getenv("VERCEL_TEAM_ID", "")
    CLAUDE_CODE_BIN: str = os.getenv("CLAUDE_CODE_BIN", "/usr/local/bin/claude")
    SUBPROCESS_TIMEOUT_S: int = int(os.getenv("DEV_SUBPROCESS_TIMEOUT_S", "300"))
