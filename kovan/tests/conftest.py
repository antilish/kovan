import threading

import pytest
from fastapi.testclient import TestClient

from controller.app import create_app
from controller.config import ControllerSettings

ADMIN_TOKEN = "a" * 40
REGISTRATION_TOKEN = "r" * 40


class FakeClock:
    def __init__(self) -> None:
        self.value = 10_000.0
        self.lock = threading.Lock()

    def now(self) -> float:
        with self.lock:
            return self.value

    def advance(self, seconds: float) -> None:
        with self.lock:
            self.value += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def controller_settings(tmp_path):
    return ControllerSettings(
        db_path=tmp_path / "kovan_test.db",
        admin_token=ADMIN_TOKEN,
        registration_token=REGISTRATION_TOKEN,
        default_task_timeout_seconds=60,
        default_max_attempts=3,
        reaper_interval_seconds=3600,
        device_offline_seconds=35,
    )


@pytest.fixture
def client(controller_settings, clock):
    app = create_app(controller_settings, clock=clock.now)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(client):
    return client.app.state.db
