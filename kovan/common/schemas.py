from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Capability = Literal[
    "sha256_file", "word_count", "pi_monte_carlo", "prime_count"
]
DeviceType = Literal[
    "desktop",
    "laptop",
    "mini_pc",
    "raspberry_pi",
    "phone",
    "tablet",
    "microcontroller",
    "unknown",
]
ThermalStatus = Literal["normal", "warm", "hot", "critical"]
TaskStatus = Literal["queued", "running", "completed", "failed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GPUInfo(StrictModel):
    name: str | None = Field(default=None, max_length=255)
    compute_capable: bool = False


class DeviceReport(StrictModel):
    device_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
    )
    hostname: str | None = Field(default=None, max_length=255)
    operating_system: str | None = Field(default=None, max_length=255)
    os_version: str | None = Field(default=None, max_length=255)
    architecture: str | None = Field(default=None, max_length=255)
    processor_name: str | None = Field(default=None, max_length=255)
    cpu_cores: int | None = Field(default=None, ge=1)
    cpu_usage: float | None = Field(default=None, ge=0, le=100)
    total_ram: int | None = Field(default=None, ge=0)
    available_ram: int | None = Field(default=None, ge=0)
    gpu_information: list[GPUInfo] | None = Field(default=None, max_length=8)
    supported_capabilities: list[Capability] = Field(
        default_factory=list, max_length=16
    )
    device_type: DeviceType | None = None
    battery_level: float | None = Field(default=None, ge=0, le=100)
    is_charging: bool | None = None
    thermal_status: ThermalStatus | None = None

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        if (
            self.total_ram is not None
            and self.available_ram is not None
            and self.available_ram > self.total_ram
        ):
            raise ValueError("available_ram cannot exceed total_ram")

        if len(set(self.supported_capabilities)) != len(
            self.supported_capabilities
        ):
            raise ValueError("Duplicate capabilities are not allowed")

        # ESP32 için görev ve protokol henüz uygulanmadı.
        if (
            self.device_type == "microcontroller"
            and self.supported_capabilities
        ):
            raise ValueError(
                "Microcontrollers cannot advertise current task types"
            )
        return self


class DeviceView(DeviceReport):
    connection_status: Literal["online", "offline"]
    last_heartbeat: float | None


class WorkerRegisterRequest(StrictModel):
    device: DeviceReport


class WorkerRegisterResponse(StrictModel):
    device_id: str
    token: str


class WorkerPairRequest(StrictModel):
    code: str = Field(min_length=4, max_length=32)
    device: DeviceReport


class WorkerHeartbeatRequest(StrictModel):
    device: DeviceReport


class TaskRequirements(StrictModel):
    min_ram_bytes: int = Field(default=0, ge=0)
    min_cpu_cores: int = Field(default=0, ge=0)
    requires_gpu: bool = False
    required_capabilities: list[Capability] = Field(default_factory=list)
    estimated_duration_seconds: float | None = Field(
        default=None, gt=0, le=86_400
    )
    priority: int = Field(default=0, ge=0, le=100)
    allowed_device_types: list[DeviceType] | None = None
    # Yerel dosya yollarını belirli worker'lara yönlendirmek için.
    allowed_device_ids: list[str] | None = Field(default=None, max_length=100)
    heavy: bool = False
    cpu_intensity: Literal["low", "medium", "high"] = "low"

    @model_validator(mode="after")
    def check_lists(self) -> Self:
        if self.allowed_device_types == []:
            raise ValueError("allowed_device_types cannot be empty")
        if self.allowed_device_ids == []:
            raise ValueError("allowed_device_ids cannot be empty")
        return self


class TaskCreateRequest(StrictModel):
    task_type: Capability
    payload: dict[str, Any]
    requirements: TaskRequirements = Field(
        default_factory=TaskRequirements
    )
    timeout_seconds: float | None = Field(
        default=None, gt=0, le=86_400
    )
    max_attempts: int | None = Field(default=None, ge=1, le=20)


class TaskCreateResponse(StrictModel):
    task_id: int
    status: TaskStatus


class TaskClaimResponse(StrictModel):
    id: int
    task_type: Capability
    payload: dict[str, Any]
    timeout_seconds: float
    attempt_count: int
    max_attempts: int
    lease_id: str


class TaskResultRequest(StrictModel):
    lease_id: str = Field(min_length=16, max_length=200)
    success: bool
    result: Any = None
    error: str | None = Field(default=None, max_length=4096)
    retryable: bool = False

    @model_validator(mode="after")
    def check_retryable(self) -> Self:
        if self.success and self.retryable:
            raise ValueError("Successful results cannot be retryable")
        return self
