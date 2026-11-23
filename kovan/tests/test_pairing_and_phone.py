import shutil
import subprocess
import time
from pathlib import Path

import pytest

from gui.runtime import LocalRuntime
from tests.conftest import ADMIN_TOKEN
from tests.test_controller_api import ADMIN, create_task, device, register
from tests.test_runtime import free_port, wait_for

HARNESS = Path(__file__).with_name("phone_harness.js")


def phone_report(device_id="phone-abc123"):
    return device(
        device_id,
        device_type="phone",
        capabilities=["pi_monte_carlo", "prime_count"],
        battery_level=80,
        is_charging=True,
    )


def new_code(client):
    response = client.post("/pairing-codes", headers=ADMIN)
    assert response.status_code == 200
    return response.json()["code"]


def test_pairing_code_is_single_use_and_expires(client, clock):
    assert client.post("/pairing-codes").status_code == 401

    code = new_code(client)
    assert len(code) == 9 and code[4] == "-"

    response = client.post(
        "/workers/pair", json={"code": code.lower(), "device": phone_report()}
    )
    assert response.status_code == 200
    token = response.json()["token"]
    assert token

    # Aynı kod ikinci kez kullanılamaz.
    response = client.post(
        "/workers/pair", json={"code": code, "device": phone_report("phone-two")}
    )
    assert response.status_code == 401

    # Süresi dolan kod geçersizdir.
    stale = new_code(client)
    clock.advance(301)
    response = client.post(
        "/workers/pair", json={"code": stale, "device": phone_report("phone-three")}
    )
    assert response.status_code == 401

    devices = client.get("/devices", headers=ADMIN).json()
    assert [d["device_id"] for d in devices] == ["phone-abc123"]
    assert devices[0]["device_type"] == "phone"


def test_pairing_is_rate_limited(client):
    statuses = [
        client.post(
            "/workers/pair",
            json={"code": f"ZZZZ-{i:04d}", "device": phone_report(f"p{i}")},
        ).status_code
        for i in range(12)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10:] == [429, 429]

    # Sınır doluyken doğru kod bile denenemez.
    code = new_code(client)
    response = client.post(
        "/workers/pair", json={"code": code, "device": phone_report("late")}
    )
    assert response.status_code == 429


def test_duplicate_device_id_cannot_be_paired(client):
    register(client, phone_report("phone-abc123"))
    response = client.post(
        "/workers/pair",
        json={"code": new_code(client), "device": phone_report("phone-abc123")},
    )
    assert response.status_code == 409


def test_phone_page_is_served_with_security_headers(client):
    response = client.get("/phone")
    assert response.status_code == 200
    assert "KOVAN" in response.text
    assert "worker-src blob:" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    # Sayfa gizli bilgi içermemeli.
    assert ADMIN_TOKEN not in response.text


def test_delete_device_releases_its_running_task(client):
    token = register(client, device("pc1"))
    task_id = create_task(client)
    claim = client.post("/workers/claim", headers={"X-Device-Token": token})
    assert claim.status_code == 200

    assert client.delete("/devices/pc1", headers=ADMIN).status_code == 204
    assert client.delete("/devices/pc1", headers=ADMIN).status_code == 404
    assert client.get("/devices", headers=ADMIN).json() == []
    info = client.get(f"/tasks/{task_id}", headers=ADMIN).json()
    assert info["status"] == "queued"


def test_portable_tasks_skip_laptop_without_capability(client):
    """Yalnızca dosya yeteneği olan cihaz π görevini almamalı."""
    token = register(
        client, device("filer", capabilities=["sha256_file", "word_count"])
    )
    response = client.post(
        "/tasks",
        headers=ADMIN,
        json={
            "task_type": "pi_monte_carlo",
            "payload": {"samples": 1000, "seed": 1},
        },
    )
    assert response.status_code == 200
    claim = client.post("/workers/claim", headers={"X-Device-Token": token})
    assert claim.status_code == 204


@pytest.mark.skipif(shutil.which("node") is None, reason="node yüklü değil")
def test_real_phone_page_javascript_pairs_and_computes(tmp_path):
    runtime = LocalRuntime(tmp_path, port=free_port(), run_worker=False)
    runtime.start()
    proc = None
    try:
        with runtime.client() as client:
            code = client.post("/pairing-codes").json()["code"]
            proc = subprocess.Popen(
                ["node", str(HARNESS), runtime.base_url, code],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            def phone_online():
                devices = client.get("/devices").json()
                return [
                    d for d in devices
                    if d["device_type"] == "phone"
                    and d["connection_status"] == "online"
                ]

            phones = wait_for(phone_online, timeout=20)
            assert phones, proc.poll()
            assert phones[0]["operating_system"] == "Android"
            assert phones[0]["os_version"] == "9"
            assert phones[0]["supported_capabilities"] == [
                "pi_monte_carlo", "prime_count"
            ]
            assert phones[0]["battery_level"] is None  # HTTP'de pil bilgisi yok

            pi_id = client.post(
                "/tasks",
                json={
                    "task_type": "pi_monte_carlo",
                    "payload": {"samples": 300_000, "seed": 7},
                },
            ).json()["task_id"]
            prime_id = client.post(
                "/tasks",
                json={
                    "task_type": "prime_count",
                    "payload": {"start": 0, "stop": 1_000_000},
                },
            ).json()["task_id"]

            def finished():
                tasks = {t["id"]: t for t in client.get("/tasks").json()}
                if all(tasks[i]["status"] == "completed" for i in (pi_id, prime_id)):
                    return tasks

            tasks = wait_for(finished, timeout=30)
            assert tasks, client.get("/tasks").text
            assert tasks[prime_id]["result"]["count"] == 78498
            pi = tasks[pi_id]["result"]
            assert 3.12 < 4 * pi["inside"] / pi["samples"] < 3.17
            assert tasks[pi_id]["assigned_worker"] == phones[0]["device_id"]
    finally:
        if proc is not None:
            proc.kill()
        runtime.stop()
