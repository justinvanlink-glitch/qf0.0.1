"""
Вкладка «Тести» — створення/редагування тестів і питань.
Простий інтерфейс для нетехнічних користувачів.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.db import Database
from core.excel_import import generate_template, parse_excel, questions_to_db_payload
from core.models import QuestionType

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OptionRow(QWidget):
    """Один рядок варіанту відповіді: текст + позначка «правильний»."""

    def __init__(self, text: str = "", is_correct: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self.correct_cb = QCheckBox()
        self.correct_cb.setChecked(is_correct)
        self.correct_cb.setToolTip("Правильна відповідь")

        self.text_edit = QLineEdit(text)
        self.text_edit.setPlaceholderText("Текст варіанту")

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedWidth(32)
        self.remove_btn.setObjectName("secondaryButton")
        self.remove_btn.setToolTip("Видалити варіант")

        layout.addWidget(self.correct_cb)
        layout.addWidget(self.text_edit, stretch=1)
        layout.addWidget(self.remove_btn)

    def get_data(self) -> tuple[str, bool]:
        return self.text_edit.text().strip(), self.correct_cb.isChecked()


class TestsTab(QWidget):
    """Вкладка керування тестами та питаннями."""

    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._current_test_id: int | None = None
        self._current_question_id: int | None = None
        self._option_rows: list[OptionRow] = []
        self._building_ui = False

        self._build_ui()
        self._load_tests()

    # ------------------------------------------------------------------ UI
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
        title = QLabel("Тести")
        title.setObjectName("titleLabel")
        title.setStyleSheet("font-size: 18px;")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ---- Ліва панель: список тестів ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        left_layout.addWidget(QLabel("Список тестів"))
        self.tests_list = QListWidget()
        self.tests_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tests_list.currentItemChanged.connect(self._on_test_selected)
        left_layout.addWidget(self.tests_list, stretch=1)

        tests_btns = QHBoxLayout()
        tests_btns.setSpacing(8)
        self.btn_new_test = QPushButton("Новий тест")
        self.btn_new_test.setMinimumHeight(36)
        self.btn_new_test.clicked.connect(self._new_test)
        self.btn_delete_test = QPushButton("Видалити")
        self.btn_delete_test.setObjectName("dangerButton")
        self.btn_delete_test.setMinimumHeight(36)
        self.btn_delete_test.clicked.connect(self._delete_test)
        tests_btns.addWidget(self.btn_new_test)
        tests_btns.addWidget(self.btn_delete_test)
        left_layout.addLayout(tests_btns)

        # Імпорт з Excel
        import_btns = QHBoxLayout()
        import_btns.setSpacing(8)
        self.btn_import = QPushButton("Імпортувати з Excel")
        self.btn_import.setObjectName("secondaryButton")
        self.btn_import.setMinimumHeight(36)
        self.btn_import.clicked.connect(self._import_excel)
        self.btn_template = QPushButton("Завантажити шаблон")
        self.btn_template.setObjectName("secondaryButton")
        self.btn_template.setMinimumHeight(36)
        self.btn_template.clicked.connect(self._download_template)
        import_btns.addWidget(self.btn_import)
        import_btns.addWidget(self.btn_template)
        left_layout.addLayout(import_btns)

        splitter.addWidget(left)

        # ---- Права панель: властивості тесту + питання ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Властивості тесту
        props_group = QGroupBox("Властивості тесту")
        props_form = QFormLayout(props_group)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Назва тесту")
        props_form.addRow("Назва:", self.title_edit)

        self.time_spin = QSpinBox()
        self.time_spin.setRange(1, 600)
        self.time_spin.setValue(60)
        self.time_spin.setSuffix(" хв")
        props_form.addRow("Ліміт часу:", self.time_spin)

        self.violation_spin = QSpinBox()
        self.violation_spin.setRange(1, 100)
        self.violation_spin.setValue(5)
        props_form.addRow("Поріг порушень:", self.violation_spin)

        self.shuffle_q_cb = QCheckBox("Перемішувати питання")
        props_form.addRow("", self.shuffle_q_cb)

        self.shuffle_o_cb = QCheckBox("Перемішувати варіанти")
        props_form.addRow("", self.shuffle_o_cb)

        self.pass_spin = QDoubleSpinBox()
        self.pass_spin.setRange(0, 100)
        self.pass_spin.setDecimals(1)
        self.pass_spin.setSuffix(" %")
        self.pass_spin.setSpecialValueText("Не задано")
        self.pass_spin.setValue(0)
        # 0 трактуємо як «не задано»
        props_form.addRow("Прохідний бал:", self.pass_spin)

        save_test_btn = QPushButton("Зберегти властивості тесту")
        save_test_btn.clicked.connect(self._save_test_props)
        props_form.addRow(save_test_btn)

        right_layout.addWidget(props_group)

        # Питання
        questions_group = QGroupBox("Питання")
        q_layout = QHBoxLayout(questions_group)

        # Список питань
        q_left = QVBoxLayout()
        self.questions_list = QListWidget()
        self.questions_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.questions_list.currentItemChanged.connect(self._on_question_selected)
        q_left.addWidget(self.questions_list, stretch=1)

        q_nav = QHBoxLayout()
        self.btn_q_up = QPushButton("↑")
        self.btn_q_up.setFixedWidth(40)
        self.btn_q_up.setObjectName("secondaryButton")
        self.btn_q_up.clicked.connect(lambda: self._move_question(-1))
        self.btn_q_down = QPushButton("↓")
        self.btn_q_down.setFixedWidth(40)
        self.btn_q_down.setObjectName("secondaryButton")
        self.btn_q_down.clicked.connect(lambda: self._move_question(1))
        q_nav.addWidget(self.btn_q_up)
        q_nav.addWidget(self.btn_q_down)
        q_left.addLayout(q_nav)

        q_btns = QHBoxLayout()
        self.btn_add_q = QPushButton("Додати питання")
        self.btn_add_q.clicked.connect(self._add_question)
        self.btn_del_q = QPushButton("Видалити")
        self.btn_del_q.setObjectName("dangerButton")
        self.btn_del_q.clicked.connect(self._delete_question)
        q_btns.addWidget(self.btn_add_q)
        q_btns.addWidget(self.btn_del_q)
        q_left.addLayout(q_btns)

        q_layout.addLayout(q_left, stretch=1)

        # Редактор питання
        q_right = QVBoxLayout()
        form = QFormLayout()

        self.q_text = QTextEdit()
        self.q_text.setPlaceholderText("Текст питання")
        self.q_text.setMaximumHeight(100)
        form.addRow("Питання:", self.q_text)

        self.q_type = QComboBox()
        self.q_type.addItem("Одна правильна (single)", QuestionType.SINGLE.value)
        self.q_type.addItem("Кілька правильних (multiple)", QuestionType.MULTIPLE.value)
        self.q_type.addItem("Відкрита відповідь (open)", QuestionType.OPEN.value)
        self.q_type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Тип:", self.q_type)

        self.q_points = QDoubleSpinBox()
        self.q_points.setRange(0.01, 1000)
        self.q_points.setDecimals(2)
        self.q_points.setSingleStep(0.25)
        self.q_points.setValue(1.0)
        self.q_points.setToolTip(
            "Бали за питання. Можна дробові: 0.25, 0.5, 1.5 тощо.\n"
            "Для multiple при partial_credit=true бал ділиться пропорційно між правильними."
        )
        form.addRow("Бали:", self.q_points)

        # Підказка-правила залежно від типу питання
        self.type_hint = QLabel()
        self.type_hint.setObjectName("subtitleLabel")
        self.type_hint.setWordWrap(True)
        self.type_hint.setStyleSheet(
            "background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; "
            "padding: 8px; color: #1e40af; font-size: 12px;"
        )
        form.addRow(self.type_hint)

        q_right.addLayout(form)

        # Варіанти (для single/multiple)
        self.options_group = QGroupBox("Варіанти відповідей")
        self.options_layout = QVBoxLayout(self.options_group)
        self.options_container = QVBoxLayout()
        self.options_layout.addLayout(self.options_container)

        add_opt_btn = QPushButton("Додати варіант")
        add_opt_btn.setObjectName("secondaryButton")
        add_opt_btn.clicked.connect(self._add_option_row)
        self.options_layout.addWidget(add_opt_btn)
        q_right.addWidget(self.options_group)

        # Відкриті відповіді
        self.open_group = QGroupBox("Допустимі відповіді (через «;»)")
        open_layout = QVBoxLayout(self.open_group)
        self.open_answers_edit = QLineEdit()
        self.open_answers_edit.setPlaceholderText("наприклад: Київ; Kyiv; Київ місто")
        open_layout.addWidget(self.open_answers_edit)
        hint = QLabel("Порівняння без урахування регістру та зайвих пробілів.")
        hint.setObjectName("subtitleLabel")
        open_layout.addWidget(hint)
        q_right.addWidget(self.open_group)
        self.open_group.hide()

        self.btn_save_q = QPushButton("Зберегти питання")
        self.btn_save_q.clicked.connect(self._save_question)
        q_right.addWidget(self.btn_save_q)
        q_right.addStretch()

        q_layout.addLayout(q_right, stretch=2)
        right_layout.addWidget(questions_group, stretch=1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter)
        self._set_editor_enabled(False)

    def _set_editor_enabled(self, enabled: bool) -> None:
        for w in (
            self.title_edit,
            self.time_spin,
            self.violation_spin,
            self.shuffle_q_cb,
            self.shuffle_o_cb,
            self.pass_spin,
            self.questions_list,
            self.btn_add_q,
            self.btn_del_q,
            self.btn_q_up,
            self.btn_q_down,
            self.q_text,
            self.q_type,
            self.q_points,
            self.btn_save_q,
            self.options_group,
            self.open_group,
        ):
            w.setEnabled(enabled)
        self.btn_delete_test.setEnabled(enabled and self._current_test_id is not None)

    # ------------------------------------------------------------------ Тести
    def _load_tests(self) -> None:
        self.tests_list.clear()
        rows = self.db.fetchall(
            "SELECT id, title FROM tests ORDER BY title COLLATE NOCASE"
        )
        for row in rows:
            item = QListWidgetItem(row["title"])
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.tests_list.addItem(item)

    def _on_test_selected(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if current is None:
            self._current_test_id = None
            self._set_editor_enabled(False)
            self.questions_list.clear()
            return

        test_id = current.data(Qt.ItemDataRole.UserRole)
        self._current_test_id = test_id
        self._set_editor_enabled(True)
        self._load_test_props(test_id)
        self._load_questions(test_id)
        self._clear_question_editor()

    def _load_test_props(self, test_id: int) -> None:
        row = self.db.fetchone("SELECT * FROM tests WHERE id = ?", (test_id,))
        if not row:
            return
        self.title_edit.setText(row["title"])
        self.time_spin.setValue(row["time_limit_minutes"])
        self.violation_spin.setValue(row["violation_threshold"])
        self.shuffle_q_cb.setChecked(bool(row["shuffle_questions"]))
        self.shuffle_o_cb.setChecked(bool(row["shuffle_options"]))
        pass_pct = row["pass_percent"]
        self.pass_spin.setValue(float(pass_pct) if pass_pct is not None else 0.0)

    def _new_test(self) -> None:
        title, ok = QInputDialog.getText(self, "Новий тест", "Назва тесту:")
        if not ok or not title.strip():
            return
        title = title.strip()
        test_id = self.db.insert(
            "tests",
            {
                "title": title,
                "time_limit_minutes": 60,
                "violation_threshold": 5,
                "shuffle_questions": 0,
                "shuffle_options": 0,
                "pass_percent": None,
                "created_at": _utc_now(),
            },
        )
        self.db.log_audit("test_created", "admin", f"id={test_id}, title={title}")
        self._load_tests()
        # Вибрати щойно створений
        for i in range(self.tests_list.count()):
            item = self.tests_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == test_id:
                self.tests_list.setCurrentItem(item)
                break

    def _save_test_props(self) -> None:
        if self._current_test_id is None:
            return
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Помилка", "Вкажіть назву тесту.")
            return

        pass_val = self.pass_spin.value()
        pass_percent = pass_val if pass_val > 0 else None

        self.db.update(
            "tests",
            {
                "title": title,
                "time_limit_minutes": self.time_spin.value(),
                "violation_threshold": self.violation_spin.value(),
                "shuffle_questions": 1 if self.shuffle_q_cb.isChecked() else 0,
                "shuffle_options": 1 if self.shuffle_o_cb.isChecked() else 0,
                "pass_percent": pass_percent,
            },
            "id = ?",
            (self._current_test_id,),
        )
        self.db.log_audit(
            "test_updated", "admin", f"id={self._current_test_id}, title={title}"
        )
        # Оновити назву в списку
        item = self.tests_list.currentItem()
        if item:
            item.setText(title)
        QMessageBox.information(self, "Збережено", "Властивості тесту збережено.")

    def _delete_test(self) -> None:
        if self._current_test_id is None:
            return
        reply = QMessageBox.question(
            self,
            "Підтвердження",
            "Видалити тест разом із усіма питаннями?\nЦю дію неможливо скасувати.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        tid = self._current_test_id
        self.db.execute("DELETE FROM tests WHERE id = ?", (tid,))
        self.db.log_audit("test_deleted", "admin", f"id={tid}")
        self._current_test_id = None
        self._load_tests()
        self._set_editor_enabled(False)
        self.questions_list.clear()
        self._clear_question_editor()

    # ------------------------------------------------------------------ Питання
    def _load_questions(self, test_id: int) -> None:
        self.questions_list.clear()
        rows = self.db.fetchall(
            "SELECT id, text, qtype, points, order_index FROM questions "
            "WHERE test_id = ? ORDER BY order_index, id",
            (test_id,),
        )
        for i, row in enumerate(rows, start=1):
            preview = (row["text"] or "")[:60]
            if len(row["text"] or "") > 60:
                preview += "…"
            label = f"{i}. [{row['qtype']}] {preview}  ({row['points']} б.)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.questions_list.addItem(item)

    def _on_question_selected(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if current is None or self._current_test_id is None:
            self._current_question_id = None
            self._clear_question_editor()
            return
        qid = current.data(Qt.ItemDataRole.UserRole)
        self._current_question_id = qid
        self._load_question(qid)

    def _clear_question_editor(self) -> None:
        self._current_question_id = None
        self.q_text.clear()
        self.q_type.setCurrentIndex(0)
        self.q_points.setValue(1.0)
        self.open_answers_edit.clear()
        self._clear_option_rows()
        self._on_type_changed()

    def _load_question(self, question_id: int) -> None:
        row = self.db.fetchone("SELECT * FROM questions WHERE id = ?", (question_id,))
        if not row:
            return
        self.q_text.setPlainText(row["text"])
        idx = self.q_type.findData(row["qtype"])
        if idx >= 0:
            self.q_type.setCurrentIndex(idx)
        self.q_points.setValue(float(row["points"]))
        self.open_answers_edit.setText(row["open_answers"] or "")

        self._clear_option_rows()
        if row["qtype"] in (QuestionType.SINGLE.value, QuestionType.MULTIPLE.value):
            opts = self.db.fetchall(
                "SELECT text, is_correct FROM options "
                "WHERE question_id = ? ORDER BY order_index, id",
                (question_id,),
            )
            for opt in opts:
                self._add_option_row(opt["text"], bool(opt["is_correct"]))
        self._on_type_changed()

    def _on_type_changed(self) -> None:
        qtype = self.q_type.currentData()
        is_open = qtype == QuestionType.OPEN.value
        self.options_group.setVisible(not is_open)
        self.open_group.setVisible(is_open)

        # Правила для кожного типу
        if qtype == QuestionType.SINGLE.value:
            self.type_hint.setText(
                "Правила (одна правильна):\n"
                "• Мінімум 2 варіанти відповіді.\n"
                "• Позначте рівно ОДИН правильний варіант галочкою.\n"
                "• Бал нараховується лише за вибір саме цього варіанту.\n"
                "• Бали можна дробові: 0.25, 0.5, 1.5 тощо."
            )
        elif qtype == QuestionType.MULTIPLE.value:
            self.type_hint.setText(
                "Правила (кілька правильних):\n"
                "• Мінімум 2 варіанти. Позначте всі правильні галочками.\n"
                "• partial_credit = false (за замовчуванням): бал лише за "
                "повністю правильний набір (усі потрібні + жоден зайвий).\n"
                "• partial_credit = true (config.json): кожна правильна відповідь "
                "оцінюється пропорційно — (кількість вірно вибраних / кількість "
                "правильних) × бали питання. Без штрафів за зайві.\n"
                "• Бали можна дробові: 0.25, 0.5, 1.5 тощо."
            )
        else:  # open
            self.type_hint.setText(
                "Правила (відкрита відповідь):\n"
                "• Варіанти не потрібні — заповніть поле «Допустимі відповіді».\n"
                "• Кілька допустимих відповідей через «;» (напр. Київ; Kyiv).\n"
                "• Порівняння без урахування регістру та зайвих пробілів.\n"
                "• Бал нараховується, якщо відповідь збігається з будь-якою допустимою.\n"
                "• Бали можна дробові: 0.25, 0.5, 1.5 тощо."
            )

    def _clear_option_rows(self) -> None:
        for row in self._option_rows:
            self.options_container.removeWidget(row)
            row.deleteLater()
        self._option_rows.clear()

    def _add_option_row(self, text: str = "", is_correct: bool = False) -> None:
        row = OptionRow(text, is_correct)
        row.remove_btn.clicked.connect(lambda: self._remove_option_row(row))
        self._option_rows.append(row)
        self.options_container.addWidget(row)

    def _remove_option_row(self, row: OptionRow) -> None:
        if row in self._option_rows:
            self._option_rows.remove(row)
            self.options_container.removeWidget(row)
            row.deleteLater()

    def _add_question(self) -> None:
        if self._current_test_id is None:
            return
        # Створюємо порожнє питання з наступним order_index
        max_order = self.db.fetchone(
            "SELECT COALESCE(MAX(order_index), -1) AS m FROM questions WHERE test_id = ?",
            (self._current_test_id,),
        )
        next_order = (max_order["m"] if max_order else -1) + 1

        qid = self.db.insert(
            "questions",
            {
                "test_id": self._current_test_id,
                "text": "Нове питання",
                "qtype": QuestionType.SINGLE.value,
                "points": 1.0,
                "order_index": next_order,
                "open_answers": "",
            },
        )
        # Два порожні варіанти за замовчуванням
        for i, txt in enumerate(("Варіант 1", "Варіант 2")):
            self.db.insert(
                "options",
                {
                    "question_id": qid,
                    "text": txt,
                    "is_correct": 1 if i == 0 else 0,
                    "order_index": i,
                },
            )
        self.db.log_audit("question_created", "admin", f"id={qid}, test_id={self._current_test_id}")
        self._load_questions(self._current_test_id)
        # Вибрати нове
        for i in range(self.questions_list.count()):
            item = self.questions_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == qid:
                self.questions_list.setCurrentItem(item)
                break

    def _save_question(self) -> None:
        if self._current_test_id is None or self._current_question_id is None:
            QMessageBox.warning(self, "Помилка", "Спочатку виберіть або створіть питання.")
            return

        text = self.q_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Помилка", "Текст питання не може бути порожнім.")
            return

        qtype = self.q_type.currentData()
        points = self.q_points.value()

        if qtype == QuestionType.OPEN.value:
            open_answers = self.open_answers_edit.text().strip()
            if not open_answers:
                QMessageBox.warning(
                    self, "Помилка", "Вкажіть хоча б одну допустиму відповідь (через «;»)."
                )
                return
            # Зберігаємо питання, видаляємо варіанти
            self.db.update(
                "questions",
                {
                    "text": text,
                    "qtype": qtype,
                    "points": points,
                    "open_answers": open_answers,
                },
                "id = ?",
                (self._current_question_id,),
            )
            self.db.execute(
                "DELETE FROM options WHERE question_id = ?", (self._current_question_id,)
            )
        else:
            # single / multiple
            options_data: list[tuple[str, bool]] = []
            for row in self._option_rows:
                t, correct = row.get_data()
                if t:
                    options_data.append((t, correct))

            if len(options_data) < 2:
                QMessageBox.warning(
                    self, "Помилка", "Для цього типу потрібно щонайменше 2 варіанти."
                )
                return
            correct_count = sum(1 for _, c in options_data if c)
            if correct_count == 0:
                QMessageBox.warning(self, "Помилка", "Позначте хоча б один правильний варіант.")
                return
            if qtype == QuestionType.SINGLE.value and correct_count > 1:
                QMessageBox.warning(
                    self,
                    "Помилка",
                    "Для типу «Одна правильна» можна позначити лише один варіант.",
                )
                return

            self.db.update(
                "questions",
                {
                    "text": text,
                    "qtype": qtype,
                    "points": points,
                    "open_answers": "",
                },
                "id = ?",
                (self._current_question_id,),
            )
            # Перезапис варіантів
            self.db.execute(
                "DELETE FROM options WHERE question_id = ?", (self._current_question_id,)
            )
            for i, (t, correct) in enumerate(options_data):
                self.db.insert(
                    "options",
                    {
                        "question_id": self._current_question_id,
                        "text": t,
                        "is_correct": 1 if correct else 0,
                        "order_index": i,
                    },
                )

        self.db.log_audit(
            "question_updated",
            "admin",
            f"id={self._current_question_id}, test_id={self._current_test_id}",
        )
        self._load_questions(self._current_test_id)
        # Повернути виділення
        for i in range(self.questions_list.count()):
            item = self.questions_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self._current_question_id:
                self.questions_list.setCurrentItem(item)
                break
        QMessageBox.information(self, "Збережено", "Питання збережено.")

    def _delete_question(self) -> None:
        if self._current_question_id is None or self._current_test_id is None:
            return
        reply = QMessageBox.question(
            self,
            "Підтвердження",
            "Видалити це питання?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        qid = self._current_question_id
        self.db.execute("DELETE FROM questions WHERE id = ?", (qid,))
        self.db.log_audit("question_deleted", "admin", f"id={qid}")
        self._current_question_id = None
        self._load_questions(self._current_test_id)
        self._clear_question_editor()

    def _move_question(self, direction: int) -> None:
        """direction: -1 вгору, +1 вниз."""
        if self._current_test_id is None or self._current_question_id is None:
            return
        rows = self.db.fetchall(
            "SELECT id, order_index FROM questions WHERE test_id = ? ORDER BY order_index, id",
            (self._current_test_id,),
        )
        ids = [r["id"] for r in rows]
        try:
            idx = ids.index(self._current_question_id)
        except ValueError:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(ids):
            return
        # Міняємо order_index місцями
        other_id = ids[new_idx]
        order_a = rows[idx]["order_index"]
        order_b = rows[new_idx]["order_index"]
        # Якщо однакові — робимо унікальними
        if order_a == order_b:
            order_b = order_a + direction

        self.db.update("questions", {"order_index": order_b}, "id = ?", (self._current_question_id,))
        self.db.update("questions", {"order_index": order_a}, "id = ?", (other_id,))

        # Нормалізація order_index (0,1,2,...)
        rows2 = self.db.fetchall(
            "SELECT id FROM questions WHERE test_id = ? ORDER BY order_index, id",
            (self._current_test_id,),
        )
        for i, r in enumerate(rows2):
            self.db.update("questions", {"order_index": i}, "id = ?", (r["id"],))

        self._load_questions(self._current_test_id)
        for i in range(self.questions_list.count()):
            item = self.questions_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self._current_question_id:
                self.questions_list.setCurrentItem(item)
                break

    # ------------------------------------------------------------------ Імпорт Excel
    def _download_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Зберегти шаблон",
            "шаблон_тест.xlsx",
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            generate_template(path)
            QMessageBox.information(
                self,
                "Шаблон",
                f"Шаблон збережено:\n{path}\n\n"
                "Відкрийте файл, заповніть аркуш «Питання» і імпортуйте його.",
            )
        except Exception as exc:
            logger.exception("Помилка створення шаблону")
            QMessageBox.critical(self, "Помилка", f"Не вдалося створити шаблон:\n{exc}")

    def _import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Виберіть файл Excel",
            "",
            "Excel (*.xlsx)",
        )
        if not path:
            return

        try:
            result = parse_excel(path)
        except Exception as exc:
            logger.exception("Помилка читання Excel")
            QMessageBox.critical(self, "Помилка", f"Не вдалося прочитати файл:\n{exc}")
            return

        if result.errors:
            self._show_import_errors(result.errors)
            return

        if not result.questions:
            QMessageBox.warning(self, "Імпорт", "У файлі не знайдено питань.")
            return

        # Підсумок + підтвердження + вибір цілі
        summary = (
            f"Знайдено {len(result.questions)} питань, "
            f"сума балів {result.total_points:g}.\n\n"
            "Куди імпортувати?"
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("Підтвердити імпорт")
        msg.setText(summary)
        btn_new = msg.addButton("Створити новий тест", QMessageBox.ButtonRole.AcceptRole)
        btn_add = msg.addButton("Додати до вибраного", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Скасувати", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_new:
            title, ok = QInputDialog.getText(
                self, "Новий тест", "Назва нового тесту:", text=Path(path).stem
            )
            if not ok or not title.strip():
                return
            test_id = self.db.insert(
                "tests",
                {
                    "title": title.strip(),
                    "time_limit_minutes": 60,
                    "violation_threshold": 5,
                    "shuffle_questions": 0,
                    "shuffle_options": 0,
                    "pass_percent": None,
                    "created_at": _utc_now(),
                },
            )
            self._insert_questions(test_id, result.questions)
            self.db.log_audit(
                "test_imported",
                "admin",
                f"new test_id={test_id}, questions={len(result.questions)}, file={path}",
            )
            self._load_tests()
            for i in range(self.tests_list.count()):
                item = self.tests_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == test_id:
                    self.tests_list.setCurrentItem(item)
                    break
            QMessageBox.information(
                self, "Імпорт", f"Створено тест «{title.strip()}» з {len(result.questions)} питаннями."
            )
        elif clicked == btn_add:
            if self._current_test_id is None:
                QMessageBox.warning(
                    self, "Імпорт", "Спочатку виберіть тест у списку зліва."
                )
                return
            self._insert_questions(self._current_test_id, result.questions)
            self.db.log_audit(
                "questions_imported",
                "admin",
                f"test_id={self._current_test_id}, questions={len(result.questions)}, file={path}",
            )
            self._load_questions(self._current_test_id)
            QMessageBox.information(
                self,
                "Імпорт",
                f"Додано {len(result.questions)} питань до поточного тесту.",
            )

    def _show_import_errors(self, errors: list) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Помилки імпорту")
        dlg.setMinimumSize(500, 300)
        layout = QVBoxLayout(dlg)

        layout.addWidget(
            QLabel("Імпорт не виконано. Виправте помилки у файлі та спробуйте знову:")
        )

        table = QTableWidget(len(errors), 2)
        table.setHorizontalHeaderLabels(["Рядок", "Що не так"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        for i, err in enumerate(errors):
            row_label = str(err.row) if err.row else "—"
            table.setItem(i, 0, QTableWidgetItem(row_label))
            table.setItem(i, 1, QTableWidgetItem(err.message))

        table.resizeColumnToContents(0)
        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.exec()

    def _insert_questions(self, test_id: int, questions) -> None:
        """Вставляє розпарсені питання в БД для вказаного тесту."""
        max_order_row = self.db.fetchone(
            "SELECT COALESCE(MAX(order_index), -1) AS m FROM questions WHERE test_id = ?",
            (test_id,),
        )
        next_order = (max_order_row["m"] if max_order_row else -1) + 1

        payload = questions_to_db_payload(questions)
        for item in payload:
            qid = self.db.insert(
                "questions",
                {
                    "test_id": test_id,
                    "text": item["text"],
                    "qtype": item["qtype"],
                    "points": item["points"],
                    "order_index": next_order,
                    "open_answers": item["open_answers"],
                },
            )
            next_order += 1
            for opt in item["options"]:
                self.db.insert(
                    "options",
                    {
                        "question_id": qid,
                        "text": opt["text"],
                        "is_correct": 1 if opt["is_correct"] else 0,
                        "order_index": opt["order_index"],
                    },
                )
