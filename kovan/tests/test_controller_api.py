from concurrent.futures import ThreadPoolExecutor

from tests.conftest import ADMIN_TOKEN, REGISTRATION_TOKEN

ADMIN = {"X-Admin-Token": ADMIN_TOKEN}
REGISTRATION = {
    "X-Registration-Token": REGISTRATION_TOKEN
}


def device(
    device_id,
    *,
    capabilities=None,
    device_type="desktop",
    cpu_usage=10,
    cpu_cores=4,
    available_ram=2 * 1024**3,
    **extra,
):
    data = {
        "device_id": device_id,
        "device_type": device_type,
        "supported_capabilities": (
            capabilities if capabilities is not None else ["word_count"]
        ),
        "cpu_usage": cpu_usage,
        "cpu_cores": cpu_cores,
        "total_ram": 4 * 1024**3,
        "available_ram": available_ram,
    }
    data.update(extra)
    return data


def register(client, report):
    response = client.post(
        "/workers/register",
        headers=REGISTRATION,
        json={"device": report},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def create_task(
    client,
    task_type="word_count",
    payload=None,
    requirements=None,
    timeout=60,
    attempts=3,
):
    response = client.post(
        "/tasks",
        headers=ADMIN,
        json={
            "task_type": task_type,
            "payload": payload or {"text": "hello kovan"},
            "requirements": requirements or {},
            "timeout_seconds": timeout,
            "max_attempts": attempts,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["task_id"]


def claim(client, token):
    return client.post(
        "/workers/claim",
        headers={"X-Device-Token": token},
    )


def submit(
    client,
    token,
    task,
    *,
    lease_id=None,
    success=True,
    retryable=False,
):
    return client.post(
        f"/workers/tasks/{task['id']}/result",
        headers={"X-Device-Token": token},
        json={
            "lease_id": lease_id or task["lease_id"],
            "success": success,
            "result": {"word_count": 2} if success else None,
            "error": None if success else "temporary failure",
            "retryable": retryable,
        },
    )


def task_info(client, task_id):
    response = client.get(f"/tasks/{task_id}", headers=ADMIN)
    assert response.status_code == 200
    return response.json()


def test_security_and_device_model(client):
    assert client.get("/health").json() == {"status": "ok"}

    response = client.post(
        "/workers/register",
        json={"device": device("pc1")},
    )
    assert response.status_code == 401

    response = client.post(
        "/tasks",
        json={"task_type": "word_count", "payload": {"text": "x"}},
    )
    assert response.status_code == 401

    token = register(client, device("pc1"))
    response = client.post(
        "/workers/heartbeat",
        headers={"X-Device-Token": token},
        json={"device": device("pc1", cpu_usage=15)},
    )
    assert response.status_code == 200

    listed = client.get("/devices", headers=ADMIN)
    assert listed.status_code == 200
    report = listed.json()[0]
    assert report["connection_status"] == "online"
    assert report["cpu_usage"] == 15
    assert report["gpu_information"] is None
    assert report["battery_level"] is None
    assert report["thermal_status"] is None
    assert "token" not in report
    assert "token_hash" not in report


def test_duplicate_registration_cannot_rotate_token(client):
    original = register(client, device("pc1"))
    response = client.post(
        "/workers/register",
        headers=REGISTRATION,
        json={"device": device("pc1")},
    )
    assert response.status_code == 409

    assert claim(client, original).status_code == 204


def test_admin_reset_invalidates_old_token(client):
    old_token = register(client, device("pc1"))
    response = client.post(
        "/devices/pc1/reset-token",
        headers=ADMIN,
    )
    assert response.status_code == 200
    new_token = response.json()["token"]
    assert new_token != old_token
    assert claim(client, old_token).status_code == 401

    response = client.post(
        "/workers/heartbeat",
        headers={"X-Device-Token": new_token},
        json={"device": device("pc1")},
    )
    assert response.status_code == 200


def test_allowlist_and_device_identity(client):
    response = client.post(
        "/tasks",
        headers=ADMIN,
        json={
            "task_type": "shell_exec",
            "payload": {"command": "whoami"},
        },
    )
    assert response.status_code == 422

    response = client.post(
        "/workers/register",
        headers=REGISTRATION,
        json={
            "device": device(
                "esp",
                device_type="microcontroller",
                capabilities=["word_count"],
            )
        },
    )
    assert response.status_code == 422

    token = register(client, device("pc1"))
    response = client.post(
        "/workers/heartbeat",
        headers={"X-Device-Token": token},
        json={"device": device("other-device")},
    )
    assert response.status_code == 403


def test_priority_capability_and_single_active_task(client):
    word_token = register(
        client,
        device("word-pc", capabilities=["word_count"]),
    )
    sha_token = register(
        client,
        device("sha-pc", capabilities=["sha256_file"]),
    )

    first = create_task(client, payload={"text": "first"})
    priority = create_task(
        client,
        payload={"text": "priority"},
        requirements={"priority": 90},
    )
    sha = create_task(
        client,
        task_type="sha256_file",
        payload={"path": "/example/path"},
        requirements={"allowed_device_ids": ["sha-pc"]},
    )

    assert claim(client, sha_token).json()["id"] == sha
    assert claim(client, sha_token).status_code == 204

    taken = claim(client, word_token).json()
    assert taken["id"] == priority
    assert claim(client, word_token).status_code == 204

    assert submit(client, word_token, taken).status_code == 200
    assert claim(client, word_token).json()["id"] == first


def test_old_attempt_cannot_finish_new_attempt_same_device(
    client, db, clock
):
    token = register(client, device("pc1"))
    task_id = create_task(client, timeout=5)

    old = claim(client, token).json()
    clock.advance(5)
    assert db.reap_expired_tasks() == 1

    assert task_info(client, task_id)["status"] == "queued"
    assert claim(client, token).status_code == 204

    clock.advance(1)
    new = claim(client, token).json()
    assert new["attempt_count"] == 2
    assert new["lease_id"] != old["lease_id"]

    assert submit(client, token, old).status_code == 409
    assert submit(client, token, new).status_code == 200
    assert submit(client, token, new).status_code == 200
    assert task_info(client, task_id)["status"] == "completed"


def test_retry_backoff_and_attempt_limit(client, clock):
    token = register(client, device("pc1"))
    task_id = create_task(client, attempts=2)

    first = claim(client, token).json()
    response = submit(
        client,
        token,
        first,
        success=False,
        retryable=True,
    )
    assert response.status_code == 200
    assert task_info(client, task_id)["status"] == "queued"
    assert claim(client, token).status_code == 204

    clock.advance(1)
    second = claim(client, token).json()
    assert second["attempt_count"] == 2

    response = submit(
        client,
        token,
        second,
        success=False,
        retryable=True,
    )
    assert response.status_code == 200
    assert task_info(client, task_id)["status"] == "failed"


def test_timeout_reassigns_after_worker_goes_offline(client, db, clock):
    first_token = register(
        client, device("first", cpu_usage=1)
    )
    second_token = register(
        client, device("second", cpu_usage=60)
    )
    task_id = create_task(client, timeout=5)

    assert claim(client, first_token).json()["id"] == task_id
    clock.advance(36)

    # İkinci worker hâlâ bağlı, ilki offline.
    response = client.post(
        "/workers/heartbeat",
        headers={"X-Device-Token": second_token},
        json={"device": device("second", cpu_usage=60)},
    )
    assert response.status_code == 200

    assert db.reap_expired_tasks() == 1
    clock.advance(1)
    assert claim(client, second_token).json()["id"] == task_id


def test_concurrent_claim_assigns_one_worker(client, db):
    token_one = register(client, device("one", cpu_usage=5))
    token_two = register(client, device("two", cpu_usage=50))
    task_id = create_task(client)

    def attempt(token):
        return db.claim_task(
            token,
            offline_after_seconds=35,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(attempt, [token_one, token_two]))

    assigned = [task for task in claims if task is not None]
    assert len(assigned) == 1
    assert assigned[0]["id"] == task_id
    assert task_info(client, task_id)["attempt_count"] == 1


def test_reset_releases_running_task(client):
    token = register(client, device("pc1"))
    task_id = create_task(client)
    taken = claim(client, token).json()

    response = client.post(
        "/devices/pc1/reset-token",
        headers=ADMIN,
    )
    assert response.status_code == 200
    assert submit(client, token, taken).status_code == 401
    assert task_info(client, task_id)["status"] == "queued"


def test_invalid_payload_and_estimate(client):
    response = client.post(
        "/tasks",
        headers=ADMIN,
        json={
            "task_type": "word_count",
            "payload": {"path": "../secret.txt"},
        },
    )
    assert response.status_code == 400

    response = client.post(
        "/tasks",
        headers=ADMIN,
        json={
            "task_type": "word_count",
            "payload": {"text": "hi"},
            "timeout_seconds": 5,
            "requirements": {"estimated_duration_seconds": 10},
        },
    )
    assert response.status_code == 400
