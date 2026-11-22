"""
Вкладка «Результати»: таблиця спроб, деталі, PDF, повторна відправка, експорт Excel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.db import Database
from core.report_builder import build_report, send_report

logger = logging.getLogger(__name__)

STATUS_UA = {
    "waiting": "Очікує",
    "in_progress": "Проходить",
    "completed": "Завершено",
    "blocked": "Заблоковано",
}


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(iso)[:16]


def _fmt_duration(start: str | None, end: str | None, qtimes_sum: int = 0) -> str:
    sec = qtimes_sum
    if start and end:
        try:
            t0 = datetime.fromisoformat(start)
            t1 = datetime.fromisoformat(end)
            sec = max(sec, int((t1 - t0).total_seconds()))
        except Exception:
            pass
    sec = max(0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class DetailsDialog(QDialog):
    """Деталі спроби: відповіді, час, порушення, скріншоти."""

    def __init__(self, db: Database, attempt_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.attempt_id = attempt_id
        self.setWindowTitle(f"Деталі спроби #{attempt_id}")
        self.setMinimumSize(700, 500)
        self.resize(800, 600)

        layout = QVBoxLayout(self)

        attempt = db.fetchone("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
        student = db.fetchone(
            "SELECT * FROM students WHERE id = ?", (attempt["student_id"],)
        ) if attempt else None
        test = db.fetchone(
            "SELECT * FROM tests WHERE id = ?", (attempt["test_id"],)
        ) if attempt else None

        header = QLabel(
            f"<b>{(student or {}).get('full_name', '')}</b> "
            f"({(student or {}).get('email', '')}) — "
            f"{(test or {}).get('title', '')}<br>"
            f"Бали: {attempt['score'] if attempt else 0:g} / "
            f"{attempt['max_score'] if attempt else 0:g} "
            f"({attempt['percent'] if attempt else 0:g}%) · "
            f"Статус: {STATUS_UA.get((attempt or {}).get('status', ''), '')}"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        # Відповіді + час
        layout.addWidget(QLabel("<b>Відповіді та час</b>"))
        ans_table = QTableWidget(0, 5)
        ans_table.setHorizontalHeaderLabels(
            ["№", "Питання", "Відповідь", "Бали", "Час (с)"]
        )
        ans_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ans_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        questions = db.fetchall(
            "SELECT * FROM questions WHERE test_id = ? ORDER BY order_index, id",
            (attempt["test_id"],),
        ) if attempt else []
        qtimes = {
            r["question_id"]: r["seconds"]
            for r in db.fetchall(
                "SELECT question_id, seconds FROM question_times WHERE attempt_id = ?",
                (attempt_id,),
            )
        }
        answers = {
            r["question_id"]: r
            for r in db.fetchall(
                "SELECT * FROM answers WHERE attempt_id = ?", (attempt_id,)
            )
        }

        ans_table.setRowCount(len(questions))
        for i, q in enumerate(questions):
            ans = answers.get(q["id"])
            selected = (ans["selected"] if ans else "") or ""
            # Для choice — показати тексти варіантів
            display = selected
            if q["qtype"] in ("single", "multiple") and selected:
                try:
                    import json
                    ids = json.loads(selected)
                    opts = {
                        o["id"]: o["text"]
                        for o in db.fetchall(
                            "SELECT id, text FROM options WHERE question_id = ?",
                            (q["id"],),
                        )
                    }
                    display = ", ".join(opts.get(i, str(i)) for i in ids)
                except Exception:
                    pass
            pts = f"{ans['points_awarded']:g}" if ans else "0"
            ans_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            preview = (q["text"] or "")[:80]
            ans_table.setItem(i, 1, QTableWidgetItem(preview))
            ans_table.setItem(i, 2, QTableWidgetItem(display[:100]))
            ans_table.setItem(i, 3, QTableWidgetItem(pts))
            ans_table.setItem(i, 4, QTableWidgetItem(str(qtimes.get(q["id"], 0))))
        layout.addWidget(ans_table, stretch=1)

        # Порушення
        layout.addWidget(QLabel("<b>Порушення</b>"))
        violations = db.fetchall(
            "SELECT * FROM violations WHERE attempt_id = ? ORDER BY occurred_at",
            (attempt_id,),
        )
        if violations:
            v_table = QTableWidget(len(violations), 4)
            v_table.setHorizontalHeaderLabels(["Час", "Тип", "Питання", "Деталі"])
            v_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            v_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for i, v in enumerate(violations):
                v_table.setItem(i, 0, QTableWidgetItem(_fmt_dt(v["occurred_at"])))
                v_table.setItem(i, 1, QTableWidgetItem(v["vtype"]))
                v_table.setItem(i, 2, QTableWidgetItem(str(v["question_number"] or "—")))
                v_table.setItem(i, 3, QTableWidgetItem(v["details"] or ""))
            layout.addWidget(v_table)
        else:
            layout.addWidget(QLabel("Порушень немає."))

        # Галерея скріншотів
        shots = db.fetchall(
            "SELECT * FROM screenshots WHERE attempt_id = ? ORDER BY captured_at",
            (attempt_id,),
        )
        if shots:
            layout.addWidget(QLabel(f"<b>Скріншоти ({len(shots)})</b>"))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMaximumHeight(200)
            gallery = QWidget()
            gal_layout = QHBoxLayout(gallery)
            for sh in shots[:20]:
                fp = sh["file_path"]
                if fp and Path(fp).is_file():
                    lbl = QLabel()
                    pix = QPixmap(fp)
                    if not pix.isNull():
                        lbl.setPixmap(
                            pix.scaled(
                                160,
                                90,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                        lbl.setToolTip(f"{sh['captured_at']}\n{fp}")
                        gal_layout.addWidget(lbl)
            gal_layout.addStretch()
            scroll.setWidget(gallery)
            layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class ResultsTab(QWidget):
    def __init__(self, db: Database, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # Хедер з лого
        header = QHBoxLayout()
        header.setSpacing(10)
        logo_label = QLabel()
        try:
            pixmap = QPixmap("assets/logo.png")
            if not pixmap.isNull():
                logo_label.setPixmap(pixmap.scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass
        header.addWidget(logo_label)
        title = QLabel("Результати")
        title.setObjectName("titleLabel")
        title.setStyleSheet("font-size: 18px;")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "Студент",
                "Email",
                "Тест",
                "Бали",
                "%",
                "Час",
                "Порушення",
                "Статус / Відправка",
                "ID",
            ]
        )
        self.table.setColumnHidden(8, True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._show_details)
        root.addWidget(self.table, stretch=1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_details = QPushButton("Деталі")
        self.btn_details.setObjectName("secondaryButton")
        self.btn_details.setMinimumHeight(36)
        self.btn_details.clicked.connect(self._show_details)

        self.btn_pdf = QPushButton("Відкрити PDF")
        self.btn_pdf.setObjectName("secondaryButton")
        self.btn_pdf.setMinimumHeight(36)
        self.btn_pdf.clicked.connect(self._open_pdf)

        self.btn_resend = QPushButton("Надіслати повторно")
        self.btn_resend.setObjectName("secondaryButton")
        self.btn_resend.setMinimumHeight(36)
        self.btn_resend.clicked.connect(self._resend)

        self.btn_export = QPushButton("Експорт усіх в Excel")
        self.btn_export.setMinimumHeight(36)
        self.btn_export.clicked.connect(self._export_excel)

        self.btn_refresh = QPushButton("Оновити")
        self.btn_refresh.setObjectName("secondaryButton")
        self.btn_refresh.setMinimumHeight(36)
        self.btn_refresh.clicked.connect(self.reload)

        btns.addWidget(self.btn_details)
        btns.addWidget(self.btn_pdf)
        btns.addWidget(self.btn_resend)
        btns.addWidget(self.btn_export)
        btns.addStretch()
        btns.addWidget(self.btn_refresh)
        root.addLayout(btns)

        self.stats = QLabel("")
        self.stats.setObjectName("subtitleLabel")
        root.addWidget(self.stats)

    def reload(self) -> None:
        rows = self.db.fetchall(
            """
            SELECT a.id, a.score, a.max_score, a.percent, a.status, a.report_sent,
                   a.report_path, a.start_time, a.end_time,
                   s.full_name, s.email,
                   t.title AS test_title,
                   (SELECT COUNT(*) FROM violations v WHERE v.attempt_id = a.id) AS vcount,
                   (SELECT COALESCE(SUM(seconds), 0) FROM question_times qt
                    WHERE qt.attempt_id = a.id) AS time_sum
            FROM attempts a
            JOIN students s ON s.id = a.student_id
            JOIN tests t ON t.id = a.test_id
            WHERE a.status IN ('completed', 'blocked', 'in_progress')
            ORDER BY a.id DESC
            """
        )
        self._rows = [dict(r) for r in rows]
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            self.table.setItem(i, 0, QTableWidgetItem(r.get("full_name") or ""))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("email") or ""))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("test_title") or ""))
            score_txt = f"{r.get('score') or 0:g}/{r.get('max_score') or 0:g}"
            self.table.setItem(i, 3, QTableWidgetItem(score_txt))
            self.table.setItem(i, 4, QTableWidgetItem(f"{r.get('percent') or 0:g}"))
            self.table.setItem(
                i,
                5,
                QTableWidgetItem(
                    _fmt_duration(r.get("start_time"), r.get("end_time"), int(r.get("time_sum") or 0))
                ),
            )
            self.table.setItem(i, 6, QTableWidgetItem(str(r.get("vcount") or 0)))
            st = STATUS_UA.get(r.get("status") or "", r.get("status") or "")
            sent = "Надіслано" if r.get("report_sent") else "Не відправлено"
            self.table.setItem(i, 7, QTableWidgetItem(f"{st} / {sent}"))
            id_item = QTableWidgetItem(str(r["id"]))
            id_item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.table.setItem(i, 8, id_item)

        self.stats.setText(f"Усього спроб: {len(self._rows)}")

    def _selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 8)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_details(self) -> None:
        aid = self._selected_id()
        if aid is None:
            QMessageBox.information(self, "Результати", "Виберіть рядок у таблиці.")
            return
        DetailsDialog(self.db, aid, self).exec()

    def _open_pdf(self) -> None:
        aid = self._selected_id()
        if aid is None:
            QMessageBox.information(self, "Результати", "Виберіть рядок у таблиці.")
            return
        row = self.db.fetchone("SELECT report_path FROM attempts WHERE id = ?", (aid,))
        path = Path(row["report_path"]) if row and row["report_path"] else None
        if not path or not path.is_file():
            try:
                path = build_report(self.db, aid)
            except Exception as exc:
                QMessageBox.critical(self, "PDF", f"Не вдалося створити звіт:\n{exc}")
                return
        # Відкрити системним переглядачем
        import os
        import subprocess
        import sys

        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            QMessageBox.information(self, "PDF", f"Файл: {path}\n\n{exc}")

    def _resend(self) -> None:
        aid = self._selected_id()
        if aid is None:
            QMessageBox.information(self, "Результати", "Виберіть рядок у таблиці.")
            return
        try:
            row = self.db.fetchone("SELECT report_path FROM attempts WHERE id = ?", (aid,))
            path = Path(row["report_path"]) if row and row["report_path"] else None
            if not path or not path.is_file():
                path = build_report(self.db, aid)
            ok = send_report(self.db, self.config, aid, path)
            if ok:
                QMessageBox.information(self, "Відправка", "Звіт надіслано.")
            else:
                QMessageBox.warning(
                    self,
                    "Відправка",
                    "Не вдалося надіслати. Перевірте SMTP і report_recipients у config.json.",
                )
            self.reload()
        except Exception as exc:
            logger.exception("resend")
            QMessageBox.critical(self, "Помилка", str(exc))

    def _export_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Експорт результатів",
            "results.xlsx",
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font

            wb = Workbook()
            ws = wb.active
            ws.title = "Результати"
            headers = [
                "ID спроби",
                "ПІБ",
                "Email",
                "Тест",
                "Бали",
                "Максимум",
                "%",
                "Склав",
                "Статус",
                "Початок",
                "Кінець",
                "Час (сек)",
                "Порушень",
                "Звіт надіслано",
                "Шлях до PDF",
            ]
            ws.append(headers)
            for c in ws[1]:
                c.font = Font(bold=True)

            for r in self._rows:
                att = self.db.fetchone("SELECT * FROM attempts WHERE id = ?", (r["id"],))
                ws.append(
                    [
                        r["id"],
                        r.get("full_name"),
                        r.get("email"),
                        r.get("test_title"),
                        r.get("score"),
                        r.get("max_score"),
                        r.get("percent"),
                        "так" if att and att["passed"] else ("ні" if att and att["passed"] is not None else "—"),
                        STATUS_UA.get(r.get("status") or "", r.get("status")),
                        r.get("start_time"),
                        r.get("end_time"),
                        r.get("time_sum"),
                        r.get("vcount"),
                        "так" if r.get("report_sent") else "ні",
                        r.get("report_path"),
                    ]
                )
            wb.save(path)
            QMessageBox.information(self, "Експорт", f"Збережено:\n{path}")
        except Exception as exc:
            logger.exception("export")
            QMessageBox.critical(self, "Помилка", str(exc))
