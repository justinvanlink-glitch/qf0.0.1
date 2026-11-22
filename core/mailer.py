"""
Єдиний модуль відправки листів (OTP-коди та звіти).
SMTP з config.json. Пароль у логи не пишеться.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any

logger = logging.getLogger(__name__)


class MailerError(Exception):
    """Помилка відправки листа."""


def _smtp_connect(smtp_cfg: dict[str, Any]) -> smtplib.SMTP:
    """Створює і налаштовує SMTP-з'єднання."""
    host = smtp_cfg.get("host", "")
    port = int(smtp_cfg.get("port", 587))
    security = (smtp_cfg.get("security") or "starttls").lower()
    username = smtp_cfg.get("username") or ""
    password = smtp_cfg.get("password") or ""

    if not host:
        raise MailerError("SMTP host не вказано в config.json")

    if security == "ssl":
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.ehlo()
        if security == "starttls":
            context = ssl.create_default_context()
            server.starttls(context=context)
            server.ehlo()

    if username:
        server.login(username, password)

    return server


def send_email(
    config: dict[str, Any],
    to_addresses: list[str] | str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> None:
    """
    Надсилає лист через SMTP з конфігурації.

    Args:
        config: повний словник config.json (або з ключем smtp).
        to_addresses: один email або список.
        subject: тема.
        body_text: текстова частина.
        body_html: HTML-частина (опційно).

    Raises:
        MailerError: при помилці з'єднання або відправки.
    """
    smtp_cfg = config.get("smtp") or {}
    from_addr = smtp_cfg.get("from_address") or smtp_cfg.get("username") or ""
    from_name = smtp_cfg.get("from_name") or "SecureTest"

    if isinstance(to_addresses, str):
        recipients = [to_addresses.strip()]
    else:
        recipients = [a.strip() for a in to_addresses if a and a.strip()]

    if not recipients:
        raise MailerError("Не вказано одержувачів")
    if not from_addr:
        raise MailerError("smtp.from_address не вказано в config.json")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    # Лог без пароля
    logger.info(
        "Надсилання листа: to=%s subject=%r host=%s",
        recipients,
        subject,
        smtp_cfg.get("host"),
    )

    try:
        server = _smtp_connect(smtp_cfg)
        try:
            server.sendmail(from_addr, recipients, msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except MailerError:
        raise
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP автентифікація невдала (пароль у лог не пишеться)")
        raise MailerError(
            "Помилка автентифікації SMTP. Перевірте username/password у config.json."
        ) from exc
    except smtplib.SMTPException as exc:
        logger.error("SMTP помилка: %s", type(exc).__name__)
        raise MailerError(f"Помилка SMTP: {exc}") from exc
    except OSError as exc:
        logger.error("Мережева помилка SMTP: %s", type(exc).__name__)
        raise MailerError(f"Не вдалося з'єднатися з SMTP-сервером: {exc}") from exc

    logger.info("Лист успішно надіслано: %s", recipients)


def send_test_message(config: dict[str, Any], to_address: str) -> None:
    """
    Надсилає тестове повідомлення для перевірки SMTP.
    """
    org = (config.get("organization") or {}).get("name") or "SecureTest"
    subject = f"[{org}] Тестове повідомлення SecureTest"
    body = (
        f"Це тестове повідомлення від SecureTest ({org}).\n\n"
        "Якщо ви отримали цей лист — налаштування SMTP працюють коректно.\n\n"
        "— SecureTest"
    )
    send_email(config, to_address, subject, body)
