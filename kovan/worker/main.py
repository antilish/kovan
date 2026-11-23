import asyncio
import json
import logging
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from common.schemas import TaskClaimResponse
from worker.config import WorkerSettings
from worker.executor import (
    FilePolicy,
    TaskExecutionError,
    execute_task,
)
from worker.probe import DeviceProbe

logger = logging.getLogger(__name__)


class WorkerClient:
    def __init__(self, settings: WorkerSettings) -> None:
        self.settings = settings
        self.file_policy = FilePolicy(
            settings.allowed_dirs,
            max_file_bytes=settings.max_file_bytes,
        )
        self.probe = DeviceProbe(settings)
        self.client = httpx.AsyncClient(
            base_url=settings.controller_url,
            timeout=settings.request_timeout,
        )
        self.token = settings.token or self._load_token()
        self._register_lock = asyncio.Lock()

    def _load_token(self) -> str | None:
        paths = [self.settings.token_file]
        legacy = Path(".kovan_worker_token")
        if legacy != self.settings.token_file:
            paths.append(legacy)

        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue

            if data.get("device_id") != self.settings.device_id:
                continue
            token = data.get("token")
            if isinstance(token, str) and token:
                return token
        return None

    def _save_token(self, token: str) -> None:
        destination = self.settings.token_file
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(parent, 0o700)

        temporary = destination.with_name(
            destination.name + "." + secrets.token_hex(8) + ".tmp"
        )
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "device_id": self.settings.device_id,
                        "token": token,
                    },
                    stream,
                )
            os.replace(temporary, destination)
            if os.name == "posix":
                os.chmod(destination, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    async def ensure_registered(self) -> None:
        if self.token:
            return

        async with self._register_lock:
            if self.token:
                return
            if not self.settings.registration_token:
                raise RuntimeError(
                    "First registration requires KOVAN_REGISTRATION_TOKEN"
                )

            report = self.probe.collect()
            response = await self.client.post(
                "/workers/register",
                headers={
                    "X-Registration-Token":
                        self.settings.registration_token
                },
                json={"device": report.model_dump(mode="json")},
            )
            if response.status_code == 409:
                raise RuntimeError(
                    "Device already exists. Restore its token or ask "
                    "an admin to reset it."
                )
            response.raise_for_status()

            token = response.json()["token"]
            # Kayıt başarılı ama token saklanamazsa yönetici sıfırlaması
            # gerekebilir. Bu hata sessizce gizlenmez.
            self._save_token(token)
            self.token = token
            logger.info(
                "Registered worker device_id=%s",
                self.settings.device_id,
            )

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        await self.ensure_registered()
        headers = dict(kwargs.pop("headers", {}))
        headers["X-Device-Token"] = self.token

        response = await self.client.request(
            method,
            path,
            headers=headers,
            **kwargs,
        )
        if response.status_code == 401:
            # Eski token ile otomatik re-register cihaz ele geçirme açığı
            # oluştururdu. Kayıt denemesi yapılmaz.
            raise RuntimeError(
                "Device token rejected. Restore the token or ask "
                "an admin to reset it."
            )
        return response

    async def heartbeat_once(self) -> None:
        report = self.probe.collect()
        response = await self.request(
            "POST",
            "/workers/heartbeat",
            json={"device": report.model_dump(mode="json")},
        )
        response.raise_for_status()

    async def heartbeat_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.settings.heartbeat_interval,
                )
                continue
            except asyncio.TimeoutError:
                pass

            try:
                await self.heartbeat_once()
            except RuntimeError as exc:
                logger.error("%s", exc)
                stop.set()
                return
            except httpx.HTTPError:
                logger.warning("Heartbeat failed; will retry")
            except Exception:
                logger.exception("Unexpected heartbeat error")

    async def submit_result(
        self,
        task: TaskClaimResponse,
        *,
        success: bool,
        result: Any = None,
        error: str | None = None,
        retryable: bool = False,
    ) -> None:
        body = {
            "lease_id": task.lease_id,
            "success": success,
            "result": result,
            "error": error,
            "retryable": retryable,
        }

        for attempt in range(3):
            try:
                response = await self.request(
                    "POST",
                    f"/workers/tasks/{task.id}/result",
                    json=body,
                )
                if response.status_code == 409:
                    logger.warning(
                        "Task %s result rejected: stale or expired lease",
                        task.id,
                    )
                    return
                response.raise_for_status()
                logger.info(
                    "Submitted task %s result success=%s",
                    task.id,
                    success,
                )
                return
            except httpx.RequestError:
                pass
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise

            if attempt < 2:
                await asyncio.sleep(2 ** attempt)

        logger.warning(
            "Could not submit task %s result after retries",
            task.id,
        )

    async def claim_and_run(self) -> bool:
        response = await self.request("POST", "/workers/claim")
        if response.status_code == 204:
            return False
        response.raise_for_status()

        task = TaskClaimResponse.model_validate(response.json())
        logger.info(
            "Claimed task %s type=%s attempt=%s/%s",
            task.id,
            task.task_type,
            task.attempt_count,
            task.max_attempts,
        )

        try:
            result = await asyncio.to_thread(
                execute_task,
                task.task_type,
                task.payload,
                self.file_policy,
            )
            success = True
            error = None
            retryable = False
        except TaskExecutionError as exc:
            result = None
            success = False
            error = str(exc)
            retryable = False
        except Exception as exc:
            logger.exception("Unexpected execution failure task=%s", task.id)
            result = None
            success = False
            error = f"{type(exc).__name__}: {exc}"
            retryable = True

        await self.submit_result(
            task,
            success=success,
            result=result,
            error=error,
            retryable=retryable,
        )
        return True

    async def claim_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                ran_task = await self.claim_and_run()
            except (httpx.RequestError, httpx.HTTPStatusError):
                logger.warning("Controller unavailable; will retry")
                ran_task = False

            if not ran_task:
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=self.settings.poll_interval,
                    )
                except asyncio.TimeoutError:
                    pass

    async def close(self) -> None:
        await self.client.aclose()


async def run_worker_with(
    settings: WorkerSettings,
    stop: asyncio.Event,
    on_state: Callable[[str], None] | None = None,
) -> None:
    """Worker'ı verilen ayarlarla çalıştırır; stop set edilince durur."""

    def report(state: str) -> None:
        if on_state is not None:
            on_state(state)

    worker = WorkerClient(settings)
    try:
        report("Controller'a bağlanıyor")
        while not stop.is_set():
            try:
                await worker.ensure_registered()
                await worker.heartbeat_once()
                break
            except httpx.RequestError:
                logger.warning(
                    "Controller unavailable during startup; retrying"
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

        if stop.is_set():
            return

        report("Çalışıyor")
        heartbeat_task = asyncio.create_task(
            worker.heartbeat_loop(stop)
        )
        try:
            await worker.claim_loop(stop)
        finally:
            stop.set()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
    finally:
        await worker.close()


async def run_worker() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = WorkerSettings.from_env()
    logger.info(
        "Starting worker device_id=%s controller=%s capabilities=%s",
        settings.device_id,
        settings.controller_url,
        settings.capabilities,
    )
    await run_worker_with(settings, asyncio.Event())


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        logging.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
