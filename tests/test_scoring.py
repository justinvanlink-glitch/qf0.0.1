"""Тести підрахунку балів."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.scoring import score_answer, _normalize_open


def test_single_correct():
    opts = [
        {"id": 1, "is_correct": True},
        {"id": 2, "is_correct": False},
    ]
    awarded, ok = score_answer("single", 2.0, json.dumps([1]), opts, "", False)
    assert awarded == 2.0 and ok is True


def test_single_wrong():
    opts = [
        {"id": 1, "is_correct": True},
        {"id": 2, "is_correct": False},
    ]
    awarded, ok = score_answer("single", 2.0, json.dumps([2]), opts, "", False)
    assert awarded == 0.0 and ok is False


def test_multiple_full():
    opts = [
        {"id": 1, "is_correct": True},
        {"id": 2, "is_correct": True},
        {"id": 3, "is_correct": False},
    ]
    awarded, ok = score_answer("multiple", 4.0, json.dumps([1, 2]), opts, "", False)
    assert awarded == 4.0 and ok is True


def test_multiple_partial_off():
    opts = [
        {"id": 1, "is_correct": True},
        {"id": 2, "is_correct": True},
        {"id": 3, "is_correct": False},
    ]
    awarded, ok = score_answer("multiple", 4.0, json.dumps([1]), opts, "", False)
    assert awarded == 0.0 and ok is False


def test_multiple_partial_on():
    opts = [
        {"id": 1, "is_correct": True},
        {"id": 2, "is_correct": True},
        {"id": 3, "is_correct": False},
    ]
    # 1 of 2 correct → half
    awarded, ok = score_answer("multiple", 4.0, json.dumps([1]), opts, "", True)
    assert awarded == 2.0 and ok is False


def test_multiple_partial_with_extra():
    opts = [
        {"id": 1, "is_correct": True},
        {"id": 2, "is_correct": True},
        {"id": 3, "is_correct": False},
    ]
    # both correct + one wrong still counts correct ones (no penalty)
    awarded, _ = score_answer("multiple", 4.0, json.dumps([1, 2, 3]), opts, "", True)
    assert awarded == 4.0


def test_open_correct():
    awarded, ok = score_answer("open", 1.5, "  Київ  ", [], "Київ; Kyiv", False)
    assert awarded == 1.5 and ok is True


def test_open_case_insensitive():
    awarded, ok = score_answer("open", 1.0, "KYIV", [], "Київ; Kyiv", False)
    assert awarded == 1.0 and ok is True


def test_open_wrong():
    awarded, ok = score_answer("open", 1.0, "Одеса", [], "Київ; Kyiv", False)
    assert awarded == 0.0 and ok is False


def test_fractional_points():
    opts = [{"id": 1, "is_correct": True}, {"id": 2, "is_correct": False}]
    awarded, ok = score_answer("single", 0.25, json.dumps([1]), opts, "", False)
    assert awarded == 0.25 and ok is True


def test_normalize_open():
    assert _normalize_open("  Hello   World  ") == "hello world"
