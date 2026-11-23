import os
import platform
import socket

import psutil

from common.schemas import DeviceReport, GPUInfo
from worker.config import WorkerSettings


class DeviceProbe:
    def __init__(self, settings: WorkerSettings) -> None:
        self.settings = settings

    def collect(self) -> DeviceReport:
        cpu_usage = None
        total_ram = None
        available_ram = None
        battery_level = None
        is_charging = None

        try:
            cpu_usage = psutil.cpu_percent(interval=0.1)
        except Exception:
            pass

        try:
            memory = psutil.virtual_memory()
            total_ram = int(memory.total)
            available_ram = int(memory.available)
        except Exception:
            pass

        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                battery_level = float(battery.percent)
                is_charging = bool(battery.power_plugged)
        except Exception:
            pass

        gpu_information = None
        if self.settings.gpu_compute_name:
            # Açıkça yapılandırılmış iddia; donanım doğrulaması değildir.
            gpu_information = [
                GPUInfo(
                    name=self.settings.gpu_compute_name,
                    compute_capable=True,
                )
            ]

        return DeviceReport(
            device_id=self.settings.device_id,
            hostname=socket.gethostname() or None,
            operating_system=platform.system() or None,
            os_version=platform.version() or None,
            architecture=platform.machine() or None,
            processor_name=platform.processor() or None,
            cpu_cores=os.cpu_count(),
            cpu_usage=cpu_usage,
            total_ram=total_ram,
            available_ram=available_ram,
            gpu_information=gpu_information,
            supported_capabilities=self.settings.capabilities,
            device_type=self.settings.device_type,
            battery_level=battery_level,
            is_charging=is_charging,
            # Genel amaçlı ve güvenilir bir platformlar arası eşleme yok.
            thermal_status=None,
        )
