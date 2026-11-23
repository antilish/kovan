from typing import Any

ALLOWED_TASK_TYPES = frozenset(
    {"sha256_file", "word_count", "pi_monte_carlo", "prime_count"}
)
# Her cihazda (telefon dahil) dosya sistemi olmadan çalışabilen görevler.
PORTABLE_TASK_TYPES = frozenset({"pi_monte_carlo", "prime_count"})
MAX_MC_SAMPLES = 50_000_000
MAX_PRIME_STOP = 50_000_000
MAX_PRIME_WIDTH = 5_000_000
MAX_INLINE_TEXT_CHARS = 100_000
MAX_PATH_CHARS = 4096


class TaskValidationError(ValueError):
    pass


def _validate_path(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_PATH_CHARS
        or "\x00" in value
    ):
        raise TaskValidationError("path must be a non-empty safe string")

    # Controller farklı bir işletim sisteminde olabilir. İki ayırıcıyı da
    # denetlemek, açık traversal girdilerini burada da reddeder.
    if ".." in value.replace("\\", "/").split("/"):
        raise TaskValidationError("path traversal is not allowed")


def _validate_int(payload: dict, key: str, low: int, high: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TaskValidationError(f"'{key}' must be an integer")
    if not low <= value <= high:
        raise TaskValidationError(f"'{key}' must be between {low} and {high}")
    return value


def validate_task_payload(task_type: str, payload: dict[str, Any]) -> None:
    if task_type not in ALLOWED_TASK_TYPES:
        raise TaskValidationError(f"Unsupported task type: {task_type}")

    if not isinstance(payload, dict):
        raise TaskValidationError("payload must be an object")

    if task_type == "sha256_file":
        if set(payload) != {"path"}:
            raise TaskValidationError("sha256_file requires only 'path'")
        _validate_path(payload["path"])
        return

    if task_type == "pi_monte_carlo":
        if set(payload) != {"samples", "seed"}:
            raise TaskValidationError(
                "pi_monte_carlo requires 'samples' and 'seed'"
            )
        _validate_int(payload, "samples", 1, MAX_MC_SAMPLES)
        _validate_int(payload, "seed", 0, 2**31 - 1)
        return

    if task_type == "prime_count":
        if set(payload) != {"start", "stop"}:
            raise TaskValidationError("prime_count requires 'start' and 'stop'")
        start = _validate_int(payload, "start", 0, MAX_PRIME_STOP - 1)
        stop = _validate_int(payload, "stop", start + 1, MAX_PRIME_STOP)
        if stop - start > MAX_PRIME_WIDTH:
            raise TaskValidationError(
                f"prime_count range cannot exceed {MAX_PRIME_WIDTH}"
            )
        return

    if "text" in payload:
        if set(payload) != {"text"}:
            raise TaskValidationError("word_count text requires only 'text'")
        text = payload["text"]
        if not isinstance(text, str) or len(text) > MAX_INLINE_TEXT_CHARS:
            raise TaskValidationError("word_count text is invalid or too large")
        return

    if set(payload) not in ({"path"}, {"path", "encoding"}):
        raise TaskValidationError(
            "word_count requires 'text' or 'path' with optional 'encoding'"
        )

    _validate_path(payload["path"])
    if payload.get("encoding", "utf-8") != "utf-8":
        raise TaskValidationError("Only utf-8 file encoding is supported")
