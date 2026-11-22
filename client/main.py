"""
SecureTest Client — вхід, згода, проходження тесту.
Крок 5.
"""

from __future__ import annotations

import logging
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import Qt

from PyQt6.QtCore import QObject, pyqtSignal


class ViolationBridge(QObject):
    """Місток для порушень з потоку keyboard hook у GUI-потік."""
    violated = pyqtSignal(str, str)  # vtype, details

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config_loader import load_config
from core.db import get_db
from core.otp import OtpService
from client.auth_ui import CodeScreen, ConsentScreen, EmailScreen
from client.quiz_ui import FinishedScreen, QuizScreen
from client.lockdown import Lockdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "client.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("client")


def apply_styles(app: QApplication, accent: str = "#2563eb") -> None:
    qss_path = Path(__file__).parent / "ui" / "styles.qss"
    if qss_path.is_file():
        with open(qss_path, "r", encoding="utf-8") as f:
            qss = f.read()
        qss = qss.replace("#2563eb", accent)
        app.setStyleSheet(qss)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClientWindow(QMainWindow):
    def __init__(self, db, config: dict, org_name: str) -> None:
        super().__init__()
        self.db = db
        self.config = config
        self.org_name = org_name
        self.otp = OtpService(db, config)

        self.setWindowTitle("QuizForge — Тестування")
        self.setMinimumSize(720, 520)
        self.resize(900, 640)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self._email: str = ""
        self._student: dict | None = None
        self._attempt_id: int | None = None
        self._lockdown: Lockdown | None = None
        self._quiz: QuizScreen | None = None

        self._show_email_screen()

    def _clear_stack(self) -> None:
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()

    def _show_email_screen(self) -> None:
        self._clear_stack()
        screen = EmailScreen(
            self.otp,
            self.config,
            on_code_sent=self._on_code_sent,
        )
        self.stack.addWidget(screen)
        self.stack.setCurrentWidget(screen)

    def _on_code_sent(self, email: str, student: dict) -> None:
        self._email = email
        self._student = student
        self._clear_stack()
        screen = CodeScreen(
            self.otp,
            self.config,
            email=email,
            student=student,
            on_success=self._on_login_success,
            on_back=self._show_email_screen,
        )
        self.stack.addWidget(screen)
        self.stack.setCurrentWidget(screen)

    def _on_login_success(self, student: dict) -> None:
        self._student = student
        test = self.db.fetchone("SELECT * FROM tests WHERE id = ?", (student["test_id"],))
        if not test:
            QMessageBox.critical(self, "Помилка", "Тест не знайдено. Зверніться до адміністратора.")
            self._show_email_screen()
            return
        test = dict(test)
        self._clear_stack()
        screen = ConsentScreen(
            student=student,
            test_title=test["title"],
            on_agree=lambda: self._start_test(student, test),
            on_cancel=self._show_email_screen,
        )
        self.stack.addWidget(screen)
        self.stack.setCurrentWidget(screen)

    def _start_test(self, student: dict, test: dict) -> None:
        attempt_id = self.db.insert(
            "attempts",
            {
                "student_id": student["id"],
                "test_id": test["id"],
                "status": "in_progress",
                "score": 0,
                "max_score": 0,
                "percent": 0,
                "passed": None,
                "start_time": _utc_now_iso(),
                "end_time": None,
                "report_sent": 0,
                "report_path": "",
            },
        )
        self._attempt_id = attempt_id
        self.db.log_audit(
            "attempt_started",
            student["email"],
            f"attempt_id={attempt_id}, test_id={test['id']}",
        )

        questions = [
            dict(r)
            for r in self.db.fetchall(
                "SELECT * FROM questions WHERE test_id = ? ORDER BY order_index, id",
                (test["id"],),
            )
        ]
        if not questions:
            QMessageBox.critical(self, "Помилка", "У тесті немає питань.")
            self.db.update("attempts", {"status": "blocked"}, "id = ?", (attempt_id,))
            self._show_email_screen()
            return

        if test.get("shuffle_questions"):
            random.shuffle(questions)

        self._clear_stack()
        quiz = QuizScreen(
            db=self.db,
            config=self.config,
            student=student,
            attempt_id=attempt_id,
            test=test,
            questions=questions,
            on_finished=self._on_quiz_finished,
        )
        self._quiz = quiz
        self.stack.addWidget(quiz)
        self.stack.setCurrentWidget(quiz)

        # Lockdown (порушення з hook-потоку → GUI через сигнал)
        self._violation_bridge = ViolationBridge()
        self._violation_bridge.violated.connect(quiz.record_violation)
        self._lockdown = Lockdown(
            window=self,
            on_violation=lambda vtype, details: self._violation_bridge.violated.emit(vtype, details),
        )
        try:
            self._lockdown.activate()
        except Exception:
            logger.exception("Не вдалося активувати lockdown")

    def _on_quiz_finished(self) -> None:
        if self._lockdown:
            try:
                self._lockdown.deactivate()
            except Exception:
                logger.exception("Deactivate lockdown")
            self._lockdown = None
        self._quiz = None

        score_info = None
        if self._attempt_id:
            row = self.db.fetchone(
                "SELECT score, max_score, percent, passed FROM attempts WHERE id = ?",
                (self._attempt_id,),
            )
            if row:
                score_info = dict(row)
            self.db.log_audit(
                "attempt_completed",
                (self._student or {}).get("email", ""),
                f"attempt_id={self._attempt_id}",
            )

        self._clear_stack()
        screen = FinishedScreen(self.config, score_info=score_info)
        self.stack.addWidget(screen)
        self.stack.setCurrentWidget(screen)


    def changeEvent(self, event) -> None:
        from PyQt6.QtCore import QEvent
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange:
            if self._lockdown and self._quiz and not self.isActiveWindow():
                self._quiz.record_violation("focus_lost", "Втрата фокуса вікна")
                try:
                    self.activateWindow()
                    self.raise_()
                except Exception:
                    pass

    def closeEvent(self, event) -> None:
        if self._lockdown:
            try:
                self._lockdown.deactivate()
            except Exception:
                logger.exception("Deactivate lockdown on close")
            self._lockdown = None

        if self._attempt_id:
            row = self.db.fetchone(
                "SELECT status FROM attempts WHERE id = ?", (self._attempt_id,)
            )
            if row and row["status"] == "in_progress":
                self.db.update(
                    "attempts",
                    {"status": "blocked", "end_time": _utc_now_iso()},
                    "id = ?",
                    (self._attempt_id,),
                )
                self.db.insert(
                    "violations",
                    {
                        "attempt_id": self._attempt_id,
                        "student_id": (self._student or {}).get("id") or 0,
                        "vtype": "emergency_close",
                        "occurred_at": _utc_now_iso(),
                        "question_number": None,
                        "details": "Аварійне закриття програми під час тесту",
                        "screenshot_id": None,
                    },
                )
                self.db.log_audit(
                    "emergency_close",
                    (self._student or {}).get("email", ""),
                    f"attempt_id={self._attempt_id}",
                )
                logger.warning("Аварійне закриття attempt_id=%s", self._attempt_id)
                # Звіт навіть при аварійному закритті
                try:
                    from core.scoring import score_attempt
                    from core.report_builder import build_report, send_report
                    score_attempt(
                        self.db,
                        self._attempt_id,
                        partial_credit=bool(self.config.get("partial_credit")),
                    )
                    rp = build_report(self.db, self._attempt_id)
                    send_report(self.db, self.config, self._attempt_id, rp)
                except Exception:
                    logger.exception("Звіт після аварійного закриття")
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SecureTest Client")
    app.setOrganizationName("SecureTest")

    try:
        config = load_config()
    except Exception as exc:
        logger.error("Конфіг: %s", exc)
        QMessageBox.critical(None, "Помилка", f"Не вдалося завантажити config.json:\n{exc}")
        return 1

    org = config.get("organization", {})
    org_name = org.get("name", "SecureTest")
    accent = org.get("accent_color", "#2563eb")
    apply_styles(app, accent)

    try:
        db = get_db()
        logger.info("БД: %s", db.db_path)
    except Exception as exc:
        logger.exception("БД")
        QMessageBox.critical(None, "Помилка БД", str(exc))
        return 1

    # Автоповтор невідправлених звітів
    try:
        from core.report_builder import retry_unsent_reports
        n = retry_unsent_reports(db, config)
        if n:
            logger.info("Повторно надіслано звітів: %s", n)
    except Exception:
        logger.exception("retry_unsent_reports")

    window = ClientWindow(db, config, org_name)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
