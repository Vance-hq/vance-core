import os


class SecurityConfig:
    PORT: int = int(os.getenv("SECURITY_AGENT_PORT", "8104"))
    SECRET: str = os.getenv("SECURITY_AGENT_SECRET", "")
    UPTIME_TARGETS: list[str] = [
        t.strip()
        for t in os.getenv("SECURITY_UPTIME_TARGETS", "").split(",")
        if t.strip()
    ]
    ALERT_EMAIL: str = os.getenv("SECURITY_ALERT_EMAIL", "")
    CHECK_INTERVAL_S: int = int(os.getenv("SECURITY_CHECK_INTERVAL_S", "60"))
    LOG_DIRS: list[str] = [
        d.strip()
        for d in os.getenv("SECURITY_LOG_DIRS", "/var/log").split(",")
        if d.strip()
    ]
