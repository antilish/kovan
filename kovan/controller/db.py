from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.schemas import DeviceReport, DeviceView, TaskRequirements
from common.security import hash_token, new_token
from controller.scheduler import DeviceSnapshot, choose_worker

SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    device_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    capabilities TEXT NOT NULL,
    last_heartbeat REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    profile TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    assigned_worker TEXT,
    lease_expires_at REAL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    timeout_seconds REAL NOT NULL,
    result TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    requirements TEXT NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    available_at REAL NOT NULL DEFAULT 0,
    lease_id TEXT,
    last_finished_lease_id TEXT
);
"""


class InvalidDeviceToken(Exception):
    pass


class DeviceMismatch(Exception):
    pass


@dataclass(frozen=True)
class SubmitResult:
    ok: bool
    reason: str
    status: str | None = None


class Database:
    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Use a file-backed SQLite database")

        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.time
        self.init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _retry_delay(attempt_count: int) -> float:
        return float(min(2 ** min(max(attempt_count - 1, 0), 5), 30))

    def _release_locked(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        now: float,
        reason: str,
    ) -> None:
        attempts = int(row["attempt_count"])
        if attempts >= int(row["max_attempts"]):
            status = "failed"
            available_at = now
        else:
            status = "queued"
            available_at = now + self._retry_delay(attempts)

        conn.execute(
            """
            UPDATE tasks
            SET status = ?,
                assigned_worker = NULL,
                lease_expires_at = NULL,
                lease_id = NULL,
                last_finished_lease_id = NULL,
                result = NULL,
                error = ?,
                available_at = ?,
                updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (status, reason, available_at, now, int(row["id"])),
        )

    def init(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)

            try:
                conn.execute("BEGIN IMMEDIATE")

                version = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
                if version > 4:
                    raise RuntimeError(
                        "Database was created by a newer KOVAN version"
                    )

                worker_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(workers)")
                }
                if "profile" not in worker_columns:
                    conn.execute(
                        "ALTER TABLE workers "
                        "ADD COLUMN profile TEXT NOT NULL DEFAULT '{}'"
                    )

                task_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(tasks)")
                }
                additions = {
                    "requirements": "TEXT NOT NULL DEFAULT '{}'",
                    "priority": "INTEGER NOT NULL DEFAULT 0",
                    "available_at": "REAL NOT NULL DEFAULT 0",
                    "lease_id": "TEXT",
                    "last_finished_lease_id": "TEXT",
                }
                for name, definition in additions.items():
                    if name not in task_columns:
                        conn.execute(
                            f"ALTER TABLE tasks ADD COLUMN {name} {definition}"
                        )

                # v0.1 çalışan görevlerinde deneme kimliği yoktur. Sonuçları
                # güvenle eşleştirilemeyeceği için bu lease'leri bırakıyoruz.
                now = float(self.clock())
                old_running = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'running'
                      AND (lease_id IS NULL OR lease_id = '')
                    """
                ).fetchall()
                for row in old_running:
                    self._release_locked(
                        conn, row, now, "old lease migrated; retry scheduled"
                    )

                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tasks_ready
                    ON tasks(status, available_at, priority, created_at, id)
                    """
                )
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_running_worker
                    ON tasks(assigned_worker)
                    WHERE status = 'running'
                      AND assigned_worker IS NOT NULL
                    """
                )
                conn.execute("PRAGMA user_version = 4")
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _profile_json(report: DeviceReport) -> str:
        profile = report.model_dump(
            mode="json",
            exclude={"device_id", "supported_capabilities"},
        )
        return json.dumps(profile, ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _report_from_row(row: sqlite3.Row) -> DeviceReport:
        profile = json.loads(row["profile"]) or {}
        return DeviceReport.model_validate(
            {
                **profile,
                "device_id": row["device_id"],
                "supported_capabilities": json.loads(
                    row["capabilities"]
                ),
            }
        )

    @staticmethod
    def _device_for_token(
        conn: sqlite3.Connection, token: str
    ) -> str | None:
        row = conn.execute(
            "SELECT device_id FROM workers WHERE token_hash = ?",
            (hash_token(token),),
        ).fetchone()
        return str(row["device_id"]) if row is not None else None

    @staticmethod
    def _task_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        public_columns = (
            "id",
            "task_type",
            "status",
            "assigned_worker",
            "lease_expires_at",
            "attempt_count",
            "max_attempts",
            "timeout_seconds",
            "priority",
            "available_at",
            "error",
            "created_at",
            "updated_at",
        )
        data = {name: row[name] for name in public_columns}
        data["payload"] = json.loads(row["payload"])
        data["requirements"] = json.loads(row["requirements"])
        data["result"] = (
            json.loads(row["result"])
            if row["result"] is not None
            else None
        )
        # lease_id yalnızca claim cevabında verilir.
        return data

    def register_device(
        self, report: DeviceReport, token_hash: str
    ) -> bool:
        now = float(self.clock())
        with self._connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                exists = conn.execute(
                    "SELECT 1 FROM workers WHERE device_id = ?",
                    (report.device_id,),
                ).fetchone()
                if exists is not None:
                    conn.rollback()
                    return False

                conn.execute(
                    """
                    INSERT INTO workers(
                        device_id, token_hash, capabilities,
                        last_heartbeat, created_at, updated_at, profile
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report.device_id,
                        token_hash,
                        json.dumps(report.supported_capabilities),
                        now,
                        now,
                        now,
                        self._profile_json(report),
                    ),
                )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    def heartbeat(self, token: str, report: DeviceReport) -> None:
        now = float(self.clock())
        with self._connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                device_id = self._device_for_token(conn, token)
                if device_id is None:
                    raise InvalidDeviceToken()
                if device_id != report.device_id:
                    raise DeviceMismatch()

                conn.execute(
                    """
                    UPDATE workers
                    SET capabilities = ?,
                        profile = ?,
                        last_heartbeat = ?,
                        updated_at = ?
                    WHERE device_id = ?
                    """,
                    (
                        json.dumps(report.supported_capabilities),
                        self._profile_json(report),
                        now,
                        now,
                        device_id,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def reset_device_token(
        self, device_id: str, token_hash: str
    ) -> bool:
        now = float(self.clock())
        with self._connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    """
                    UPDATE workers
                    SET token_hash = ?,
                        last_heartbeat = 0,
                        updated_at = ?
                    WHERE device_id = ?
                    """,
                    (token_hash, now, device_id),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    return False

                running = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'running' AND assigned_worker = ?
                    """,
                    (device_id,),
                ).fetchall()
                for row in running:
                    self._release_locked(
                        conn,
                        row,
                        now,
                        "device token reset; retry scheduled",
                    )

                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    def delete_device(self, device_id: str) -> bool:
        now = float(self.clock())
        with self._connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                running = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'running' AND assigned_worker = ?
                    """,
                    (device_id,),
                ).fetchall()
                for row in running:
                    self._release_locked(
                        conn, row, now, "device removed; retry scheduled"
                    )
                cur = conn.execute(
                    "DELETE FROM workers WHERE device_id = ?", (device_id,)
                )
                conn.commit()
                return cur.rowcount == 1
            except Exception:
                conn.rollback()
                raise

    def create_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        requirements: TaskRequirements,
        timeout_seconds: float,
        max_attempts: int,
    ) -> int:
        now = float(self.clock())
        with self._connection() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO tasks(
                        task_type, payload, status, assigned_worker,
                        lease_expires_at, attempt_count, max_attempts,
                        timeout_seconds, result, error, created_at,
                        updated_at, requirements, priority, available_at,
                        lease_id, last_finished_lease_id
                    )
                    VALUES(
                        ?, ?, 'queued', NULL,
                        NULL, 0, ?,
                        ?, NULL, NULL, ?,
                        ?, ?, ?, ?,
                        NULL, NULL
                    )
                    """,
                    (
                        task_type,
                        json.dumps(payload, ensure_ascii=False),
                        max_attempts,
                        timeout_seconds,
                        now,
                        now,
                        json.dumps(
                            requirements.model_dump(mode="json"),
                            ensure_ascii=False,
                        ),
                        requirements.priority,
                        now,
                    ),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                if conn.in_transaction:
                    conn.rollback()

    def _reap_expired_locked(
        self, conn: sqlite3.Connection, now: float
    ) -> int:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= ?
            """,
            (now,),
        ).fetchall()
        for row in rows:
            self._release_locked(
                conn, row, now, "lease expired; retry scheduled"
            )
        return len(rows)

    def reap_expired_tasks(self) -> int:
        now = float(self.clock())
        with self._connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                count = self._reap_expired_locked(conn, now)
                conn.commit()
                return count
            except Exception:
                conn.rollback()
                raise

    def claim_task(
        self,
        token: str,
        *,
        offline_after_seconds: float,
    ) -> dict[str, Any] | None:
        now = float(self.clock())
        with self._connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                device_id = self._device_for_token(conn, token)
                if device_id is None:
                    raise InvalidDeviceToken()

                self._reap_expired_locked(conn, now)

                # Poll eden cihazın bağlantısı canlıdır. Kaynak ölçümleri
                # heartbeat'ten gelir; claim bunları değiştirmez.
                conn.execute(
                    """
                    UPDATE workers
                    SET last_heartbeat = ?, updated_at = ?
                    WHERE device_id = ?
                    """,
                    (now, now, device_id),
                )

                worker_rows = conn.execute(
                    "SELECT * FROM workers"
                ).fetchall()
                busy = {
                    row["assigned_worker"]
                    for row in conn.execute(
                        """
                        SELECT assigned_worker FROM tasks
                        WHERE status = 'running'
                          AND assigned_worker IS NOT NULL
                        """
                    )
                }
                devices = [
                    DeviceSnapshot(
                        report=self._report_from_row(row),
                        last_heartbeat=float(row["last_heartbeat"]),
                        busy=row["device_id"] in busy,
                    )
                    for row in worker_rows
                ]

                if device_id in busy:
                    conn.commit()
                    return None

                queued = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'queued'
                      AND available_at <= ?
                    ORDER BY priority DESC, created_at ASC, id ASC
                    """,
                    (now,),
                )

                for row in queued:
                    requirements = TaskRequirements.model_validate(
                        json.loads(row["requirements"])
                    )
                    chosen = choose_worker(
                        devices,
                        str(row["task_type"]),
                        requirements,
                        now=now,
                        offline_after_seconds=offline_after_seconds,
                    )
                    if chosen != device_id:
                        continue

                    lease_id = new_token()
                    cur = conn.execute(
                        """
                        UPDATE tasks
                        SET status = 'running',
                            assigned_worker = ?,
                            lease_id = ?,
                            lease_expires_at = ?,
                            attempt_count = attempt_count + 1,
                            error = NULL,
                            updated_at = ?
                        WHERE id = ?
                          AND status = 'queued'
                          AND available_at <= ?
                        """,
                        (
                            device_id,
                            lease_id,
                            now + float(row["timeout_seconds"]),
                            now,
                            int(row["id"]),
                            now,
                        ),
                    )
                    if cur.rowcount != 1:
                        raise RuntimeError("Atomic task claim failed")

                    updated = conn.execute(
                        "SELECT * FROM tasks WHERE id = ?",
                        (int(row["id"]),),
                    ).fetchone()
                    task = self._task_to_dict(updated)
                    task["lease_id"] = lease_id
                    conn.commit()
                    return task

                conn.commit()
                return None
            except Exception:
                conn.rollback()
                raise

    def submit_result(
        self,
        token: str,
        task_id: int,
        lease_id: str,
        *,
        success: bool,
        result: Any,
        error: str | None,
        retryable: bool,
    ) -> SubmitResult:
        now = float(self.clock())
        result_json = None
        if success:
            result_json = json.dumps(
                result, ensure_ascii=False, allow_nan=False
            )
            if len(result_json.encode("utf-8")) > 262_144:
                return SubmitResult(False, "result_too_large")

        with self._connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                device_id = self._device_for_token(conn, token)
                if device_id is None:
                    raise InvalidDeviceToken()

                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return SubmitResult(False, "not_found")

                if (
                    row["status"] in {"completed", "failed"}
                    and row["assigned_worker"] == device_id
                    and row["last_finished_lease_id"] == lease_id
                ):
                    conn.commit()
                    return SubmitResult(
                        True, "already_accepted", str(row["status"])
                    )

                if (
                    row["status"] != "running"
                    or row["assigned_worker"] != device_id
                    or row["lease_id"] != lease_id
                ):
                    conn.rollback()
                    return SubmitResult(False, "stale_or_wrong_lease")

                if float(row["lease_expires_at"]) <= now:
                    self._release_locked(
                        conn,
                        row,
                        now,
                        "lease expired; late result rejected",
                    )
                    conn.commit()
                    return SubmitResult(False, "expired")

                if (
                    not success
                    and retryable
                    and int(row["attempt_count"]) < int(row["max_attempts"])
                ):
                    self._release_locked(
                        conn,
                        row,
                        now,
                        error or "retryable worker failure",
                    )
                    conn.commit()
                    return SubmitResult(True, "retry_scheduled", "queued")

                status = "completed" if success else "failed"
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?,
                        result = ?,
                        error = ?,
                        lease_expires_at = NULL,
                        lease_id = NULL,
                        last_finished_lease_id = ?,
                        updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (
                        status,
                        result_json,
                        None if success else (error or "worker failure"),
                        lease_id,
                        now,
                        task_id,
                    ),
                )
                conn.commit()
                return SubmitResult(True, "accepted", status)
            except Exception:
                conn.rollback()
                raise

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return self._task_to_dict(row) if row is not None else None

    def list_tasks(
        self, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connection() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            return [self._task_to_dict(row) for row in rows]

    def list_devices(
        self, *, offline_after_seconds: float
    ) -> list[DeviceView]:
        now = float(self.clock())
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM workers ORDER BY device_id"
            ).fetchall()

        devices = []
        for row in rows:
            report = self._report_from_row(row)
            last_heartbeat = float(row["last_heartbeat"])
            online = (
                last_heartbeat > 0
                and now - last_heartbeat <= offline_after_seconds
            )
            devices.append(
                DeviceView.model_validate(
                    {
                        **report.model_dump(mode="python"),
                        "connection_status": (
                            "online" if online else "offline"
                        ),
                        "last_heartbeat": last_heartbeat,
                    }
                )
            )
        return devices
