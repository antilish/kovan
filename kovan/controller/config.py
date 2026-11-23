import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ControllerSettings:
    db_path: Path
    admin_token: str
    registration_token: str
    default_task_timeout_seconds: float = 60.0
    default_max_attempts: int = 3
    reaper_interval_seconds: float = 5.0
    device_offline_seconds: float = 35.0

    def __post_init__(self) -> None:
        if len(self.admin_token) < 32:
            raise ValueError("KOVAN_ADMIN_TOKEN must have at least 32 characters")
        if len(self.registration_token) < 32:
            raise ValueError(
                "KOVAN_REGISTRATION_TOKEN must have at least 32 characters"
            )
        if self.admin_token == self.registration_token:
            raise ValueError("Admin and registration tokens must differ")
        if self.default_task_timeout_seconds <= 0:
            raise ValueError("Task timeout must be positive")
        if not 1 <= self.default_max_attempts <= 20:
            raise ValueError("Default max attempts must be between 1 and 20")
        if self.reaper_interval_seconds <= 0:
            raise ValueError("Reaper interval must be positive")
        if self.device_offline_seconds <= 0:
            raise ValueError("Device offline interval must be positive")

    @classmethod
    def from_env(cls) -> "ControllerSettings":
        return cls(
            db_path=Path(os.getenv("KOVAN_DB_PATH", "kovan.db")),
            admin_token=os.getenv("KOVAN_ADMIN_TOKEN", ""),
            registration_token=os.getenv("KOVAN_REGISTRATION_TOKEN", ""),
            default_task_timeout_seconds=float(
                os.getenv("KOVAN_DEFAULT_TASK_TIMEOUT_SECONDS", "60")
            ),
            default_max_attempts=int(
                os.getenv("KOVAN_DEFAULT_MAX_ATTEMPTS", "3")
            ),
            reaper_interval_seconds=float(
                os.getenv("KOVAN_REAPER_INTERVAL_SECONDS", "5")
            ),
            device_offline_seconds=float(
                os.getenv("KOVAN_DEVICE_OFFLINE_SECONDS", "35")
            ),
        )
