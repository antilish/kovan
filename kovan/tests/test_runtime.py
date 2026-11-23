import socket
import time

from gui.runtime import LocalRuntime


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    return None


def test_local_runtime_runs_task_end_to_end(tmp_path):
    runtime = LocalRuntime(tmp_path, port=free_port())
    runtime.start()
    try:
        with runtime.client() as client:
            def device_online():
                devices = client.get("/devices").json()
                return devices and devices[0]["connection_status"] == "online"

            assert wait_for(device_online), runtime.worker_state

            sample = runtime.data_dir / "sample.txt"
            sample.write_text("bir iki üç dört", encoding="utf-8")

            ids = [
                client.post(
                    "/tasks",
                    json={
                        "task_type": "word_count",
                        "payload": {"text": "a b c"},
                    },
                ).json()["task_id"],
                client.post(
                    "/tasks",
                    json={
                        "task_type": "word_count",
                        "payload": {"path": str(sample)},
                        "requirements": {
                            "allowed_device_ids": [runtime.device_id]
                        },
                    },
                ).json()["task_id"],
            ]

            def all_done():
                tasks = {
                    t["id"]: t for t in client.get("/tasks").json()
                }
                return all(
                    tasks[i]["status"] == "completed" for i in ids
                ) and tasks

            tasks = wait_for(all_done)
            assert tasks, client.get("/tasks").text
            assert tasks[ids[0]]["result"]["word_count"] == 3
            assert tasks[ids[1]]["result"]["word_count"] == 4
    finally:
        runtime.stop()


def test_secrets_are_created_and_reused(tmp_path):
    first = LocalRuntime(tmp_path, port=free_port(), run_worker=False)
    second = LocalRuntime(tmp_path, port=free_port(), run_worker=False)
    assert first.admin_token == second.admin_token
    assert first.admin_token != first.registration_token
    assert len(first.admin_token) >= 32


def test_lan_toggle_restarts_controller_and_keeps_local_worker(tmp_path):
    runtime = LocalRuntime(tmp_path, port=free_port())
    assert runtime.lan is False
    runtime.start()
    try:
        with runtime.client() as client:
            assert wait_for(lambda: client.get("/devices").json())

            runtime.set_lan(True)
            assert runtime.lan is True and runtime.host == "0.0.0.0"
            assert client.get("/health").status_code == 200

            # Ayar kalıcıdır: yeni çalıştırıcı LAN modunda açılır.
            assert LocalRuntime(tmp_path, port=free_port(), run_worker=False).lan

            # Yerel worker yeniden başlayan controller'a bağlı kalmalı.
            def worker_still_works():
                task_id = client.post(
                    "/tasks",
                    json={"task_type": "word_count", "payload": {"text": "x y"}},
                ).json()["task_id"]
                return wait_for(
                    lambda: client.get(f"/tasks/{task_id}").json()["status"]
                    == "completed",
                    timeout=15,
                )

            assert worker_still_works()

            runtime.set_lan(False)
            assert runtime.lan is False
    finally:
        runtime.stop()
