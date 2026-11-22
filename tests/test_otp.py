"""Тести OTP."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.db import Database
from core.otp import OtpService, OtpDenied, OtpInvalid, OtpSendLimit, generate_code, _hash_code


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    # тестовий тест і студент
    tid = d.insert(
        "tests",
        {
            "title": "T",
            "time_limit_minutes": 30,
            "violation_threshold": 5,
            "shuffle_questions": 0,
            "shuffle_options": 0,
            "pass_percent": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    d.insert(
        "students",
        {
            "full_name": "Test User",
            "email": "user@company.com",
            "test_id": tid,
            "attempts_allowed": 1,
        },
    )
    return d


@pytest.fixture
def otp(db):
    cfg = {
        "otp_ttl_minutes": 10,
        "otp_max_failed": 3,
        "otp_resend_cooldown_sec": 60,
        "otp_max_requests_per_hour": 5,
        "allowed_domains": ["company.com"],
    }
    return OtpService(db, cfg)


def test_generate_code():
    c = generate_code()
    assert len(c) == 6 and c.isdigit()


def test_request_and_verify(otp, db):
    code, student = otp.request_code("user@company.com")
    assert len(code) == 6
    assert student["email"] == "user@company.com"
    result = otp.verify_code("user@company.com", code)
    assert result["id"] == student["id"]


def test_wrong_code(otp):
    code, _ = otp.request_code("user@company.com")
    with pytest.raises(OtpInvalid):
        otp.verify_code("user@company.com", "000000")


def test_max_failed(otp, db):
    code, _ = otp.request_code("user@company.com")
    for _ in range(3):
        with pytest.raises(OtpInvalid):
            otp.verify_code("user@company.com", "000000")
    # код анульовано
    with pytest.raises(OtpInvalid):
        otp.verify_code("user@company.com", code)


def test_denied_unknown_email(otp):
    with pytest.raises(OtpDenied):
        otp.request_code("nobody@company.com")


def test_denied_domain(otp):
    with pytest.raises(OtpDenied):
        otp.request_code("user@other.com")


def test_used_code_invalid(otp):
    code, _ = otp.request_code("user@company.com")
    otp.verify_code("user@company.com", code)
    with pytest.raises(OtpInvalid):
        otp.verify_code("user@company.com", code)


def test_hash_not_plaintext(otp, db):
    code, _ = otp.request_code("user@company.com")
    row = db.fetchone("SELECT code_hash, salt FROM otp_codes ORDER BY id DESC LIMIT 1")
    assert row["code_hash"] != code
    assert row["code_hash"] == _hash_code(code, row["salt"])
