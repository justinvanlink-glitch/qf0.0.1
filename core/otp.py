"""
Генерація, зберігання та перевірка одноразових кодів (OTP).
У БД зберігається лише SHA-256(salt + code), порівняння через hmac.compare_digest.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from core.db import Database

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    if dt is None:
        dt = _utc_now()
    return dt.isoformat()


def _hash_code(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}{code}".encode("utf-8")).hexdigest()


def generate_code() -> str:
    """6-значний числовий код."""
    return f"{secrets.randbelow(1_000_000):06d}"


class OtpError(Exception):
    """Базова помилка OTP."""


class OtpDenied(OtpError):
    """Доступ не надано (нейтральне повідомлення користувачу)."""


class OtpSendLimit(OtpError):
    """Перевищено ліміт надсилань."""


class OtpInvalid(OtpError):
    """Невірний або прострочений код."""


class OtpService:
    """Сервіс роботи з одноразовими кодами."""

    def __init__(self, db: Database, config: dict[str, Any]) -> None:
        self.db = db
        self.config = config
        self.ttl_minutes = int(config.get("otp_ttl_minutes", 10))
        self.max_failed = int(config.get("otp_max_failed", 10))
        self.resend_cooldown = int(config.get("otp_resend_cooldown_sec", 60))
        self.max_per_hour = int(config.get("otp_max_requests_per_hour", 5))
        self.allowed_domains: list[str] = [
            d.lower().strip() for d in (config.get("allowed_domains") or []) if d
        ]

    def _normalize_email(self, email: str) -> str:
        return (email or "").strip().lower()

    def check_access(self, email: str) -> dict[str, Any]:
        """
        Перевіряє, чи email у білому списку і чи є невикористана спроба.
        Повертає dict студента або кидає OtpDenied.
        """
        email = self._normalize_email(email)
        if not email or "@" not in email:
            raise OtpDenied("Доступ не надано")

        if self.allowed_domains:
            domain = email.split("@", 1)[-1]
            if domain not in self.allowed_domains:
                raise OtpDenied("Доступ не надано")

        student = self.db.fetchone(
            "SELECT * FROM students WHERE email = ? COLLATE NOCASE", (email,)
        )
        if not student:
            raise OtpDenied("Доступ не надано")

        if not student["test_id"]:
            raise OtpDenied("Доступ не надано")

        # Перевірка спроб
        used = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM attempts
            WHERE student_id = ?
              AND status IN ('in_progress', 'completed', 'blocked')
            """,
            (student["id"],),
        )
        used_count = used["cnt"] if used else 0
        allowed = int(student["attempts_allowed"] or 1)
        if used_count >= allowed:
            raise OtpDenied("Спробу вже використано. Зверніться до адміністратора")

        return dict(student)

    def _count_sends_last_hour(self, email: str) -> int:
        since = _utc_iso(_utc_now() - timedelta(hours=1))
        row = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM otp_codes WHERE email = ? AND created_at >= ?",
            (email, since),
        )
        return int(row["cnt"]) if row else 0

    def request_code(self, email: str) -> tuple[str, dict[str, Any]]:
        """
        Генерує код, зберігає хеш, повертає (plain_code, student).
        plain_code потрібен лише для відправки листом — далі ніде не зберігається.
        """
        student = self.check_access(email)
        email = self._normalize_email(email)

        if self._count_sends_last_hour(email) >= self.max_per_hour:
            raise OtpSendLimit(
                f"Перевищено ліміт запитів ({self.max_per_hour} на годину). Спробуйте пізніше."
            )

        # Анулюємо попередні активні коди
        self.db.execute(
            "UPDATE otp_codes SET used = 1 WHERE email = ? AND used = 0",
            (email,),
        )

        code = generate_code()
        salt = secrets.token_hex(16)
        code_hash = _hash_code(code, salt)
        expires = _utc_now() + timedelta(minutes=self.ttl_minutes)

        self.db.insert(
            "otp_codes",
            {
                "email": email,
                "code_hash": code_hash,
                "salt": salt,
                "expires_at": _utc_iso(expires),
                "failed_attempts": 0,
                "used": 0,
                "created_at": _utc_iso(),
            },
        )
        # plain code не логуємо
        logger.info("OTP згенеровано для %s, TTL=%s хв", email, self.ttl_minutes)
        return code, student

    def verify_code(self, email: str, code: str) -> dict[str, Any]:
        """
        Перевіряє код. Повертає student dict при успіху.
        """
        email = self._normalize_email(email)
        code = (code or "").strip()

        if not code or len(code) != 6 or not code.isdigit():
            raise OtpInvalid("Невірний код")

        # Актуальний невикористаний код
        row = self.db.fetchone(
            """
            SELECT * FROM otp_codes
            WHERE email = ? AND used = 0
            ORDER BY id DESC LIMIT 1
            """,
            (email,),
        )
        if not row:
            raise OtpInvalid("Код недійсний. Запросіть новий.")

        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if _utc_now() > expires:
            self.db.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
            raise OtpInvalid("Код прострочено. Запросіть новий.")

        if int(row["failed_attempts"] or 0) >= self.max_failed:
            self.db.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
            raise OtpInvalid("Перевищено кількість спроб. Запросіть новий код.")

        expected = row["code_hash"]
        actual = _hash_code(code, row["salt"])
        if not hmac.compare_digest(expected, actual):
            failed = int(row["failed_attempts"] or 0) + 1
            self.db.execute(
                "UPDATE otp_codes SET failed_attempts = ? WHERE id = ?",
                (failed, row["id"]),
            )
            if failed >= self.max_failed:
                self.db.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
                raise OtpInvalid("Перевищено кількість спроб. Запросіть новий код.")
            left = self.max_failed - failed
            raise OtpInvalid(f"Невірний код. Залишилось спроб: {left}")

        # Успіх — анулюємо код
        self.db.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
        student = self.check_access(email)
        logger.info("OTP успішно підтверджено для %s", email)
        return student

    def seconds_until_resend_allowed(self, email: str) -> int:
        """Скільки секунд залишилось до можливості повторної відправки (0 = можна)."""
        email = self._normalize_email(email)
        row = self.db.fetchone(
            """
            SELECT created_at FROM otp_codes
            WHERE email = ?
            ORDER BY id DESC LIMIT 1
            """,
            (email,),
        )
        if not row:
            return 0
        created = datetime.fromisoformat(row["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (_utc_now() - created).total_seconds()
        left = self.resend_cooldown - elapsed
        return max(0, int(left))
