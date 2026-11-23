import codecs
import hashlib
import math
import os
import random
import stat
import time
from pathlib import Path
from typing import BinaryIO

from common.tasks import TaskValidationError, validate_task_payload


class TaskExecutionError(Exception):
    pass


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if is_junction is not None else False


class FilePolicy:
    def __init__(
        self,
        allowed_dirs: tuple[Path, ...],
        *,
        max_file_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        if not allowed_dirs or max_file_bytes < 1:
            raise ValueError("A directory and positive size limit are required")

        roots: list[Path] = []
        for directory in allowed_dirs:
            if not directory.is_absolute():
                raise ValueError("Allowed directories must be absolute")
            if _is_link_or_junction(directory) or not directory.is_dir():
                raise ValueError(
                    "Allowed directories must exist and must not be links"
                )
            root = directory.resolve(strict=True)
            if root == Path(root.anchor):
                raise ValueError("A filesystem root cannot be an allowed directory")
            roots.append(root)

        self.roots = tuple(roots)
        self.max_file_bytes = max_file_bytes

    def _wrap_regular_file(self, fd: int) -> BinaryIO:
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise TaskExecutionError("Only regular files are permitted")
            if info.st_size > self.max_file_bytes:
                raise TaskExecutionError("File exceeds configured size limit")
            return os.fdopen(fd, "rb")
        except Exception:
            os.close(fd)
            raise

    def _open_posix(self, root: Path, parts: tuple[str, ...]) -> BinaryIO:
        if (
            not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY")
            or os.open not in os.supports_dir_fd
        ):
            raise TaskExecutionError(
                "Secure file access is unavailable on this platform"
            )

        directory_flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        file_flags = (
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )

        directory_fd = os.open(root, directory_flags)
        try:
            for part in parts[:-1]:
                next_fd = os.open(
                    part,
                    directory_flags,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd

            file_fd = os.open(
                parts[-1],
                file_flags,
                dir_fd=directory_fd,
            )
        finally:
            os.close(directory_fd)

        return self._wrap_regular_file(file_fd)

    def _open_windows(
        self,
        root: Path,
        parts: tuple[str, ...],
    ) -> BinaryIO:
        current = root
        for part in parts:
            if ":" in part:
                raise TaskExecutionError(
                    "Windows alternate data streams are not permitted"
                )
            current = current / part
            if _is_link_or_junction(current):
                raise TaskExecutionError(
                    "Symlinks and junctions are not permitted"
                )

        if current.is_reserved():
            raise TaskExecutionError("Reserved path is not permitted")

        fd = os.open(
            current,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        return self._wrap_regular_file(fd)

    def open_read(self, raw_path: str) -> BinaryIO:
        if "\x00" in raw_path:
            raise TaskExecutionError("Invalid file path")

        path = Path(raw_path)
        if not path.is_absolute():
            raise TaskExecutionError("File path must be absolute")
        if ".." in path.parts:
            raise TaskExecutionError("Path traversal is not permitted")

        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise TaskExecutionError(
                "File does not exist or cannot be resolved"
            ) from exc

        for root in self.roots:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue

            if not relative.parts:
                raise TaskExecutionError("A directory is not a file")
            if not resolved.is_relative_to(root):
                raise TaskExecutionError(
                    "Path escapes the allowed directory"
                )

            try:
                if os.name == "posix":
                    return self._open_posix(root, relative.parts)
                if os.name == "nt":
                    return self._open_windows(root, relative.parts)
            except OSError as exc:
                raise TaskExecutionError(
                    f"File cannot be opened safely: {exc}"
                ) from exc

            raise TaskExecutionError(
                "Secure file access is unavailable on this platform"
            )

        raise TaskExecutionError("Path is outside allowed directories")


def _word_count_file(
    file_obj: BinaryIO,
    max_file_bytes: int,
) -> dict[str, int]:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    byte_count = 0
    word_count = 0
    char_count = 0
    in_word = False

    def consume(text: str) -> None:
        nonlocal word_count, char_count, in_word
        for char in text:
            char_count += 1
            if char.isspace():
                in_word = False
            elif not in_word:
                word_count += 1
                in_word = True

    while True:
        chunk = file_obj.read(64 * 1024)
        if not chunk:
            break
        byte_count += len(chunk)
        if byte_count > max_file_bytes:
            raise TaskExecutionError("File exceeds configured size limit")
        consume(decoder.decode(chunk))

    consume(decoder.decode(b"", final=True))
    return {"word_count": word_count, "char_count": char_count}


def _pi_monte_carlo(payload: dict) -> dict:
    samples = payload["samples"]
    rnd = random.Random(payload["seed"]).random
    started = time.perf_counter()
    inside = 0
    for _ in range(samples):
        x = rnd()
        y = rnd()
        if x * x + y * y <= 1.0:
            inside += 1
    return {
        "inside": inside,
        "samples": samples,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _prime_count(payload: dict) -> dict:
    start, stop = payload["start"], payload["stop"]
    started = time.perf_counter()

    limit = math.isqrt(stop) + 1
    small = bytearray([1]) * (limit + 1)
    small[0] = 0
    if limit >= 1:
        small[1] = 0
    for i in range(2, math.isqrt(limit) + 1):
        if small[i]:
            small[i * i :: i] = bytes(len(range(i * i, limit + 1, i)))

    segment = bytearray([1]) * (stop - start)
    for p in range(2, limit + 1):
        if not small[p]:
            continue
        first = max(p * p, ((start + p - 1) // p) * p)
        if first >= stop:
            continue
        segment[first - start :: p] = bytes(len(range(first - start, stop - start, p)))
    for n in (0, 1):
        if start <= n < stop:
            segment[n - start] = 0

    return {
        "count": sum(segment),
        "start": start,
        "stop": stop,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def execute_task(
    task_type: str,
    payload: dict,
    file_policy: FilePolicy,
) -> dict:
    try:
        validate_task_payload(task_type, payload)
    except TaskValidationError as exc:
        raise TaskExecutionError(str(exc)) from exc

    if task_type == "pi_monte_carlo":
        return _pi_monte_carlo(payload)

    if task_type == "prime_count":
        return _prime_count(payload)

    if task_type == "sha256_file":
        digest = hashlib.sha256()
        byte_count = 0
        with file_policy.open_read(payload["path"]) as file_obj:
            while True:
                chunk = file_obj.read(64 * 1024)
                if not chunk:
                    break
                byte_count += len(chunk)
                if byte_count > file_policy.max_file_bytes:
                    raise TaskExecutionError(
                        "File exceeds configured size limit"
                    )
                digest.update(chunk)

        return {
            "sha256": digest.hexdigest(),
            "size": byte_count,
            "path": payload["path"],
        }

    if task_type == "word_count":
        if "text" in payload:
            text = payload["text"]
            return {
                "word_count": len(text.split()),
                "char_count": len(text),
            }

        try:
            with file_policy.open_read(payload["path"]) as file_obj:
                return _word_count_file(
                    file_obj,
                    file_policy.max_file_bytes,
                )
        except UnicodeError as exc:
            raise TaskExecutionError(
                "File is not valid UTF-8"
            ) from exc

    raise TaskExecutionError("Unsupported task type")
