"""
Пароль адміністратора: PBKDF2-SHA256, хеш у config.json.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Any

from core.config_loader import load_config, save_config

logger = logging.getLogger(__name__)

_ITERATIONS = 200_000
_SALT_LEN = 16


def _hash_password(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    return salt.hex() + ":" + dk.hex()


def set_password(password: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Встановлює пароль адміна, зберігає хеш у config.json."""
    if config is None:
        config = load_config()
    salt = secrets.token_bytes(_SALT_LEN)
    config["admin_password_hash"] = _hash_password(password, salt)
    save_config(config)
    logger.info("Пароль адміністратора встановлено")
    return config


def verify_password(password: str, config: dict[str, Any] | None = None) -> bool:
    """Перевіряє пароль. Повертає True при успіху."""
    if config is None:
        config = load_config()
    stored = config.get("admin_password_hash") or ""
    if not stored or ":" not in stored:
        return False
    salt_hex, hash_hex = stored.split(":", 1)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    expected = _hash_password(password, salt)
    return hmac.compare_digest(expected, stored)


def is_password_set(config: dict[str, Any] | None = None) -> bool:
    if config is None:
        config = load_config()
    h = config.get("admin_password_hash") or ""
    return bool(h and ":" in h)
