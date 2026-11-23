"""Controller ve yerel worker'ı tek süreçte başlatan çalıştırıcı.

Bu modül Qt'ye bağlı değildir; testler arayüz olmadan kullanabilir.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import socket
import threading
import time
from pathlib import Path

import httpx
import psutil
import uvicorn

from common.tasks import ALLOWED_TASK_TYPES
from controller.app import create_app
from controller.config import ControllerSettings
from worker.config import WorkerSettings
from worker.main import run_worker_with


def read_or_create_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    except OSError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value)
    return value


def default_device_id() -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", socket.gethostname())
    name = name.strip("-._")[:64].strip("-._")
    return name or "local-pc"


def detect_device_type() -> str:
    try:
        return "laptop" if psutil.sensors_battery() is not None else "desktop"
    except Exception:
        return "desktop"


def lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))  # paket göndermez
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


class LocalRuntime:
    def __init__(
        self,
        root: Path | str,
        *,
        host: str | None = None,
        port: int = 8000,
        run_worker: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        secrets_dir = self.root / ".kovan-secrets"
        self.secrets_dir = secrets_dir
        if host is None:
            host = "0.0.0.0" if self._load_settings().get("lan") else "127.0.0.1"
        self.host = host
        self.port = port
        self.lan = host not in {"127.0.0.1", "localhost"}
        self.data_dir = self.root / "data"
        self.admin_token = read_or_create_secret(secrets_dir / "admin.txt")
        self.registration_token = read_or_create_secret(
            secrets_dir / "registration.txt"
        )
        self.device_id = default_device_id()
        self.worker_state = "Başlamadı"
        self._with_worker = run_worker

        self._server: uvicorn.Server | None = None
        self._server_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None

    @property
    def settings_path(self) -> Path:
        return self.secrets_dir / "settings.json"

    def _load_settings(self) -> dict:
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self, **values: object) -> None:
        data = self._load_settings()
        data.update(values)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(data), encoding="utf-8")

    def set_lan(self, enabled: bool) -> None:
        """Controller'ı ağa açar/kapatır. Yerel worker çalışmaya devam eder."""
        if enabled == self.lan and self._server is not None:
            return
        self._stop_controller()
        self.host = "0.0.0.0" if enabled else "127.0.0.1"
        self.lan = enabled
        self._save_settings(lan=enabled)
        self._start_controller()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers={"X-Admin-Token": self.admin_token},
            timeout=5.0,
        )

    def _set_state(self, state: str) -> None:
        self.worker_state = state

    def start(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._start_controller()
        if self._with_worker:
            self._start_worker()

    def _start_controller(self) -> None:
        settings = ControllerSettings(
            db_path=self.root / "kovan.db",
            admin_token=self.admin_token,
            registration_token=self.registration_token,
        )
        app = create_app(settings)
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            loop="asyncio",
            http="h11",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run, name="kovan-controller", daemon=True
        )
        thread.start()

        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError(
                    f"Controller başlatılamadı. {self.port} portu başka "
                    "bir program tarafından kullanılıyor olabilir."
                )
            if time.monotonic() > deadline:
                raise RuntimeError("Controller zamanında başlamadı.")
            time.sleep(0.05)

        self._server = server
        self._server_thread = thread

    def _start_worker(self) -> None:
        settings = WorkerSettings(
            controller_url=self.base_url,
            device_id=self.device_id,
            registration_token=self.registration_token,
            token=None,
            token_file=self.secrets_dir / f"worker-{self.device_id}.json",
            capabilities=sorted(ALLOWED_TASK_TYPES),
            allowed_dirs=(self.data_dir,),
            device_type=detect_device_type(),
            heartbeat_interval=5.0,
            poll_interval=1.0,
        )

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._stop = asyncio.Event()
            try:
                loop.run_until_complete(
                    run_worker_with(settings, self._stop, self._set_state)
                )
                self.worker_state = "Durdu"
            except Exception as exc:  # arayüzde göster
                self.worker_state = f"Hata: {exc}"
            finally:
                loop.close()

        self.worker_state = "Başlıyor"
        thread = threading.Thread(
            target=runner, name="kovan-local-worker", daemon=True
        )
        thread.start()
        self._worker_thread = thread

    def stop(self) -> None:
        if self._loop is not None and self._stop is not None:
            try:
                self._loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5)

        self._stop_controller()

    def _stop_controller(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_thread is not None:
            self._server_thread.join(timeout=10)
        self._server = None
        self._server_thread = None
