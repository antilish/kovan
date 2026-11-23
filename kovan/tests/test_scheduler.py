from common.schemas import DeviceReport, GPUInfo, TaskRequirements
from controller.scheduler import (
    DeviceSnapshot,
    choose_worker,
    eligible,
)


def snapshot(
    name,
    *,
    device_type="desktop",
    cpu_usage=10,
    cpu_cores=4,
    available_ram=4 * 1024**3,
    gpu_information=None,
    battery_level=None,
    is_charging=None,
    thermal_status=None,
    capabilities=None,
    last_heartbeat=100,
):
    report = DeviceReport(
        device_id=name,
        device_type=device_type,
        supported_capabilities=capabilities or ["word_count"],
        cpu_usage=cpu_usage,
        cpu_cores=cpu_cores,
        total_ram=max(8 * 1024**3, available_ram),
        available_ram=available_ram,
        gpu_information=gpu_information,
        battery_level=battery_level,
        is_charging=is_charging,
        thermal_status=thermal_status,
    )
    return DeviceSnapshot(
        report=report,
        last_heartbeat=last_heartbeat,
        busy=False,
    )


def test_ram_cores_and_capabilities_are_hard_requirements():
    small = snapshot(
        "small",
        available_ram=256 * 1024**2,
        cpu_cores=1,
    )
    requirement = TaskRequirements(
        min_ram_bytes=1024**3,
        min_cpu_cores=2,
    )
    assert not eligible(
        small,
        "word_count",
        requirement,
        now=100,
        offline_after_seconds=35,
    )


def test_gpu_needs_explicit_compute_report_and_not_phone():
    requirement = TaskRequirements(requires_gpu=True)
    phone = snapshot(
        "phone",
        device_type="phone",
        gpu_information=[
            GPUInfo(name="graphics", compute_capable=True)
        ],
    )
    pc = snapshot(
        "pc",
        gpu_information=[
            GPUInfo(name="compute GPU", compute_capable=True)
        ],
    )
    assert choose_worker(
        [phone, pc],
        "word_count",
        requirement,
        now=100,
        offline_after_seconds=35,
    ) == "pc"


def test_mobile_heavy_task_requires_battery_charging_and_thermal_data():
    requirement = TaskRequirements(
        heavy=True,
        estimated_duration_seconds=120,
    )
    unplugged = snapshot(
        "phone",
        device_type="phone",
        battery_level=90,
        is_charging=False,
        thermal_status="normal",
    )
    charging = snapshot(
        "tablet",
        device_type="tablet",
        battery_level=90,
        is_charging=True,
        thermal_status="normal",
    )
    assert choose_worker(
        [unplugged, charging],
        "word_count",
        requirement,
        now=100,
        offline_after_seconds=35,
    ) == "tablet"

    unknown_temperature = snapshot(
        "unknown",
        device_type="phone",
        battery_level=90,
        is_charging=True,
    )
    assert not eligible(
        unknown_temperature,
        "word_count",
        requirement,
        now=100,
        offline_after_seconds=35,
    )


def test_idle_old_pc_can_win_light_task():
    old_idle = snapshot(
        "old",
        cpu_cores=2,
        cpu_usage=1,
        available_ram=1024**3,
    )
    new_busy = snapshot(
        "new",
        cpu_cores=16,
        cpu_usage=70,
        available_ram=16 * 1024**3,
    )
    assert choose_worker(
        [old_idle, new_busy],
        "word_count",
        TaskRequirements(),
        now=100,
        offline_after_seconds=35,
    ) == "old"


def test_offline_busy_and_device_id_filters():
    offline = snapshot("offline", last_heartbeat=1)
    online = snapshot("online")
    busy = DeviceSnapshot(
        report=online.report,
        last_heartbeat=online.last_heartbeat,
        busy=True,
    )
    requirement = TaskRequirements(
        allowed_device_ids=["online"]
    )
    assert choose_worker(
        [offline, busy],
        "word_count",
        requirement,
        now=100,
        offline_after_seconds=35,
    ) is None
    assert choose_worker(
        [offline, online],
        "word_count",
        requirement,
        now=100,
        offline_after_seconds=35,
    ) == "online"
