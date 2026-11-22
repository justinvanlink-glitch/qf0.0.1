"""
Модульні тести для core/excel_import.py
Запуск: pytest tests/test_excel_import.py -v
або:    python -m pytest tests/test_excel_import.py -v
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from openpyxl import Workbook

# Додаємо корінь проєкту
import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.excel_import import (
    generate_template,
    parse_excel,
    questions_to_db_payload,
    ParseResult,
    ParsedQuestion,
)


def _write_sheet(rows: list[list], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)
    wb.close()


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


@pytest.fixture
def tmp_xlsx(tmp_path: Path):
    return tmp_path / "test.xlsx"


def test_generate_template(tmp_path: Path):
    path = tmp_path / "template.xlsx"
    result = generate_template(path)
    assert result == path
    assert path.is_file()
    # Файл відкривається і має два аркуші
    from openpyxl import load_workbook
    wb = load_workbook(path)
    assert "Питання" in wb.sheetnames
    assert "Інструкція" in wb.sheetnames
    ws = wb["Питання"]
    assert ws.cell(1, 1).value == "Питання"
    assert ws.cell(2, 2).value == "single"  # приклад
    wb.close()


def test_parse_valid_file(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Столиця?", "single", "Київ", "Львів", "", "", "", "", "1", 1],
        ["Мови?", "multiple", "Python", "HTML", "Java", "", "", "", "1,3", 2.5],
        ["Планета?", "open", "", "", "", "", "", "", "Юпітер; Jupiter", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert result.ok
    assert len(result.questions) == 3
    assert result.total_points == 4.5

    q0 = result.questions[0]
    assert q0.qtype == "single"
    assert q0.options == ["Київ", "Львів"]
    assert q0.correct_indices == [0]

    q1 = result.questions[1]
    assert q1.qtype == "multiple"
    assert q1.correct_indices == [0, 2]
    assert q1.points == 2.5

    q2 = result.questions[2]
    assert q2.qtype == "open"
    assert "Юпітер" in q2.open_answers


def test_empty_question(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["", "single", "A", "B", "", "", "", "", "1", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok
    assert any("Порожній текст" in e.message for e in result.errors)


def test_unknown_type(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Питання", "checkbox", "A", "B", "", "", "", "", "1", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok
    assert any("Невідомий тип" in e.message for e in result.errors)


def test_too_few_options(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Питання", "single", "Тільки один", "", "", "", "", "", "1", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok
    assert any("щонайменше 2 варіанти" in e.message for e in result.errors)


def test_correct_out_of_range(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Питання", "single", "A", "B", "", "", "", "", "5", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok
    assert any("поза межами" in e.message for e in result.errors)


def test_missing_correct(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Питання", "single", "A", "B", "", "", "", "", "", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok
    assert any("Не вказано правильні" in e.message for e in result.errors)


def test_non_numeric_points(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Питання", "single", "A", "B", "", "", "", "", "1", "багато"],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok
    assert any("Нечислові бали" in e.message for e in result.errors)


def test_single_with_multiple_corrects(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Питання", "single", "A", "B", "C", "", "", "", "1,2", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok
    assert any("лише один правильний" in e.message for e in result.errors)


def test_open_missing_answers(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Питання", "open", "", "", "", "", "", "", "", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok
    assert any("допустимі відповіді" in e.message for e in result.errors)


def test_empty_file(tmp_xlsx: Path):
    _write_sheet([], tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert not result.ok


def test_points_with_comma(tmp_xlsx: Path):
    """Підтримка коми як десяткового роздільника."""
    rows = [
        HEADERS,
        ["Питання", "single", "A", "B", "", "", "", "", "1", "1,5"],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert result.ok
    assert result.questions[0].points == 1.5


def test_questions_to_db_payload():
    questions = [
        ParsedQuestion(
            text="Q1",
            qtype="single",
            points=1.0,
            options=["A", "B"],
            correct_indices=[0],
        ),
        ParsedQuestion(
            text="Q2",
            qtype="open",
            points=2.0,
            open_answers="yes; так",
        ),
    ]
    payload = questions_to_db_payload(questions)
    assert len(payload) == 2
    assert payload[0]["options"][0]["is_correct"] is True
    assert payload[0]["options"][1]["is_correct"] is False
    assert payload[1]["open_answers"] == "yes; так"
    assert payload[1]["options"] == []


def test_skip_blank_rows(tmp_xlsx: Path):
    rows = [
        HEADERS,
        ["Питання 1", "single", "A", "B", "", "", "", "", "1", 1],
        [None, None, None, None, None, None, None, None, None, None],
        ["Питання 2", "single", "X", "Y", "", "", "", "", "2", 1],
    ]
    _write_sheet(rows, tmp_xlsx)
    result = parse_excel(tmp_xlsx)
    assert result.ok
    assert len(result.questions) == 2
