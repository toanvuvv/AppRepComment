"""Encryption utilities for sensitive fields (cookies, moderator config, etc.)."""

from __future__ import annotations

import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

_ENV_KEY = "APP_ENCRYPTION_KEY"
_ENV_ENVIRONMENT = "APP_ENV"
_CIPHERTEXT_PREFIX = "gAAAAA"
_DEV_DEFAULT_KEY = base64.urlsafe_b64encode(b"\x00" * 32).decode("ascii")


def generate_key() -> str:
    """Generate a new Fernet key, suitable for setting APP_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode("ascii")


def _load_key() -> bytes:
    key = os.environ.get(_ENV_KEY)
    if key:
        return key.encode("ascii") if isinstance(key, str) else key

    env = os.environ.get(_ENV_ENVIRONMENT, "development").lower()
    if env == "production":
        raise RuntimeError(
            f"{_ENV_KEY} is required in production. "
            "Generate one with `python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`."
        )

    logger.warning(
        "%s not set; falling back to an insecure dev-default key. "
        "Do NOT use this in production.",
        _ENV_KEY,
    )
    return _DEV_DEFAULT_KEY.encode("ascii")


def _get_fernet() -> Fernet:
    return Fernet(_load_key())


def encrypt(plain: str | None) -> str | None:
    """Encrypt a plaintext string. Passes None/empty values through unchanged."""
    if plain is None or plain == "":
        return plain
    token = _get_fernet().encrypt(plain.encode("utf-8"))
    return token.decode("ascii")


def decrypt(cipher: str | None) -> str | None:
    """Decrypt a ciphertext string. Passes None/empty values through unchanged."""
    if cipher is None or cipher == "":
        return cipher
    try:
        plain = _get_fernet().decrypt(cipher.encode("ascii"))
    except InvalidToken:
        logger.warning(
            "decrypt() received a value that is not a valid Fernet token; "
            "returning raw value (possible unmigrated plaintext)."
        )
        return cipher
    return plain.decode("utf-8")


class EncryptedString(TypeDecorator):
    """SQLAlchemy column type that transparently encrypts/decrypts string values.

    Backward-compatible: if a stored value is not a valid Fernet token (e.g. a
    row that hasn't been migrated yet), the raw value is returned on read and a
    warning is logged.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:  # type: ignore[override]
        if value is None or value == "":
            return value
        if isinstance(value, str) and value.startswith(_CIPHERTEXT_PREFIX):
            # Already looks like a Fernet token; don't double-encrypt.
            return value
        return encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:  # type: ignore[override]
        if value is None or value == "":
            return value
        try:
            return decrypt(value)
        except InvalidToken:
            logger.warning(
                "EncryptedString: stored value failed decryption; returning raw."
            )
            return value
