"""
Екрани входу: email → OTP → згода.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.mailer import MailerError, send_email
from core.otp import OtpDenied, OtpInvalid, OtpSendLimit, OtpService

logger = logging.getLogger(__name__)


class EmailScreen(QWidget):
    """Екран 1: введення корпоративної пошти."""

    def __init__(
        self,
        otp: OtpService,
        config: dict[str, Any],
        on_code_sent: Callable[[str, dict], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.otp = otp
        self.config = config
        self.on_code_sent = on_code_sent

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 24, 32, 24)

        # Вертикальне центрування (як Flexbox justify-content: center)
        layout.addStretch(1)

        # Логотип + назва
        logo_layout = QHBoxLayout()
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.setSpacing(12)
        logo_label = QLabel()
        try:
            pixmap = QPixmap("assets/logo.png")
            if not pixmap.isNull():
                logo_label.setPixmap(pixmap.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass
        logo_layout.addWidget(logo_label)
        name_label = QLabel("QuizForge")
        name_label.setObjectName("logoLabel")
        logo_layout.addWidget(name_label)
        layout.addLayout(logo_layout)

        title = QLabel("Вхід до тесту")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        hint = QLabel("Введіть корпоративну пошту, на яку надійде одноразовий код.")
        hint.setObjectName("subtitleLabel")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setMaximumWidth(480)
        layout.addWidget(hint, alignment=Qt.AlignmentFlag.AlignCenter)

        form = QVBoxLayout()
        form.setSpacing(12)
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("name@company.com")
        self.email_edit.setMinimumWidth(280)
        self.email_edit.setMaximumWidth(480)
        self.email_edit.setMinimumHeight(44)
        self.email_edit.returnPressed.connect(self._submit)
        form.addWidget(self.email_edit, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn = QPushButton("Отримати код")
        self.btn.setMinimumHeight(48)
        self.btn.setMinimumWidth(220)
        self.btn.setMaximumWidth(480)
        self.btn.clicked.connect(self._submit)
        form.addWidget(self.btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(form)

        self.status = QLabel("")
        self.status.setObjectName("subtitleLabel")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setMaximumWidth(480)
        layout.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(1)

    def _submit(self) -> None:
        email = self.email_edit.text().strip()
        if not email:
            self.status.setText("Введіть адресу електронної пошти.")
            return

        self.btn.setEnabled(False)
        self.status.setText("Надсилаємо код…")
        try:
            code, student = self.otp.request_code(email)
        except OtpDenied as exc:
            # Нейтральне повідомлення — без деталей
            msg = str(exc)
            if "використано" in msg.lower():
                self.status.setText(msg)
            else:
                self.status.setText("Доступ не надано. Зверніться до адміністратора.")
            self.btn.setEnabled(True)
            return
        except OtpSendLimit as exc:
            self.status.setText(str(exc))
            self.btn.setEnabled(True)
            return
        except Exception as exc:
            logger.exception("Помилка генерації OTP")
            self.status.setText("Сталася помилка. Спробуйте пізніше.")
            self.btn.setEnabled(True)
            return

        # Відправка листа
        try:
            self._send_otp_email(email, code)
        except MailerError as exc:
            logger.error("Не вдалося надіслати OTP: %s", exc)
            self.status.setText(
                "Не вдалося надіслати код. Перевірте з'єднання або зверніться до адміністратора."
            )
            self.btn.setEnabled(True)
            return
        except Exception as exc:
            logger.exception("Неочікувана помилка відправки OTP")
            self.status.setText(
                "Не вдалося надіслати код. Перевірте з'єднання або зверніться до адміністратора."
            )
            self.btn.setEnabled(True)
            return

        self.btn.setEnabled(True)
        self.on_code_sent(email, student)

    def _send_otp_email(self, email: str, code: str) -> None:
        org = (self.config.get("organization") or {}).get("name") or "SecureTest"
        ttl = self.otp.ttl_minutes
        subject = f"[{org}] Код для входу до тесту"
        body = (
            f"Ваш одноразовий код для входу: {code}\n\n"
            f"Код дійсний {ttl} хв.\n"
            f"Нікому не повідомляйте цей код.\n\n"
            f"— {org}"
        )
        send_email(self.config, email, subject, body)


class CodeScreen(QWidget):
    """Екран 2: введення коду з листа."""

    def __init__(
        self,
        otp: OtpService,
        config: dict[str, Any],
        email: str,
        student: dict,
        on_success: Callable[[dict], None],
        on_back: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.otp = otp
        self.config = config
        self.email = email
        self.student = student
        self.on_success = on_success
        self.on_back = on_back

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 24, 32, 24)

        layout.addStretch(1)

        # Логотип + назва
        logo_layout = QHBoxLayout()
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.setSpacing(12)
        logo_label = QLabel()
        try:
            pixmap = QPixmap("assets/logo.png")
            if not pixmap.isNull():
                logo_label.setPixmap(pixmap.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass
        logo_layout.addWidget(logo_label)
        name_label = QLabel("QuizForge")
        name_label.setObjectName("logoLabel")
        logo_layout.addWidget(name_label)
        layout.addLayout(logo_layout)

        title = QLabel("Код з листа")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        hint = QLabel(f"Код надіслано на\n{email}")
        hint.setObjectName("subtitleLabel")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setMaximumWidth(480)
        layout.addWidget(hint, alignment=Qt.AlignmentFlag.AlignCenter)

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("000000")
        self.code_edit.setMaxLength(6)
        self.code_edit.setMinimumWidth(200)
        self.code_edit.setMaximumWidth(280)
        self.code_edit.setMinimumHeight(48)
        self.code_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_edit.setStyleSheet("font-size: 22px; letter-spacing: 8px;")
        self.code_edit.returnPressed.connect(self._submit)
        layout.addWidget(self.code_edit, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_login = QPushButton("Увійти")
        self.btn_login.setMinimumHeight(48)
        self.btn_login.setMinimumWidth(200)
        self.btn_login.setMaximumWidth(320)
        self.btn_login.clicked.connect(self._submit)
        layout.addWidget(self.btn_login, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_resend = QPushButton("Надіслати код повторно")
        self.btn_resend.setObjectName("secondaryButton")
        self.btn_resend.setMinimumHeight(40)
        self.btn_resend.clicked.connect(self._resend)
        layout.addWidget(self.btn_resend, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_back = QPushButton("← Інша пошта")
        self.btn_back.setObjectName("secondaryButton")
        self.btn_back.setMinimumHeight(40)
        self.btn_back.clicked.connect(self.on_back)
        layout.addWidget(self.btn_back, alignment=Qt.AlignmentFlag.AlignCenter)

        self.status = QLabel("")
        self.status.setObjectName("subtitleLabel")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setMaximumWidth(480)
        layout.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(1)

        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.timeout.connect(self._tick_cooldown)
        self._update_resend_btn()

    def _submit(self) -> None:
        code = self.code_edit.text().strip()
        try:
            student = self.otp.verify_code(self.email, code)
        except OtpInvalid as exc:
            self.status.setText(str(exc))
            return
        except OtpDenied as exc:
            self.status.setText(str(exc))
            return
        except Exception:
            logger.exception("Помилка перевірки OTP")
            self.status.setText("Сталася помилка. Спробуйте пізніше.")
            return
        self.on_success(student)

    def _resend(self) -> None:
        left = self.otp.seconds_until_resend_allowed(self.email)
        if left > 0:
            self.status.setText(f"Повторна відправка через {left} с.")
            return
        try:
            code, student = self.otp.request_code(self.email)
            self.student = student
        except (OtpDenied, OtpSendLimit) as exc:
            self.status.setText(str(exc))
            return
        except Exception:
            logger.exception("Помилка повторної генерації OTP")
            self.status.setText("Сталася помилка.")
            return

        try:
            org = (self.config.get("organization") or {}).get("name") or "SecureTest"
            ttl = self.otp.ttl_minutes
            subject = f"[{org}] Код для входу до тесту"
            body = (
                f"Ваш одноразовий код для входу: {code}\n\n"
                f"Код дійсний {ttl} хв.\n"
                f"Нікому не повідомляйте цей код.\n\n"
                f"— {org}"
            )
            send_email(self.config, self.email, subject, body)
            self.status.setText("Новий код надіслано.")
        except Exception as exc:
            logger.error("Не вдалося надіслати OTP повторно: %s", exc)
            self.status.setText(
                "Не вдалося надіслати код. Перевірте з'єднання або зверніться до адміністратора."
            )
            return
        self._update_resend_btn()

    def _update_resend_btn(self) -> None:
        left = self.otp.seconds_until_resend_allowed(self.email)
        if left > 0:
            self.btn_resend.setEnabled(False)
            self.btn_resend.setText(f"Повторно через {left} с")
            self._cooldown_timer.start(1000)
        else:
            self.btn_resend.setEnabled(True)
            self.btn_resend.setText("Надіслати код повторно")
            self._cooldown_timer.stop()

    def _tick_cooldown(self) -> None:
        self._update_resend_btn()


class ConsentScreen(QWidget):
    """Екран згоди перед початком тесту."""

    def __init__(
        self,
        student: dict,
        test_title: str,
        on_agree: Callable[[], None],
        on_cancel: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 24, 32, 24)

        layout.addStretch(1)

        # Логотип + назва
        logo_layout = QHBoxLayout()
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.setSpacing(12)
        logo_label = QLabel()
        try:
            pixmap = QPixmap("assets/logo.png")
            if not pixmap.isNull():
                logo_label.setPixmap(pixmap.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass
        logo_layout.addWidget(logo_label)
        name_label = QLabel("QuizForge")
        name_label.setObjectName("logoLabel")
        logo_layout.addWidget(name_label)
        layout.addLayout(logo_layout)

        title = QLabel("Перед початком")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        info = QLabel(f"{student.get('full_name', '')}\nТест: {test_title}")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setWordWrap(True)
        info.setMaximumWidth(520)
        layout.addWidget(info, alignment=Qt.AlignmentFlag.AlignCenter)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setMinimumHeight(120)
        text.setMaximumHeight(220)
        text.setMaximumWidth(520)
        text.setPlainText(
            "Під час тесту ведеться запис екрана та журнал дій.\n\n"
            "Заборонено:\n"
            "• перемикатися на інші вікна та програми;\n"
            "• використовувати сторонні засоби віддаленого доступу;\n"
            "• фотографувати або копіювати завдання.\n\n"
            "Порушення правил може призвести до блокування спроби.\n"
            "Натискаючи «Погоджуюсь і почати», ви підтверджуєте ознайомлення "
            "з умовами та даєте згоду на моніторинг."
        )
        layout.addWidget(text, alignment=Qt.AlignmentFlag.AlignCenter)

        btns = QHBoxLayout()
        btns.setSpacing(12)
        btn_cancel = QPushButton("Скасувати")
        btn_cancel.setObjectName("secondaryButton")
        btn_cancel.setMinimumHeight(44)
        btn_cancel.setMinimumWidth(140)
        btn_cancel.clicked.connect(on_cancel)
        btn_ok = QPushButton("Погоджуюсь і почати")
        btn_ok.setMinimumHeight(44)
        btn_ok.setMinimumWidth(180)
        btn_ok.clicked.connect(on_agree)
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        btns.addStretch()
        layout.addLayout(btns)

        layout.addStretch(1)
