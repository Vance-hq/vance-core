import os


class MemoryConfig:
    REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB_SESSION", "0"))
    TTL_S: int = int(os.getenv("REDIS_TTL_SESSION_S", "86400"))
