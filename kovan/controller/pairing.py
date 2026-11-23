"""Kısa ömürlü, tek kullanımlık eşleştirme kodları (telefon vb. için)."""

import secrets
import threading
import time
from collections import deque
from collections.abc import Callable

# Karışan karakterler (I, O, 0, 1) yok.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class PairingStore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        ttl_seconds: float = 300.0,
        max_failures: int = 10,
        failure_window_seconds: float = 60.0,
    ) -> None:
        self._clock = clock or time.time
        self.ttl_seconds = ttl_seconds
        self._max_failures = max_failures
        self._window = failure_window_seconds
        self._codes: dict[str, float] = {}
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()

    @staticmethod
    def _normalize(code: str) -> str:
        return code.strip().upper().replace("-", "").replace(" ", "")

    def create(self) -> str:
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        now = float(self._clock())
        with self._lock:
            self._codes = {
                key: expiry
                for key, expiry in self._codes.items()
                if expiry > now
            }
            self._codes[code] = now + self.ttl_seconds
        return f"{code[:4]}-{code[4:]}"

    def consume(self, code: str) -> str:
        """'ok', 'invalid' veya 'limited' döndürür."""
        normalized = self._normalize(code)
        now = float(self._clock())
        with self._lock:
            while self._failures and now - self._failures[0] > self._window:
                self._failures.popleft()
            if len(self._failures) >= self._max_failures:
                return "limited"

            expiry = self._codes.pop(normalized, None)
            if expiry is None or expiry <= now:
                self._failures.append(now)
                return "invalid"
            return "ok"
