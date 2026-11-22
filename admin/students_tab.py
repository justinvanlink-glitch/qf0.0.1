"""
Вкладка «Студенти» — білий список, імпорт, спроби, повторна спроба.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.db import Database
from core.mailer import MailerError, send_test_message

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "waiting": "Очікує",
    "in_progress": "Проходить",
    "completed": "Завершено",
    "blocked": "Заблоковано",
}


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


class StudentDialog(QDialog):
    """Діалог додавання / редагування студента."""

    def __init__(
        self,
        db: Database,
        parent: QWidget | None = None,
        student_id: int | None = None,
        data: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.student_id = student_id
        self.setWindowTitle("Студент" if student_id else "Новий студент")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Прізвище Ім'я По батькові")
        form.addRow("ПІБ:", self.name_edit)

        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("name@company.com")
        form.addRow("Корпоративна пошта:", self.email_edit)

        self.test_combo = QComboBox()
        self.test_combo.addItem("— не призначено —", None)
        for row in self.db.fetchall("SELECT id, title FROM tests ORDER BY title COLLATE NOCASE"):
            self.test_combo.addItem(row["title"], row["id"])
        form.addRow("Тест:", self.test_combo)

        self.attempts_spin = QSpinBox()
        self.attempts_spin.setRange(1, 100)
        self.attempts_spin.setValue(1)
        form.addRow("Дозволено спроб:", self.attempts_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if data:
            self.name_edit.setText(data.get("full_name", ""))
            self.email_edit.setText(data.get("email", ""))
            self.attempts_spin.setValue(int(data.get("attempts_allowed") or 1))
            tid = data.get("test_id")
            idx = self.test_combo.findData(tid)
            if idx >= 0:
                self.test_combo.setCurrentIndex(idx)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        email = _normalize_email(self.email_edit.text())
        if not name:
            QMessageBox.warning(self, "Помилка", "Вкажіть ПІБ.")
            return
        if not email or "@" not in email:
            QMessageBox.warning(self, "Помилка", "Вкажіть коректну корпоративну пошту.")
            return

        # Унікальність email
        existing = self.db.fetchone(
            "SELECT id FROM students WHERE email = ? COLLATE NOCASE", (email,)
        )
        if existing and existing["id"] != self.student_id:
            QMessageBox.warning(self, "Помилка", f"Пошта «{email}» уже є у списку.")
            return

        self.accept()

    def get_data(self) -> dict:
        return {
            "full_name": self.name_edit.text().strip(),
            "email": _normalize_email(self.email_edit.text()),
            "test_id": self.test_combo.currentData(),
            "attempts_allowed": self.attempts_spin.value(),
        }


class StudentsTab(QWidget):
    """Вкладка керування білим списком студентів."""

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

        # Компактний хедер з лого
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
        title = QLabel("Студенти")
        title.setObjectName("titleLabel")
        title.setStyleSheet("font-size: 18px;")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        # Панель пошуку та фільтра
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("Пошук:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("ПІБ або email…")
        self.search_edit.setMinimumHeight(36)
        self.search_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.search_edit, stretch=1)

        top.addWidget(QLabel("Статус:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("Усі", "")
        for key, label in STATUS_LABELS.items():
            self.status_filter.addItem(label, key)
        self.status_filter.setMinimumHeight(36)
        self.status_filter.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(self.status_filter)
        root.addLayout(top)

        # Таблиця
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ПІБ", "Email", "Тест", "Спроб", "Статус", "ID"]
        )
        self.table.setColumnHidden(5, True)  # ID
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._edit_student)
        root.addWidget(self.table, stretch=1)

        # Кнопки
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_add = QPushButton("Додати")
        self.btn_add.setMinimumHeight(36)
        self.btn_add.clicked.connect(self._add_student)
        self.btn_edit = QPushButton("Редагувати")
        self.btn_edit.setObjectName("secondaryButton")
        self.btn_edit.setMinimumHeight(36)
        self.btn_edit.clicked.connect(self._edit_student)
        self.btn_delete = QPushButton("Видалити")
        self.btn_delete.setObjectName("dangerButton")
        self.btn_delete.setMinimumHeight(36)
        self.btn_delete.clicked.connect(self._delete_student)
        self.btn_retry = QPushButton("Дозволити повторну спробу")
        self.btn_retry.setObjectName("secondaryButton")
        self.btn_retry.setMinimumHeight(36)
        self.btn_retry.clicked.connect(self._allow_retry)
        self.btn_import = QPushButton("Імпорт Excel/CSV")
        self.btn_import.setObjectName("secondaryButton")
        self.btn_import.setMinimumHeight(36)
        self.btn_import.clicked.connect(self._import_file)
        self.btn_smtp_test = QPushButton("Тестове повідомлення SMTP")
        self.btn_smtp_test.setObjectName("secondaryButton")
        self.btn_smtp_test.setMinimumHeight(36)
        self.btn_smtp_test.clicked.connect(self._smtp_test)

        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_edit)
        btns.addWidget(self.btn_delete)
        btns.addWidget(self.btn_retry)
        btns.addWidget(self.btn_import)
        btns.addStretch()
        btns.addWidget(self.btn_smtp_test)
        root.addLayout(btns)

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("subtitleLabel")
        root.addWidget(self.stats_label)

    # ------------------------------------------------------------------ дані
    def reload(self) -> None:
        """Перезавантажує таблицю з БД."""
        rows = self.db.fetchall(
            """
            SELECT s.id, s.full_name, s.email, s.test_id, s.attempts_allowed,
                   t.title AS test_title,
                   (
                       SELECT a.status FROM attempts a
                       WHERE a.student_id = s.id
                       ORDER BY a.id DESC LIMIT 1
                   ) AS last_status,
                   (
                       SELECT COUNT(*) FROM attempts a
                       WHERE a.student_id = s.id
                         AND a.status IN ('in_progress', 'completed', 'blocked')
                   ) AS used_attempts
            FROM students s
            LEFT JOIN tests t ON t.id = s.test_id
            ORDER BY s.full_name COLLATE NOCASE
            """
        )
        self._all_rows = [dict(r) for r in rows]
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_edit.text().strip().lower()
        status_key = self.status_filter.currentData() or ""

        filtered = []
        for r in self._all_rows:
            status = r.get("last_status") or "waiting"
            if status_key and status != status_key:
                continue
            if query:
                hay = f"{r.get('full_name', '')} {r.get('email', '')}".lower()
                if query not in hay:
                    continue
            filtered.append(r)

        self.table.setRowCount(len(filtered))
        for i, r in enumerate(filtered):
            status = r.get("last_status") or "waiting"
            status_text = STATUS_LABELS.get(status, status)

            self.table.setItem(i, 0, QTableWidgetItem(r.get("full_name") or ""))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("email") or ""))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("test_title") or "—"))
            attempts_text = f"{r.get('used_attempts') or 0} / {r.get('attempts_allowed') or 1}"
            self.table.setItem(i, 3, QTableWidgetItem(attempts_text))
            self.table.setItem(i, 4, QTableWidgetItem(status_text))
            id_item = QTableWidgetItem(str(r["id"]))
            id_item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.table.setItem(i, 5, id_item)

        self.stats_label.setText(f"Показано: {len(filtered)} з {len(self._all_rows)}")

    def _selected_student_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 5)
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _selected_row_data(self) -> dict | None:
        sid = self._selected_student_id()
        if sid is None:
            return None
        for r in self._all_rows:
            if r["id"] == sid:
                return r
        return None

    # ------------------------------------------------------------------ CRUD
    def _add_student(self) -> None:
        dlg = StudentDialog(self.db, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        try:
            sid = self.db.insert(
                "students",
                {
                    "full_name": data["full_name"],
                    "email": data["email"],
                    "test_id": data["test_id"],
                    "attempts_allowed": data["attempts_allowed"],
                },
            )
            self.db.log_audit("student_created", "admin", f"id={sid}, email={data['email']}")
            self.reload()
        except Exception as exc:
            logger.exception("Помилка додавання студента")
            QMessageBox.critical(self, "Помилка", str(exc))

    def _edit_student(self) -> None:
        row = self._selected_row_data()
        if not row:
            QMessageBox.information(self, "Студенти", "Виберіть студента в таблиці.")
            return
        dlg = StudentDialog(self.db, self, student_id=row["id"], data=row)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        try:
            self.db.update(
                "students",
                {
                    "full_name": data["full_name"],
                    "email": data["email"],
                    "test_id": data["test_id"],
                    "attempts_allowed": data["attempts_allowed"],
                },
                "id = ?",
                (row["id"],),
            )
            self.db.log_audit("student_updated", "admin", f"id={row['id']}, email={data['email']}")
            self.reload()
        except Exception as exc:
            logger.exception("Помилка оновлення студента")
            QMessageBox.critical(self, "Помилка", str(exc))

    def _delete_student(self) -> None:
        row = self._selected_row_data()
        if not row:
            QMessageBox.information(self, "Студенти", "Виберіть студента в таблиці.")
            return
        reply = QMessageBox.question(
            self,
            "Підтвердження",
            f"Видалити студента «{row['full_name']}» ({row['email']})?\n"
            "Усі пов'язані спроби також будуть видалені.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.db.execute("DELETE FROM students WHERE id = ?", (row["id"],))
        self.db.log_audit("student_deleted", "admin", f"id={row['id']}, email={row['email']}")
        self.reload()

    def _allow_retry(self) -> None:
        row = self._selected_row_data()
        if not row:
            QMessageBox.information(self, "Студенти", "Виберіть студента в таблиці.")
            return

        # +1 до attempts_allowed
        new_allowed = int(row.get("attempts_allowed") or 1) + 1
        self.db.update(
            "students",
            {"attempts_allowed": new_allowed},
            "id = ?",
            (row["id"],),
        )

        # Якщо останній attempt blocked/completed — статус знову «очікує»
        # (новий attempt створюється при старті тесту на клієнті)
        last = self.db.fetchone(
            "SELECT id, status FROM attempts WHERE student_id = ? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        )
        details = f"email={row['email']}, attempts_allowed={new_allowed}"
        if last and last["status"] in ("blocked", "completed", "in_progress"):
            details += f", previous_attempt={last['id']} status={last['status']}"

        self.db.log_audit("retry_allowed", "admin", details)
        QMessageBox.information(
            self,
            "Повторна спроба",
            f"Студенту «{row['full_name']}» дозволено спроб: {new_allowed}.\n"
            "Статус знову «Очікує» при наступному вході.",
        )
        self.reload()

    # ------------------------------------------------------------------ імпорт
    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Імпорт студентів",
            "",
            "Excel / CSV (*.xlsx *.csv)",
        )
        if not path:
            return
        path_obj = Path(path)
        try:
            if path_obj.suffix.lower() == ".csv":
                records = self._parse_csv(path_obj)
            else:
                records = self._parse_xlsx(path_obj)
        except Exception as exc:
            logger.exception("Помилка читання файлу імпорту")
            QMessageBox.critical(self, "Помилка", f"Не вдалося прочитати файл:\n{exc}")
            return

        if not records:
            QMessageBox.warning(self, "Імпорт", "У файлі не знайдено рядків з даними.")
            return

        # Мапа назва тесту → id
        tests = {
            (r["title"] or "").strip().lower(): r["id"]
            for r in self.db.fetchall("SELECT id, title FROM tests")
        }

        added = 0
        skipped = 0
        errors: list[str] = []

        for i, rec in enumerate(records, start=2):
            name = (rec.get("full_name") or "").strip()
            email = _normalize_email(rec.get("email") or "")
            test_name = (rec.get("test_name") or "").strip()
            attempts = rec.get("attempts_allowed") or 1

            if not name or not email:
                errors.append(f"Рядок {i}: відсутні ПІБ або email")
                skipped += 1
                continue
            if "@" not in email:
                errors.append(f"Рядок {i}: некоректний email «{email}»")
                skipped += 1
                continue

            existing = self.db.fetchone(
                "SELECT id FROM students WHERE email = ? COLLATE NOCASE", (email,)
            )
            if existing:
                errors.append(f"Рядок {i}: пошта «{email}» уже існує — пропущено")
                skipped += 1
                continue

            test_id = None
            if test_name:
                test_id = tests.get(test_name.lower())
                if test_id is None:
                    errors.append(f"Рядок {i}: тест «{test_name}» не знайдено")

            try:
                attempts_val = int(attempts)
                if attempts_val < 1:
                    attempts_val = 1
            except (TypeError, ValueError):
                attempts_val = 1

            self.db.insert(
                "students",
                {
                    "full_name": name,
                    "email": email,
                    "test_id": test_id,
                    "attempts_allowed": attempts_val,
                },
            )
            added += 1

        self.db.log_audit(
            "students_imported",
            "admin",
            f"added={added}, skipped={skipped}, file={path}",
        )
        self.reload()

        msg = f"Додано: {added}\nПропущено: {skipped}"
        if errors:
            msg += "\n\nДеталі:\n" + "\n".join(errors[:15])
            if len(errors) > 15:
                msg += f"\n… ще {len(errors) - 15}"
        QMessageBox.information(self, "Імпорт завершено", msg)

    def _parse_csv(self, path: Path) -> list[dict]:
        records = []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            # Підтримка різних назв колонок
            for row in reader:
                mapped = self._map_row(row)
                if mapped:
                    records.append(mapped)
        return records

    def _parse_xlsx(self, path: Path) -> list[dict]:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return []

        headers = [str(c).strip().lower() if c else "" for c in rows[0]]
        records = []
        for row in rows[1:]:
            if not row:
                continue
            d = {}
            for i, h in enumerate(headers):
                if i < len(row):
                    d[h] = row[i]
            mapped = self._map_row(d)
            if mapped:
                records.append(mapped)
        return records

    @staticmethod
    def _map_row(row: dict) -> dict | None:
        """Нормалізує ключі: ПІБ / full_name / name, email, тест / test, спроби."""
        lower = {str(k).strip().lower(): v for k, v in row.items() if k is not None}

        name = (
            lower.get("піб")
            or lower.get("full_name")
            or lower.get("name")
            or lower.get("фїб")
            or lower.get("студент")
        )
        email = lower.get("email") or lower.get("пошта") or lower.get("e-mail") or lower.get("mail")
        test_name = (
            lower.get("тест")
            or lower.get("test")
            or lower.get("test_name")
            or lower.get("назва тесту")
        )
        attempts = (
            lower.get("спроби")
            or lower.get("attempts")
            or lower.get("attempts_allowed")
            or lower.get("дозволено спроб")
            or 1
        )

        if name is None and email is None:
            return None
        return {
            "full_name": str(name).strip() if name else "",
            "email": str(email).strip() if email else "",
            "test_name": str(test_name).strip() if test_name else "",
            "attempts_allowed": attempts,
        }

    # ------------------------------------------------------------------ SMTP
    def _smtp_test(self) -> None:
        email, ok = QInputDialog.getText(
            self,
            "Тестове повідомлення",
            "Email для тестового листа:",
            text=self.config.get("smtp", {}).get("from_address", ""),
        )
        if not ok or not email.strip():
            return
        email = email.strip()
        try:
            send_test_message(self.config, email)
            QMessageBox.information(
                self,
                "SMTP",
                f"Тестовий лист надіслано на {email}.\nПеревірте скриньку.",
            )
        except MailerError as exc:
            QMessageBox.critical(self, "Помилка SMTP", str(exc))
        except Exception as exc:
            logger.exception("Неочікувана помилка SMTP")
            QMessageBox.critical(self, "Помилка", str(exc))
