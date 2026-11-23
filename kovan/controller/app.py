import asyncio
import logging
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse

from common.schemas import (
    DeviceView,
    TaskClaimResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskResultRequest,
    WorkerHeartbeatRequest,
    WorkerPairRequest,
    WorkerRegisterRequest,
    WorkerRegisterResponse,
)
from common.security import hash_token, new_token
from common.tasks import TaskValidationError, validate_task_payload
from controller.config import ControllerSettings
from controller.pairing import PairingStore
from controller.phone_page import PHONE_CSP, PHONE_HTML
from controller.db import (
    Database,
    DeviceMismatch,
    InvalidDeviceToken,
)

logger = logging.getLogger(__name__)


def create_app(
    settings: ControllerSettings | None = None,
    *,
    clock: Callable[[], float] | None = None,
) -> FastAPI:
    settings = settings or ControllerSettings.from_env()
    db = Database(settings.db_path, clock=clock)
    pairing = PairingStore(clock=clock)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()

        async def reaper_loop() -> None:
            while not stop.is_set():
                try:
                    await asyncio.to_thread(db.reap_expired_tasks)
                except Exception:
                    logger.exception("Task reaper failed")

                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=settings.reaper_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(reaper_loop())
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(
        title="KOVAN Controller",
        version="0.4.0",
        lifespan=lifespan,
    )
    app.state.db = db
    app.state.settings = settings

    def require_admin(
        x_admin_token: str | None = Header(
            default=None, alias="X-Admin-Token"
        ),
    ) -> None:
        if x_admin_token is None or not secrets.compare_digest(
            x_admin_token, settings.admin_token
        ):
            raise HTTPException(status_code=401, detail="Invalid admin token")

    def require_registration(
        x_registration_token: str | None = Header(
            default=None, alias="X-Registration-Token"
        ),
    ) -> None:
        if x_registration_token is None or not secrets.compare_digest(
            x_registration_token, settings.registration_token
        ):
            raise HTTPException(
                status_code=401, detail="Invalid registration token"
            )

    def require_device_token(
        x_device_token: str | None = Header(
            default=None, alias="X-Device-Token"
        ),
    ) -> str:
        if not x_device_token:
            raise HTTPException(status_code=401, detail="Missing device token")
        return x_device_token

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/workers/register",
        response_model=WorkerRegisterResponse,
    )
    def register_worker(
        req: WorkerRegisterRequest,
        _: None = Depends(require_registration),
    ) -> WorkerRegisterResponse:
        token = new_token()
        created = db.register_device(req.device, hash_token(token))
        if not created:
            raise HTTPException(
                status_code=409,
                detail="Device already registered; use existing token "
                "or ask an admin to reset it",
            )
        return WorkerRegisterResponse(
            device_id=req.device.device_id,
            token=token,
        )

    @app.post("/pairing-codes")
    def create_pairing_code(_: None = Depends(require_admin)) -> dict:
        return {
            "code": pairing.create(),
            "expires_in": int(pairing.ttl_seconds),
        }

    @app.post("/workers/pair", response_model=WorkerRegisterResponse)
    def pair_worker(req: WorkerPairRequest) -> WorkerRegisterResponse:
        outcome = pairing.consume(req.code)
        if outcome == "limited":
            raise HTTPException(
                status_code=429,
                detail="Too many attempts; try again in a minute",
            )
        if outcome != "ok":
            raise HTTPException(
                status_code=401, detail="Invalid or expired pairing code"
            )

        token = new_token()
        if not db.register_device(req.device, hash_token(token)):
            raise HTTPException(
                status_code=409, detail="Device already registered"
            )
        return WorkerRegisterResponse(
            device_id=req.device.device_id, token=token
        )

    @app.get("/phone", response_class=HTMLResponse, include_in_schema=False)
    def phone_page() -> HTMLResponse:
        return HTMLResponse(
            PHONE_HTML,
            headers={
                "Content-Security-Policy": PHONE_CSP,
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.post("/workers/heartbeat")
    def heartbeat(
        req: WorkerHeartbeatRequest,
        token: str = Depends(require_device_token),
    ) -> dict[str, str]:
        try:
            db.heartbeat(token, req.device)
        except InvalidDeviceToken as exc:
            raise HTTPException(
                status_code=401, detail="Invalid device token"
            ) from exc
        except DeviceMismatch as exc:
            raise HTTPException(
                status_code=403, detail="Device ID does not match token"
            ) from exc
        return {"status": "ok"}

    @app.post(
        "/workers/claim",
        response_model=TaskClaimResponse | None,
    )
    def claim(token: str = Depends(require_device_token)):
        try:
            task = db.claim_task(
                token,
                offline_after_seconds=settings.device_offline_seconds,
            )
        except InvalidDeviceToken as exc:
            raise HTTPException(
                status_code=401, detail="Invalid device token"
            ) from exc

        if task is None:
            return Response(status_code=204)
        return TaskClaimResponse(
            id=task["id"],
            task_type=task["task_type"],
            payload=task["payload"],
            timeout_seconds=task["timeout_seconds"],
            attempt_count=task["attempt_count"],
            max_attempts=task["max_attempts"],
            lease_id=task["lease_id"],
        )

    @app.post("/workers/tasks/{task_id}/result")
    def submit_result(
        task_id: int,
        req: TaskResultRequest,
        token: str = Depends(require_device_token),
    ) -> dict:
        try:
            outcome = db.submit_result(
                token,
                task_id,
                req.lease_id,
                success=req.success,
                result=req.result,
                error=req.error,
                retryable=req.retryable,
            )
        except InvalidDeviceToken as exc:
            raise HTTPException(
                status_code=401, detail="Invalid device token"
            ) from exc

        if not outcome.ok:
            if outcome.reason == "not_found":
                raise HTTPException(status_code=404, detail="Task not found")
            if outcome.reason == "result_too_large":
                raise HTTPException(status_code=413, detail="Result too large")
            raise HTTPException(
                status_code=409,
                detail=f"Result rejected: {outcome.reason}",
            )
        return {"task_id": task_id, "status": outcome.status}

    @app.post("/tasks", response_model=TaskCreateResponse)
    def create_task(
        req: TaskCreateRequest,
        _: None = Depends(require_admin),
    ) -> TaskCreateResponse:
        try:
            validate_task_payload(req.task_type, req.payload)
        except TaskValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        timeout = (
            req.timeout_seconds
            if req.timeout_seconds is not None
            else settings.default_task_timeout_seconds
        )
        max_attempts = (
            req.max_attempts
            if req.max_attempts is not None
            else settings.default_max_attempts
        )

        estimate = req.requirements.estimated_duration_seconds
        if estimate is not None and estimate > timeout:
            raise HTTPException(
                status_code=400,
                detail="Estimated duration exceeds task timeout",
            )

        task_id = db.create_task(
            req.task_type,
            req.payload,
            req.requirements,
            timeout,
            max_attempts,
        )
        return TaskCreateResponse(task_id=task_id, status="queued")

    @app.get("/tasks", dependencies=[Depends(require_admin)])
    def list_tasks(
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if status is not None and status not in {
            "queued", "running", "completed", "failed"
        }:
            raise HTTPException(status_code=400, detail="Invalid status")
        if not 1 <= limit <= 1000:
            raise HTTPException(
                status_code=400,
                detail="limit must be between 1 and 1000",
            )
        return db.list_tasks(status=status, limit=limit)

    @app.get("/tasks/{task_id}", dependencies=[Depends(require_admin)])
    def get_task(task_id: int) -> dict:
        task = db.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.get(
        "/devices",
        response_model=list[DeviceView],
        dependencies=[Depends(require_admin)],
    )
    @app.get(
        "/workers",
        response_model=list[DeviceView],
        dependencies=[Depends(require_admin)],
        include_in_schema=False,
    )
    def list_devices() -> list[DeviceView]:
        return db.list_devices(
            offline_after_seconds=settings.device_offline_seconds
        )

    @app.delete("/devices/{device_id}", status_code=204)
    def delete_device(
        device_id: str,
        _: None = Depends(require_admin),
    ) -> Response:
        if not db.delete_device(device_id):
            raise HTTPException(status_code=404, detail="Device not found")
        return Response(status_code=204)

    @app.post(
        "/devices/{device_id}/reset-token",
        response_model=WorkerRegisterResponse,
    )
    def reset_device_token(
        device_id: str,
        _: None = Depends(require_admin),
    ) -> WorkerRegisterResponse:
        token = new_token()
        if not db.reset_device_token(device_id, hash_token(token)):
            raise HTTPException(status_code=404, detail="Device not found")
        return WorkerRegisterResponse(device_id=device_id, token=token)

    return app
