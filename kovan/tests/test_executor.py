import hashlib

import pytest

from worker.executor import (
    FilePolicy,
    TaskExecutionError,
    execute_task,
)


def policy(directory):
    return FilePolicy((directory.resolve(),))


def test_hash_and_file_word_count(tmp_path):
    file_path = tmp_path / "text.txt"
    data = "Merhaba KOVAN\nikinci satır".encode("utf-8")
    file_path.write_bytes(data)

    sha = execute_task(
        "sha256_file",
        {"path": str(file_path)},
        policy(tmp_path),
    )
    assert sha["sha256"] == hashlib.sha256(data).hexdigest()
    assert sha["size"] == len(data)

    words = execute_task(
        "word_count",
        {"path": str(file_path)},
        policy(tmp_path),
    )
    assert words["word_count"] == 4
    assert words["char_count"] == len(data.decode("utf-8"))


def test_inline_text_and_allowlist(tmp_path):
    assert execute_task(
        "word_count",
        {"text": "one two"},
        policy(tmp_path),
    )["word_count"] == 2

    with pytest.raises(TaskExecutionError):
        execute_task(
            "shell",
            {"command": "whoami"},
            policy(tmp_path),
        )


def test_outside_path_and_traversal_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    guarded = policy(allowed)

    with pytest.raises(TaskExecutionError):
        execute_task(
            "sha256_file",
            {"path": str(secret)},
            guarded,
        )

    with pytest.raises(TaskExecutionError):
        execute_task(
            "sha256_file",
            {"path": str(allowed / ".." / "secret.txt")},
            guarded,
        )


def test_symlink_rejected_even_if_target_is_inside_root(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("hello", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this machine")

    with pytest.raises(TaskExecutionError):
        execute_task(
            "sha256_file",
            {"path": str(link)},
            policy(tmp_path),
        )


def test_size_limit_and_utf8(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_bytes(b"abcdef")

    limited = FilePolicy(
        (tmp_path.resolve(),),
        max_file_bytes=3,
    )
    with pytest.raises(TaskExecutionError):
        execute_task(
            "sha256_file",
            {"path": str(file_path)},
            limited,
        )

    file_path.write_bytes(b"\xff")
    with pytest.raises(TaskExecutionError):
        execute_task(
            "word_count",
            {"path": str(file_path)},
            policy(tmp_path),
        )


def test_prime_count_matches_known_values(tmp_path):
    first = execute_task("prime_count", {"start": 0, "stop": 1_000_000}, policy(tmp_path))
    second = execute_task(
        "prime_count", {"start": 1_000_000, "stop": 2_000_000}, policy(tmp_path)
    )
    assert first["count"] == 78498
    assert first["count"] + second["count"] == 148933

    tiny = execute_task("prime_count", {"start": 0, "stop": 3}, policy(tmp_path))
    assert tiny["count"] == 1  # yalnızca 2


def test_pi_monte_carlo_estimates_pi_and_is_deterministic(tmp_path):
    payload = {"samples": 200_000, "seed": 42}
    first = execute_task("pi_monte_carlo", payload, policy(tmp_path))
    second = execute_task("pi_monte_carlo", payload, policy(tmp_path))
    assert first["inside"] == second["inside"]
    assert 3.12 < 4 * first["inside"] / first["samples"] < 3.17


def test_portable_task_payload_validation(tmp_path):
    for task_type, payload in [
        ("pi_monte_carlo", {"samples": 0, "seed": 1}),
        ("pi_monte_carlo", {"samples": 10**9, "seed": 1}),
        ("pi_monte_carlo", {"samples": 5}),
        ("prime_count", {"start": 10, "stop": 10}),
        ("prime_count", {"start": 0, "stop": 6_000_000}),
        ("prime_count", {"start": True, "stop": 10}),
    ]:
        with pytest.raises(TaskExecutionError):
            execute_task(task_type, payload, policy(tmp_path))
