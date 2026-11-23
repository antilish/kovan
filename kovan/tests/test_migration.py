import json
import sqlite3

from fastapi.testclient import TestClient

from common.security import hash_token
from controller.app import create_app
from tests.conftest import ADMIN_TOKEN, REGISTRATION_TOKEN


def test_existing_v01_database_migrates_without_losing_records(
    controller_settings,
    clock,
):
    path = controller_settings.db_path

    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE workers (
                device_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL,
                capabilities TEXT NOT NULL,
                last_heartbeat REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'queued', 'running', 'completed', 'failed'
                    )
                ),
                assigned_worker TEXT,
                lease_expires_at REAL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL,
                timeout_seconds REAL NOT NULL,
                result TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO workers VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "old-pc",
                hash_token("old-device-token"),
                json.dumps(["word_count"]),
                clock.now(),
                clock.now(),
                clock.now(),
            ),
        )
        conn.execute(
            """
            INSERT INTO tasks(
                id, task_type, payload, status, assigned_worker,
                lease_expires_at, attempt_count, max_attempts,
                timeout_seconds, result, error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                123,
                "word_count",
                json.dumps({"text": "old task"}),
                "running",
                "old-pc",
                clock.now() + 100,
                1,
                3,
                60,
                None,
                None,
                clock.now(),
                clock.now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    app = create_app(controller_settings, clock=clock.now)
    with TestClient(app) as client:
        response = client.get(
            "/tasks/123",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        assert response.json()["attempt_count"] == 1
        assert response.json()["payload"] == {"text": "old task"}

        # Eski token özeti korundu; yeni rapor formatıyla kullanılabilir.
        response = client.post(
            "/workers/heartbeat",
            headers={"X-Device-Token": "old-device-token"},
            json={
                "device": {
                    "device_id": "old-pc",
                    "supported_capabilities": ["word_count"],
                    "cpu_cores": 2,
                    "cpu_usage": 5,
                    "total_ram": 1024**3,
                    "available_ram": 512 * 1024**2,
                }
            },
        )
        assert response.status_code == 200

        clock.advance(1)
        response = client.post(
            "/workers/claim",
            headers={"X-Device-Token": "old-device-token"},
        )
        assert response.status_code == 200
        assert response.json()["id"] == 123
        assert response.json()["attempt_count"] == 2

        # Yönetici ve kayıt token'ları birbirine karışmadı.
        assert ADMIN_TOKEN != REGISTRATION_TOKEN
