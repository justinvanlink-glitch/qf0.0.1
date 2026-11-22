"""
Імпорт тестів з Excel та генерація шаблону.
Формат аркуша (перший рядок — заголовки):
  A: Питання
  B: Тип (single / multiple / open)
  C–H: Варіант 1 … Варіант 6
  I: Правильні (номери варіантів через кому, напр. "1,3";
     для open — допустимі відповіді через ";")
  J: Бали
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.comments import Comment

logger = logging.getLogger(__name__)

HEADERS = [
    "Питання",
    "Тип",
    "Варіант 1",
    "Варіант 2",
    "Варіант 3",
    "Варіант 4",
    "Варіант 5",
    "Варіант 6",
    "Правильні",
    "Бали",
]

VALID_TYPES = {"single", "multiple", "open"}


@dataclass
class ImportErrorItem:
    row: int
    message: str


@dataclass
class ParsedQuestion:
    text: str
    qtype: str
    points: float
    options: list[str] = field(default_factory=list)  # для single/multiple
    correct_indices: list[int] = field(default_factory=list)  # 0-based
    open_answers: str = ""  # для open


@dataclass
class ParseResult:
    questions: list[ParsedQuestion] = field(default_factory=list)
    errors: list[ImportErrorItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0 and len(self.questions) > 0

    @property
    def total_points(self) -> float:
        return sum(q.points for q in self.questions)


def generate_template(path: str | Path) -> Path:
    """
    Створює файл-шаблон .xlsx з прикладами та підказками.
    Повертає шлях до створеного файлу.
    """
    path = Path(path)
    wb = Workbook()

    # ---- Аркуш з даними ----
    ws = wb.active
    ws.title = "Питання"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2563EB")
    thin = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )
    example_fill = PatternFill("solid", fgColor="F1F5F9")

    for col, header in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = thin

    # Приклади
    examples = [
        [
            "Столиця України?",
            "single",
            "Київ",
            "Львів",
            "Одеса",
            "Харків",
            "",
            "",
            "1",
            1,
        ],
        [
            "Які з наведених мов є мовами програмування?",
            "multiple",
            "Python",
            "HTML",
            "Java",
            "CSS",
            "C++",
            "",
            "1,3,5",
            2,
        ],
        [
            "Назвіть найбільшу планету Сонячної системи",
            "open",
            "",
            "",
            "",
            "",
            "",
            "",
            "Юпітер; Jupiter; юпітер",
            1.5,
        ],
    ]

    for r_idx, row_data in enumerate(examples, start=2):
        for c_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=value)
            cell.border = thin
            cell.fill = example_fill
            if c_idx == 1:
                cell.alignment = Alignment(wrap_text=True)

    # Ширина колонок
    widths = [40, 12, 18, 18, 18, 18, 18, 18, 28, 10]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.row_dimensions[1].height = 22

    # Коментарі-підказки
    ws["A1"].comment = Comment("Текст питання (обов’язково)", "SecureTest")
    ws["B1"].comment = Comment(
        "Тип: single (одна правильна), multiple (кілька), open (відкрита відповідь)",
        "SecureTest",
    )
    ws["I1"].comment = Comment(
        "Для single/multiple — номери варіантів через кому (1,3).\n"
        "Для open — допустимі відповіді через крапку з комою (;)",
        "SecureTest",
    )
    ws["J1"].comment = Comment("Бали за правильну відповідь (число, можна дробове)", "SecureTest")

    # ---- Аркуш з інструкцією ----
    info = wb.create_sheet("Інструкція")
    info["A1"] = "Інструкція з імпорту питань"
    info["A1"].font = Font(bold=True, size=14)

    instructions = [
        "",
        "══════════════════════════════════════════════════════════════",
        "ТИПИ ПИТАНЬ — ПРАВИЛА",
        "══════════════════════════════════════════════════════════════",
        "",
        "1) single — ОДНА ПРАВИЛЬНА ВІДПОВІДЬ",
        "   • Заповніть мінімум 2 варіанти (колонки «Варіант 1»…«Варіант 6»).",
        "   • У колонці «Правильні» вкажіть ОДИН номер, наприклад: 1",
        "   • Бал нараховується лише якщо студент обрав саме цей варіант.",
        "   • Приклад: Столиця України?  →  Київ / Львів / Одеса  →  Правильні: 1",
        "",
        "2) multiple — КІЛЬКА ПРАВИЛЬНИХ ВІДПОВІДЕЙ",
        "   • Заповніть мінімум 2 варіанти.",
        "   • У колонці «Правильні» вкажіть номери через кому, наприклад: 1,3,5",
        "   • partial_credit = false (за замовчуванням): бал лише за ПОВНІСТЮ",
        "     правильний набір (усі потрібні вибрані і жоден зайвий).",
        "   • partial_credit = true (у config.json): кожна правильна відповідь",
        "     оцінюється пропорційно — (вірно вибрані / усі правильні) × бали.",
        "     Без штрафів за зайві вибори.",
        "   • Бали можна дробові: 0.25, 0.5, 1.5 (у Excel також 0,25 або 0,5).",
        "   • Приклад: Які мови програмування?  →  Python, HTML, Java  →  Правильні: 1,3",
        "",
        "3) open — ВІДКРИТА ВІДПОВІДЬ (вільний текст)",
        "   • Варіанти (колонки C–H) залишайте порожніми.",
        "   • У колонці «Правильні» перелічіть допустимі відповіді через «;»",
        "     (крапка з комою), наприклад: Київ; Kyiv; Київ місто",
        "   • Порівняння БЕЗ урахування регістру і зайвих пробілів.",
        "   • Бал нараховується, якщо відповідь студента збігається з будь-якою",
        "     з допустимих (після нормалізації).",
        "   • Приклад: Найбільша планета?  →  Правильні: Юпітер; Jupiter; юпітер",
        "",
        "══════════════════════════════════════════════════════════════",
        "ЗАГАЛЬНІ ПРАВИЛА ЗАПОВНЕННЯ",
        "══════════════════════════════════════════════════════════════",
        "",
        "• Перший рядок аркуша «Питання» — заголовки. Не змінюйте їх.",
        "• Колонка «Тип»: лише single, multiple або open (регістр не важливий).",
        "• Колонка «Бали»: додатне число, можна дробове (0.25, 0.5, 1.5 або 0,25).",
        "• Порожні рядки в кінці файлу ігноруються.",
        "• Після вибору файлу програма покаже таблицю помилок (якщо є)",
        "  або підсумок («Знайдено N питань, сума балів X») для підтвердження.",
        "",
        "Приклади всіх трьох типів уже є на аркуші «Питання» —",
        "можете їх змінити, доповнити або видалити.",
    ]
    for i, line in enumerate(instructions, start=2):
        info[f"A{i}"] = line
        # Виділення заголовків секцій
        if line.startswith("═") or line.startswith("ТИПИ") or line.startswith("ЗАГАЛЬНІ"):
            info[f"A{i}"].font = Font(bold=True)
        if line.startswith(("1)", "2)", "3)")):
            info[f"A{i}"].font = Font(bold=True, color="2563EB")
    info.column_dimensions["A"].width = 95

    wb.save(path)
    logger.info("Шаблон збережено: %s", path)
    return path


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_points(raw: Any, row_num: int, errors: list[ImportErrorItem]) -> float | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        errors.append(ImportErrorItem(row_num, "Не вказано бали"))
        return None
    try:
        # Підтримка коми як десяткового роздільника
        if isinstance(raw, str):
            raw = raw.replace(",", ".").strip()
        val = float(raw)
        if val <= 0:
            errors.append(ImportErrorItem(row_num, "Бали мають бути більше 0"))
            return None
        return val
    except (TypeError, ValueError):
        errors.append(ImportErrorItem(row_num, f"Нечислові бали: «{raw}»"))
        return None


def _parse_correct_indices(
    raw: str, num_options: int, qtype: str, row_num: int, errors: list[ImportErrorItem]
) -> list[int] | None:
    if not raw:
        errors.append(ImportErrorItem(row_num, "Не вказано правильні відповіді"))
        return None

    parts = re.split(r"[,;]\s*", raw)
    indices: list[int] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            num = int(p)
        except ValueError:
            errors.append(
                ImportErrorItem(row_num, f"Некоректний номер варіанту в «Правильні»: «{p}»")
            )
            return None
        if num < 1 or num > num_options:
            errors.append(
                ImportErrorItem(
                    row_num,
                    f"Номер варіанту {num} поза межами (є {num_options} варіантів)",
                )
            )
            return None
        idx = num - 1
        if idx not in indices:
            indices.append(idx)

    if not indices:
        errors.append(ImportErrorItem(row_num, "Не вказано правильні відповіді"))
        return None

    if qtype == "single" and len(indices) > 1:
        errors.append(
            ImportErrorItem(row_num, "Для типу single дозволено лише один правильний варіант")
        )
        return None

    return indices


def parse_excel(path: str | Path) -> ParseResult:
    """
    Читає .xlsx і валідує всі рядки.
    Повертає ParseResult з питаннями (якщо помилок немає) або списком помилок.
    Імпорт у БД НЕ виконується.
    """
    path = Path(path)
    result = ParseResult()

    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        result.errors.append(ImportErrorItem(0, f"Не вдалося відкрити файл: {exc}"))
        return result

    try:
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not rows:
        result.errors.append(ImportErrorItem(0, "Файл порожній"))
        return result

    # Перевірка заголовків (м’яка — лише попередження в лог)
    header_row = [_cell_str(c).lower() for c in (rows[0] or [])]
    expected = [h.lower() for h in HEADERS]
    if header_row[: len(expected)] != expected:
        logger.warning("Заголовки відрізняються від очікуваних: %s", header_row[:10])

    for row_idx, row in enumerate(rows[1:], start=2):  # 1-based Excel row
        if row is None:
            continue
        # Нормалізуємо до 10 колонок
        cells = list(row) + [None] * 10
        cells = cells[:10]

        text = _cell_str(cells[0])
        qtype_raw = _cell_str(cells[1]).lower()
        option_texts = [_cell_str(cells[i]) for i in range(2, 8)]
        correct_raw = _cell_str(cells[8])
        points_raw = cells[9]

        # Повністю порожній рядок — пропускаємо
        if not text and not qtype_raw and not any(option_texts) and not correct_raw and points_raw is None:
            continue

        row_errors: list[ImportErrorItem] = []

        if not text:
            row_errors.append(ImportErrorItem(row_idx, "Порожній текст питання"))

        if qtype_raw not in VALID_TYPES:
            row_errors.append(
                ImportErrorItem(
                    row_idx,
                    f"Невідомий тип «{qtype_raw or '(порожньо)'}». Допустимо: single, multiple, open",
                )
            )
            # Далі валідація залежить від типу — якщо тип невідомий, інші помилки все одно збираємо
            qtype = qtype_raw or "?"
        else:
            qtype = qtype_raw

        points = _parse_points(points_raw, row_idx, row_errors)

        options = [t for t in option_texts if t]  # лише заповнені

        if qtype in ("single", "multiple"):
            if len(options) < 2:
                row_errors.append(
                    ImportErrorItem(
                        row_idx,
                        f"Для типу {qtype} потрібно щонайменше 2 варіанти (знайдено {len(options)})",
                    )
                )
            correct_indices = _parse_correct_indices(
                correct_raw, len(options), qtype, row_idx, row_errors
            )
            open_answers = ""
        elif qtype == "open":
            if not correct_raw:
                row_errors.append(
                    ImportErrorItem(row_idx, "Для open потрібно вказати допустимі відповіді в колонці «Правильні»")
                )
            correct_indices = []
            open_answers = correct_raw
            # Варіанти для open ігноруємо
            options = []
        else:
            correct_indices = []
            open_answers = ""

        if row_errors:
            result.errors.extend(row_errors)
            continue

        # Сюди потрапляємо лише якщо помилок у рядку немає
        assert points is not None
        assert correct_indices is not None or qtype == "open"

        result.questions.append(
            ParsedQuestion(
                text=text,
                qtype=qtype,
                points=points,
                options=options,
                correct_indices=correct_indices or [],
                open_answers=open_answers,
            )
        )

    if not result.questions and not result.errors:
        result.errors.append(ImportErrorItem(0, "У файлі не знайдено жодного питання"))

    return result


def questions_to_db_payload(questions: list[ParsedQuestion]) -> list[dict[str, Any]]:
    """
    Перетворює ParsedQuestion у структуру, зручну для вставки в БД.
    Повертає список dict:
      {
        "text", "qtype", "points", "open_answers",
        "options": [{"text", "is_correct", "order_index"}, ...]
      }
    """
    payload = []
    for q in questions:
        opts = []
        if q.qtype in ("single", "multiple"):
            for i, text in enumerate(q.options):
                opts.append(
                    {
                        "text": text,
                        "is_correct": i in q.correct_indices,
                        "order_index": i,
                    }
                )
        payload.append(
            {
                "text": q.text,
                "qtype": q.qtype,
                "points": q.points,
                "open_answers": q.open_answers if q.qtype == "open" else "",
                "options": opts,
            }
        )
    return payload
