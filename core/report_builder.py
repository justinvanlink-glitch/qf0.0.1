"""
Побудова PDF-звіту про спробу тесту (reportlab, кирилиця).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.db import Database

logger = logging.getLogger(__name__)

# Кандидати шляхів до шрифту з кирилицею
_FONT_CANDIDATES = [
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    # Windows
    "C:/Windows/Fonts/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/Arial.ttf",
    # macOS
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def _find_font() -> tuple[str | None, str | None]:
    """Повертає (regular_path, bold_path)."""
    regular = None
    bold = None
    # Шукаємо поруч із пакетом (для збірки PyInstaller)
    bundled = Path(__file__).resolve().parent.parent / "fonts"
    for name, target in [("DejaVuSans.ttf", "regular"), ("DejaVuSans-Bold.ttf", "bold")]:
        p = bundled / name
        if p.is_file():
            if target == "regular":
                regular = str(p)
            else:
                bold = str(p)

    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            lower = path.lower()
            if "bold" in lower and bold is None:
                bold = path
            elif regular is None:
                regular = path
    return regular, bold


_FONTS_REGISTERED = False
_FONT_NAME = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def _ensure_fonts() -> None:
    global _FONTS_REGISTERED, _FONT_NAME, _FONT_BOLD
    if _FONTS_REGISTERED:
        return
    regular, bold = _find_font()
    try:
        if regular:
            pdfmetrics.registerFont(TTFont("STFont", regular))
            _FONT_NAME = "STFont"
        if bold:
            pdfmetrics.registerFont(TTFont("STFont-Bold", bold))
            _FONT_BOLD = "STFont-Bold"
        elif regular:
            _FONT_BOLD = "STFont"
    except Exception:
        logger.exception("Не вдалося зареєструвати шрифт, використовуємо Helvetica")
    _FONTS_REGISTERED = True


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return local.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return iso


def _fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _reports_dir(db_path: Path) -> Path:
    d = db_path.parent / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_report(db: Database, attempt_id: int) -> Path:
    """
    Формує PDF-звіт для спроби і зберігає в reports/.
    Повертає шлях до файлу. Оновлює таблиці attempts/reports.
    """
    _ensure_fonts()

    attempt = db.fetchone("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
    if not attempt:
        raise ValueError(f"Attempt {attempt_id} not found")

    student = db.fetchone("SELECT * FROM students WHERE id = ?", (attempt["student_id"],))
    test = db.fetchone("SELECT * FROM tests WHERE id = ?", (attempt["test_id"],))

    questions = db.fetchall(
        "SELECT * FROM questions WHERE test_id = ? ORDER BY order_index, id",
        (attempt["test_id"],),
    )
    qtimes = {
        r["question_id"]: r["seconds"]
        for r in db.fetchall(
            "SELECT question_id, seconds FROM question_times WHERE attempt_id = ?",
            (attempt_id,),
        )
    }
    violations = db.fetchall(
        "SELECT * FROM violations WHERE attempt_id = ? ORDER BY occurred_at",
        (attempt_id,),
    )
    # Скріншоти порушень (до 10)
    v_shots = []
    for v in violations[:10]:
        if v["screenshot_id"]:
            sh = db.fetchone("SELECT * FROM screenshots WHERE id = ?", (v["screenshot_id"],))
            if sh and sh["file_path"] and Path(sh["file_path"]).is_file():
                v_shots.append((v, sh))

    # Час
    total_sec = sum(qtimes.values())
    if attempt["start_time"] and attempt["end_time"]:
        try:
            t0 = datetime.fromisoformat(attempt["start_time"])
            t1 = datetime.fromisoformat(attempt["end_time"])
            total_sec = max(total_sec, int((t1 - t0).total_seconds()))
        except Exception:
            pass

    limit_min = (test or {}).get("time_limit_minutes") or 0
    score = attempt["score"] or 0
    max_score = attempt["max_score"] or 0
    percent = attempt["percent"] or 0
    passed = attempt["passed"]
    if passed is None:
        result_text = "—"
    elif passed:
        result_text = "Склав"
    else:
        result_text = "Не склав"

    status_map = {
        "completed": "Завершено",
        "blocked": "Заблоковано",
        "in_progress": "Проходить",
        "waiting": "Очікує",
    }
    status_text = status_map.get(attempt["status"], attempt["status"])

    # ---- PDF ----
    out_dir = _reports_dir(db.db_path)
    email_safe = ((student or {}).get("email") or "unknown").replace("@", "_at_")
    filename = f"report_{attempt_id}_{email_safe}.pdf"
    out_path = out_dir / filename

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="STTitle",
            fontName=_FONT_BOLD,
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="STHeading",
            fontName=_FONT_BOLD,
            fontSize=12,
            spaceBefore=10,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="STBody",
            fontName=_FONT_NAME,
            fontSize=10,
            leading=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="STSmall",
            fontName=_FONT_NAME,
            fontSize=8,
            leading=10,
        )
    )

    story: list[Any] = []
    story.append(Paragraph("Звіт про проходження тесту", styles["STTitle"]))
    story.append(Spacer(1, 4 * mm))

    # Основна інформація
    info_data = [
        ["ПІБ:", (student or {}).get("full_name") or "—"],
        ["Email:", (student or {}).get("email") or "—"],
        ["Тест:", (test or {}).get("title") or "—"],
        ["Статус спроби:", status_text],
        ["Початок:", _fmt_dt(attempt["start_time"])],
        ["Кінець:", _fmt_dt(attempt["end_time"])],
        ["Витрачений час:", _fmt_duration(total_sec)],
        ["Ліміт часу:", f"{limit_min} хв" if limit_min else "—"],
        ["Бали:", f"{score:g} / {max_score:g} ({percent:g}%)"],
        ["Результат:", result_text],
        ["Порушень:", str(len(violations))],
    ]
    info_table = Table(info_data, colWidths=[45 * mm, 120 * mm])
    info_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), _FONT_BOLD),
                ("FONTNAME", (1, 0), (1, -1), _FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(info_table)
    story.append(Spacer(1, 6 * mm))

    # Час по питаннях
    story.append(Paragraph("Час по питаннях", styles["STHeading"]))
    time_rows = [["№", "Питання", "Секунд", "Час"]]
    for i, q in enumerate(questions, start=1):
        sec = int(qtimes.get(q["id"], 0))
        preview = (q["text"] or "")[:60]
        if len(q["text"] or "") > 60:
            preview += "…"
        time_rows.append([str(i), preview, str(sec), _fmt_duration(sec)])

    if len(time_rows) > 1:
        t = Table(time_rows, colWidths=[10 * mm, 110 * mm, 20 * mm, 25 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                    ("FONTNAME", (0, 1), (-1, -1), _FONT_NAME),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.93, 0.97)),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(t)
    else:
        story.append(Paragraph("Немає даних.", styles["STBody"]))

    # Порушення
    story.append(Paragraph("Журнал порушень", styles["STHeading"]))
    if violations:
        v_rows = [["Час", "Тип", "Питання", "Деталі"]]
        type_labels = {
            "focus_lost": "Втрата фокуса",
            "blocked_key": "Заблокована клавіша",
            "emergency_close": "Аварійне закриття",
            "blacklist_process": "Заборонений процес",
            "threshold_exceeded": "Поріг порушень",
        }
        for v in violations:
            v_rows.append(
                [
                    _fmt_dt(v["occurred_at"]),
                    type_labels.get(v["vtype"], v["vtype"]),
                    str(v["question_number"] or "—"),
                    (v["details"] or "")[:40],
                ]
            )
        vt = Table(v_rows, colWidths=[40 * mm, 40 * mm, 20 * mm, 55 * mm])
        vt.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                    ("FONTNAME", (0, 1), (-1, -1), _FONT_NAME),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(1, 0.9, 0.9)),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(vt)
    else:
        story.append(Paragraph("Порушень немає.", styles["STBody"]))

    # Мініатюри скріншотів
    if v_shots:
        story.append(Paragraph("Скріншоти порушень (до 10)", styles["STHeading"]))
        for v, sh in v_shots:
            try:
                img = Image(sh["file_path"], width=80 * mm, height=45 * mm, kind="proportional")
                story.append(img)
                story.append(
                    Paragraph(
                        f"{_fmt_dt(v['occurred_at'])} — {v['vtype']}: {v['details'] or ''}",
                        styles["STSmall"],
                    )
                )
                story.append(Spacer(1, 3 * mm))
            except Exception:
                logger.exception("Не вдалося вставити зображення %s", sh["file_path"])

    doc.build(story)
    logger.info("PDF-звіт створено: %s", out_path)

    # Запис у БД
    existing = db.fetchone("SELECT id FROM reports WHERE attempt_id = ?", (attempt_id,))
    if existing:
        db.update(
            "reports",
            {
                "file_path": str(out_path),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "sent": 0,
                "last_send_error": "",
            },
            "id = ?",
            (existing["id"],),
        )
    else:
        db.insert(
            "reports",
            {
                "attempt_id": attempt_id,
                "file_path": str(out_path),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "sent": 0,
                "last_send_error": "",
            },
        )

    db.update(
        "attempts",
        {"report_path": str(out_path), "report_sent": 0},
        "id = ?",
        (attempt_id,),
    )
    return out_path


def send_report(
    db: Database,
    config: dict[str, Any],
    attempt_id: int,
    report_path: Path | None = None,
) -> bool:
    """
    Надсилає PDF-звіт одержувачам з config + опційно студенту.
    Повертає True при успіху.
    """
    from core.mailer import MailerError, send_email
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr
    import smtplib
    import ssl

    attempt = db.fetchone("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
    if not attempt:
        return False
    student = db.fetchone("SELECT * FROM students WHERE id = ?", (attempt["student_id"],))
    test = db.fetchone("SELECT * FROM tests WHERE id = ?", (attempt["test_id"],))

    path = Path(report_path or attempt["report_path"] or "")
    if not path.is_file():
        path = build_report(db, attempt_id)

    recipients: list[str] = list(config.get("report_recipients") or [])
    if config.get("send_copy_to_student") and student and student["email"]:
        recipients.append(student["email"])
    # унікальні
    seen = set()
    unique = []
    for r in recipients:
        r = (r or "").strip().lower()
        if r and r not in seen:
            seen.add(r)
            unique.append(r)
    recipients = unique

    if not recipients:
        logger.warning("Немає одержувачів звіту для attempt=%s", attempt_id)
        db.update(
            "reports",
            {"last_send_error": "Немає одержувачів у config.json"},
            "attempt_id = ?",
            (attempt_id,),
        )
        return False

    org = (config.get("organization") or {}).get("name") or "SecureTest"
    name = (student or {}).get("full_name") or ""
    email = (student or {}).get("email") or ""
    title = (test or {}).get("title") or ""
    subject = f"[{org}] Звіт: {name} — {title}"
    body = (
        f"Звіт про проходження тесту.\n\n"
        f"Студент: {name}\n"
        f"Email: {email}\n"
        f"Тест: {title}\n"
        f"Бали: {attempt['score']:g} / {attempt['max_score']:g} ({attempt['percent']:g}%)\n"
        f"Статус: {attempt['status']}\n\n"
        f"PDF у вкладенні.\n\n— {org}"
    )

    smtp_cfg = config.get("smtp") or {}
    from_addr = smtp_cfg.get("from_address") or ""
    from_name = smtp_cfg.get("from_name") or "SecureTest"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with open(path, "rb") as f:
        part = MIMEApplication(f.read(), Name=path.name)
    part["Content-Disposition"] = f'attachment; filename="{path.name}"'
    msg.attach(part)

    try:
        host = smtp_cfg.get("host", "")
        port = int(smtp_cfg.get("port", 587))
        security = (smtp_cfg.get("security") or "starttls").lower()
        username = smtp_cfg.get("username") or ""
        password = smtp_cfg.get("password") or ""

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
        server.sendmail(from_addr, recipients, msg.as_string())
        server.quit()

        db.update("reports", {"sent": 1, "last_send_error": ""}, "attempt_id = ?", (attempt_id,))
        db.update("attempts", {"report_sent": 1}, "id = ?", (attempt_id,))
        logger.info("Звіт attempt=%s надіслано: %s", attempt_id, recipients)
        return True
    except Exception as exc:
        err = str(exc)
        logger.error("Не вдалося надіслати звіт attempt=%s: %s", attempt_id, type(exc).__name__)
        db.update(
            "reports",
            {"sent": 0, "last_send_error": err[:500]},
            "attempt_id = ?",
            (attempt_id,),
        )
        db.update("attempts", {"report_sent": 0}, "id = ?", (attempt_id,))
        return False


def retry_unsent_reports(db: Database, config: dict[str, Any]) -> int:
    """Повторна відправка невідправлених звітів. Повертає кількість успішних."""
    rows = db.fetchall(
        "SELECT attempt_id, file_path FROM reports WHERE sent = 0"
    )
    ok = 0
    for r in rows:
        path = Path(r["file_path"]) if r["file_path"] else None
        if path and path.is_file():
            if send_report(db, config, r["attempt_id"], path):
                ok += 1
        else:
            # спробувати згенерувати знову
            try:
                build_report(db, r["attempt_id"])
                if send_report(db, config, r["attempt_id"]):
                    ok += 1
            except Exception:
                logger.exception("retry report attempt=%s", r["attempt_id"])
    return ok
