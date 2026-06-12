import os


class OrchestratorConfig:
    HOST: str = os.getenv("ORCHESTRATOR_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("ORCHESTRATOR_PORT", "7700"))
    SECRET_KEY: str = os.getenv("ORCHESTRATOR_SECRET_KEY", "")
    QUEUE_MAX_SIZE: int = int(os.getenv("ORCHESTRATOR_QUEUE_MAX_SIZE", "500"))
    HEARTBEAT_INTERVAL_S: int = int(os.getenv("ORCHESTRATOR_HEARTBEAT_INTERVAL_S", "30"))
    DISPATCH_CONFIDENCE_MIN: float = float(os.getenv("ORCHESTRATOR_DISPATCH_CONFIDENCE_MIN", "0.5"))
