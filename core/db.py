"""
Робота з SQLite базою даних SecureTest.
Режим WAL, таймаут блокування, міграції схеми.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable

from core.config_loader import get_db_path, load_config

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Таймаут очікування блокування (секунди) — важливо для мережевої папки
BUSY_TIMEOUT_MS = 30_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Обгортка над SQLite з підтримкою WAL і міграцій."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            config = load_config()
            db_path = get_db_path(config)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_connection_settings()
        self._ensure_schema()

    def _init_connection_settings(self) -> None:
        """Налаштування з'єднання (викликається один раз при створенні)."""
        with self._connect() as conn:
            # Спроба увімкнути WAL (краще для конкурентного доступу).
            # На деяких мережевих/віртуальних ФС WAL не підтримується — тоді DELETE.
            try:
                mode = conn.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
                if str(mode).lower() != "wal":
                    logger.warning(
                        "WAL недоступний, використовується journal_mode=%s", mode
                    )
            except Exception as exc:
                logger.warning(
                    "Не вдалося увімкнути WAL (%s), використовуємо DELETE", exc
                )
                conn.execute("PRAGMA journal_mode=DELETE;")
            conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS};")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA synchronous=NORMAL;")

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            self.db_path,
            timeout=BUSY_TIMEOUT_MS / 1000,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """Створює таблиці та застосовує міграції за потреби."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                )
                """
            )
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            current = row["version"] if row else 0

            if current < 1:
                self._migrate_to_v1(conn)
                if row:
                    conn.execute("UPDATE schema_version SET version = 1")
                else:
                    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
                logger.info("Схему БД оновлено до версії 1")

    def _migrate_to_v1(self, conn: sqlite3.Connection) -> None:
        """Створення початкової схеми."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                time_limit_minutes INTEGER NOT NULL DEFAULT 60,
                violation_threshold INTEGER NOT NULL DEFAULT 5,
                shuffle_questions INTEGER NOT NULL DEFAULT 0,
                shuffle_options INTEGER NOT NULL DEFAULT 0,
                pass_percent REAL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                test_id INTEGER REFERENCES tests(id) ON DELETE SET NULL,
                attempts_allowed INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                qtype TEXT NOT NULL CHECK(qtype IN ('single', 'multiple', 'open')),
                points REAL NOT NULL DEFAULT 1.0,
                order_index INTEGER NOT NULL DEFAULT 0,
                open_answers TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                is_correct INTEGER NOT NULL DEFAULT 0,
                order_index INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS otp_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE,
                code_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_codes(email);

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'waiting'
                    CHECK(status IN ('waiting', 'in_progress', 'completed', 'blocked')),
                score REAL NOT NULL DEFAULT 0,
                max_score REAL NOT NULL DEFAULT 0,
                percent REAL NOT NULL DEFAULT 0,
                passed INTEGER,
                start_time TEXT,
                end_time TEXT,
                report_sent INTEGER NOT NULL DEFAULT 0,
                report_path TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                selected TEXT NOT NULL DEFAULT '',
                is_correct INTEGER,
                points_awarded REAL NOT NULL DEFAULT 0,
                UNIQUE(attempt_id, question_id)
            );

            CREATE TABLE IF NOT EXISTS question_times (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                seconds INTEGER NOT NULL DEFAULT 0,
                UNIQUE(attempt_id, question_id)
            );

            CREATE TABLE IF NOT EXISTS violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                vtype TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                question_number INTEGER,
                details TEXT DEFAULT '',
                screenshot_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                violation_id INTEGER REFERENCES violations(id) ON DELETE SET NULL,
                captured_at TEXT NOT NULL,
                file_path TEXT NOT NULL,
                is_periodic INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL UNIQUE REFERENCES attempts(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0,
                last_send_error TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                details TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )

    # ---------- Допоміжні методи ----------

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._connect() as conn:
            return conn.execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(sql, seq)

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def insert(self, table: str, data: dict[str, Any]) -> int:
        """Вставляє рядок і повертає lastrowid."""
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        with self._connect() as conn:
            cur = conn.execute(sql, tuple(data.values()))
            return cur.lastrowid or 0

    def update(self, table: str, data: dict[str, Any], where: str, params: Iterable[Any]) -> int:
        """Оновлює рядки. Повертає кількість змінених."""
        sets = ", ".join(f"{k}=?" for k in data)
        sql = f"UPDATE {table} SET {sets} WHERE {where}"
        with self._connect() as conn:
            cur = conn.execute(sql, (*data.values(), *params))
            return cur.rowcount

    def log_audit(self, action: str, actor: str, details: str = "") -> None:
        self.insert(
            "audit_log",
            {
                "action": action,
                "actor": actor,
                "details": details,
                "created_at": _utc_now(),
            },
        )


def get_db(db_path: str | Path | None = None) -> Database:
    """Фабрика для отримання екземпляра Database."""
    return Database(db_path)
