import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path

from common.tasks import ALLOWED_TASK_TYPES

DEVICE_TYPES = {
    "desktop",
    "laptop",
    "mini_pc",
    "raspberry_pi",
    "phone",
    "tablet",
    "microcontroller",
    "unknown",
}


@dataclass(frozen=True)
class WorkerSettings:
    controller_url: str
    device_id: str
    registration_token: str | None
    token: str | None
    token_file: Path
    capabilities: list[str]
    allowed_dirs: tuple[Path, ...]
    device_type: str | None = None
    gpu_compute_name: str | None = None
    max_file_bytes: int = 100 * 1024 * 1024
    heartbeat_interval: float = 10.0
    poll_interval: float = 2.0
    request_timeout: float = 30.0

    def __post_init__(self) -> None:
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.device_id
        ):
            raise ValueError("Invalid device ID")
        if self.device_type not in DEVICE_TYPES | {None}:
            raise ValueError("Invalid device type")
        if set(self.capabilities) - ALLOWED_TASK_TYPES:
            raise ValueError("Unsupported worker capability")
        if (
            self.device_type == "microcontroller"
            and self.capabilities
        ):
            raise ValueError("Current Python tasks do not support ESP32")
        if not self.allowed_dirs:
            raise ValueError(
                "KOVAN_ALLOWED_DIRS must contain at least one trusted directory"
            )
        if self.max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        if self.heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        if self.poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be positive")

    @classmethod
    def from_env(cls) -> "WorkerSettings":
        device_id = (
            os.getenv("KOVAN_DEVICE_ID") or socket.gethostname()
        )
        capabilities = sorted(
            {
                item.strip()
                for item in os.getenv(
                    "KOVAN_CAPABILITIES",
                    "sha256_file,word_count,pi_monte_carlo,prime_count",
                ).split(",")
                if item.strip()
            }
        )
        allowed_dirs = tuple(
            Path(item.strip())
            for item in os.getenv("KOVAN_ALLOWED_DIRS", "").split(
                os.pathsep
            )
            if item.strip()
        )
        device_type = os.getenv("KOVAN_DEVICE_TYPE") or None

        return cls(
            controller_url=os.getenv(
                "KOVAN_CONTROLLER_URL",
                "http://127.0.0.1:8000",
            ).rstrip("/"),
            device_id=device_id,
            registration_token=(
                os.getenv("KOVAN_REGISTRATION_TOKEN") or None
            ),
            token=os.getenv("KOVAN_WORKER_TOKEN") or None,
            token_file=Path(
                os.getenv(
                    "KOVAN_TOKEN_FILE",
                    f".kovan-secrets/worker-{device_id}.json",
                )
            ),
            capabilities=capabilities,
            allowed_dirs=allowed_dirs,
            device_type=device_type,
            gpu_compute_name=(
                os.getenv("KOVAN_GPU_COMPUTE_NAME") or None
            ),
            max_file_bytes=int(
                os.getenv("KOVAN_MAX_FILE_BYTES", "104857600")
            ),
            heartbeat_interval=float(
                os.getenv("KOVAN_HEARTBEAT_INTERVAL", "10")
            ),
            poll_interval=float(
                os.getenv("KOVAN_POLL_INTERVAL", "2")
            ),
            request_timeout=float(
                os.getenv("KOVAN_REQUEST_TIMEOUT", "30")
            ),
        )
