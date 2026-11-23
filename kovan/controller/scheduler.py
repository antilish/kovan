from dataclasses import dataclass

from common.schemas import DeviceReport, TaskRequirements

MIB = 1024 * 1024
GIB = 1024 * MIB


@dataclass(frozen=True)
class DeviceSnapshot:
    report: DeviceReport
    last_heartbeat: float
    busy: bool


def is_heavy(requirements: TaskRequirements) -> bool:
    return (
        requirements.heavy
        or requirements.cpu_intensity == "high"
        or requirements.min_cpu_cores >= 2
        or requirements.min_ram_bytes >= 512 * MIB
        or (requirements.estimated_duration_seconds or 0) > 60
    )


def eligible(
    device: DeviceSnapshot,
    task_type: str,
    requirements: TaskRequirements,
    *,
    now: float,
    offline_after_seconds: float,
) -> bool:
    report = device.report

    if device.busy:
        return False
    if device.last_heartbeat <= 0:
        return False
    if now - device.last_heartbeat > offline_after_seconds:
        return False

    # Mevcut görevleri ESP32 gibi cihazlara göndermiyoruz.
    if report.device_type == "microcontroller":
        return False
    if task_type not in report.supported_capabilities:
        return False
    if not set(requirements.required_capabilities).issubset(
        report.supported_capabilities
    ):
        return False

    if (
        requirements.allowed_device_types is not None
        and report.device_type not in requirements.allowed_device_types
    ):
        return False
    if (
        requirements.allowed_device_ids is not None
        and report.device_id not in requirements.allowed_device_ids
    ):
        return False

    if requirements.min_cpu_cores:
        if (
            report.cpu_cores is None
            or report.cpu_cores < requirements.min_cpu_cores
        ):
            return False
    if requirements.min_ram_bytes:
        if (
            report.available_ram is None
            or report.available_ram < requirements.min_ram_bytes
        ):
            return False

    mobile = report.device_type in {"phone", "tablet"}
    heavy = is_heavy(requirements)

    if requirements.requires_gpu:
        # Buradaki GPU yalnızca yerleşim koşuludur; mevcut görevler GPU'da
        # hesaplama yapmaz.
        if mobile:
            return False
        if not any(
            gpu.compute_capable for gpu in (report.gpu_information or [])
        ):
            return False

    if report.thermal_status in {"hot", "critical"}:
        return False
    if report.cpu_usage is not None and report.cpu_usage >= 95:
        return False

    if mobile:
        if (
            report.battery_level is not None
            and report.battery_level < 20
            and report.is_charging is not True
        ):
            return False

    if heavy:
        # Bilinmeyen kapasiteyi ağır iş için uygun saymıyoruz.
        if report.cpu_cores is None or report.cpu_cores < 2:
            return False
        if report.available_ram is None or report.available_ram < 256 * MIB:
            return False
        if report.cpu_usage is None or report.cpu_usage >= 75:
            return False

        if mobile and (
            report.is_charging is not True
            or report.battery_level is None
            or report.battery_level < 40
            or report.thermal_status != "normal"
        ):
            return False

        if (
            report.device_type == "laptop"
            and report.battery_level is not None
            and report.battery_level < 20
            and report.is_charging is not True
        ):
            return False

    return True


def score(device: DeviceSnapshot, requirements: TaskRequirements) -> float:
    report = device.report
    heavy = is_heavy(requirements)

    # Hafif işleri düşük yüklü eski bir makine de alabilsin; çekirdek ve
    # bellek miktarı öncelikle ağır işlerde etkili olsun.
    cpu_usage = report.cpu_usage if report.cpu_usage is not None else 50.0
    cores = min(report.cpu_cores or 1, 16)
    available_gib = min((report.available_ram or 0) / GIB, 32)

    value = (100.0 - cpu_usage) * 2
    value += cores * (2.0 if heavy else 0.3)
    value += available_gib * (1.0 if heavy else 0.1)

    if report.device_type in {"phone", "tablet"}:
        value -= 15
        if report.is_charging is not True:
            value -= 20

    return value


def choose_worker(
    devices: list[DeviceSnapshot],
    task_type: str,
    requirements: TaskRequirements,
    *,
    now: float,
    offline_after_seconds: float,
) -> str | None:
    candidates = [
        device
        for device in devices
        if eligible(
            device,
            task_type,
            requirements,
            now=now,
            offline_after_seconds=offline_after_seconds,
        )
    ]
    if not candidates:
        return None

    candidates.sort(
        key=lambda device: (
            -score(device, requirements),
            device.report.device_id,
        )
    )
    return candidates[0].report.device_id
