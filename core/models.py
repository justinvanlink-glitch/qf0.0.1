"""
Моделі даних SecureTest (dataclasses / TypedDict для зручності).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AttemptStatus(str, Enum):
    WAITING = "waiting"          # Очікує
    IN_PROGRESS = "in_progress"  # Проходить
    COMPLETED = "completed"      # Завершено
    BLOCKED = "blocked"          # Заблоковано


class QuestionType(str, Enum):
    SINGLE = "single"
    MULTIPLE = "multiple"
    OPEN = "open"


class ViolationType(str, Enum):
    FOCUS_LOST = "focus_lost"
    BLOCKED_KEY = "blocked_key"
    EMERGENCY_CLOSE = "emergency_close"
    BLACKLIST_PROCESS = "blacklist_process"
    THRESHOLD_EXCEEDED = "threshold_exceeded"


@dataclass
class Student:
    id: int | None = None
    full_name: str = ""
    email: str = ""
    test_id: int | None = None
    attempts_allowed: int = 1


@dataclass
class Test:
    id: int | None = None
    title: str = ""
    time_limit_minutes: int = 60
    violation_threshold: int = 5
    shuffle_questions: bool = False
    shuffle_options: bool = False
    pass_percent: float | None = None  # None = не перевіряти
    created_at: datetime | None = None


@dataclass
class Option:
    id: int | None = None
    question_id: int | None = None
    text: str = ""
    is_correct: bool = False
    order_index: int = 0


@dataclass
class Question:
    id: int | None = None
    test_id: int | None = None
    text: str = ""
    qtype: QuestionType = QuestionType.SINGLE
    points: float = 1.0
    order_index: int = 0
    # Для open: допустимі відповіді через ";"
    open_answers: str = ""
    options: list[Option] = field(default_factory=list)


@dataclass
class Attempt:
    id: int | None = None
    student_id: int | None = None
    test_id: int | None = None
    status: AttemptStatus = AttemptStatus.WAITING
    score: float = 0.0
    max_score: float = 0.0
    percent: float = 0.0
    passed: bool | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    report_sent: bool = False
    report_path: str = ""


@dataclass
class Answer:
    id: int | None = None
    attempt_id: int | None = None
    question_id: int | None = None
    # Для single/multiple: JSON-список id варіантів або текст для open
    selected: str = ""
    is_correct: bool | None = None
    points_awarded: float = 0.0


@dataclass
class QuestionTime:
    id: int | None = None
    attempt_id: int | None = None
    question_id: int | None = None
    seconds: int = 0


@dataclass
class Violation:
    id: int | None = None
    attempt_id: int | None = None
    student_id: int | None = None
    vtype: ViolationType | str = ""
    occurred_at: datetime | None = None
    question_number: int | None = None
    details: str = ""
    screenshot_id: int | None = None


@dataclass
class Screenshot:
    id: int | None = None
    attempt_id: int | None = None
    violation_id: int | None = None
    captured_at: datetime | None = None
    file_path: str = ""
    is_periodic: bool = False


@dataclass
class OtpCode:
    email: str = ""
    code_hash: str = ""
    salt: str = ""
    expires_at: datetime | None = None
    failed_attempts: int = 0
    used: bool = False
    created_at: datetime | None = None


@dataclass
class AuditLogEntry:
    id: int | None = None
    action: str = ""
    actor: str = ""  # email або "admin"
    details: str = ""
    created_at: datetime | None = None
