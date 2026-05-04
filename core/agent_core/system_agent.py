"""System information agent."""

from datetime import datetime, timezone
import os
import platform
import socket
import time

import psutil


class SystemAgent:
    name = "system_agent"
    description = "Reports local system status."

    def stats(self) -> dict:
        boot_time = psutil.boot_time()
        uptime_seconds = int(time.time() - boot_time)
        boot_datetime = datetime.fromtimestamp(boot_time, timezone.utc)
        cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        return {
            "cpu_percent": self._average_percent(cpu_per_core),
            "cpu_cores_total": psutil.cpu_count(logical=True),
            "cpu_cores_active": sum(1 for percent in cpu_per_core if percent > 5),
            "memory_percent": memory.percent,
            "memory_total_gb": self._bytes_to_gb(memory.total, precision=1),
            "memory_used_gb": self._bytes_to_gb(memory.used, precision=1),
            "memory_free_gb": self._bytes_to_gb(memory.available, precision=1),
            "disk_percent": disk.percent,
            "disk_total_gb": self._bytes_to_gb(disk.total),
            "disk_used_gb": self._bytes_to_gb(disk.used),
            "disk_free_gb": self._bytes_to_gb(disk.free),
            "uptime": self._format_uptime(uptime_seconds),
            "uptime_seconds": uptime_seconds,
            "boot_time": boot_datetime.isoformat(),
            "load_avg": self._load_average(),
            "hostname": socket.gethostname(),
            "current_time": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(),
        }

    def handle(self, message: str = "") -> dict:
        return {
            "agent": self.name,
            "response": "Current system status is available.",
            "data": self.stats(),
        }

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m"

    @staticmethod
    def _bytes_to_gb(value: int, precision: int = 0) -> int | float:
        gb = value / (1024**3)
        return round(gb, precision) if precision else round(gb)

    @staticmethod
    def _average_percent(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 1)

    @staticmethod
    def _load_average() -> dict | None:
        if not hasattr(os, "getloadavg"):
            return None
        one, five, fifteen = os.getloadavg()
        return {
            "1m": round(one, 2),
            "5m": round(five, 2),
            "15m": round(fifteen, 2),
        }
