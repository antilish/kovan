import hashlib
import secrets


def hash_token(token: str) -> str:
    """Yüksek entropili cihaz token'ının veritabanında tutulacak özeti."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)
