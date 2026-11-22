"""
Підрахунок балів за спробу тесту.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.db import Database

logger = logging.getLogger(__name__)


def _normalize_open(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def score_answer(
    qtype: str,
    points: float,
    selected: str,
    options: list[dict[str, Any]],
    open_answers: str,
    partial_credit: bool,
) -> tuple[float, bool | None]:
    """
    Рахує бали за одну відповідь.

    Returns:
        (points_awarded, is_correct)
        is_correct: True / False / None (якщо неможливо визначити)
    """
    points = float(points or 0)

    if qtype == "open":
        answer = _normalize_open(selected)
        if not answer:
            return 0.0, False
        allowed = [
            _normalize_open(a)
            for a in (open_answers or "").split(";")
            if a.strip()
        ]
        if answer in allowed:
            return points, True
        return 0.0, False

    # single / multiple — selected = JSON list of option ids
    try:
        selected_ids = set(json.loads(selected or "[]"))
    except (json.JSONDecodeError, TypeError):
        selected_ids = set()

    correct_ids = {opt["id"] for opt in options if opt.get("is_correct")}
    if not correct_ids:
        return 0.0, None

    if qtype == "single":
        if len(selected_ids) == 1 and selected_ids == correct_ids:
            return points, True
        return 0.0, False

    # multiple
    if not partial_credit:
        if selected_ids == correct_ids:
            return points, True
        return 0.0, False

    # partial: (correctly selected / total correct) * points, no penalty
    correctly_selected = selected_ids & correct_ids
    ratio = len(correctly_selected) / len(correct_ids)
    awarded = round(points * ratio, 4)
    is_correct = selected_ids == correct_ids
    return awarded, is_correct


def score_attempt(
    db: Database,
    attempt_id: int,
    partial_credit: bool = False,
) -> dict[str, Any]:
    """
    Підраховує бали за всю спробу, оновлює answers і attempts.
    Повертає {score, max_score, percent, passed}.
    """
    attempt = db.fetchone("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
    if not attempt:
        raise ValueError(f"Attempt {attempt_id} not found")

    test = db.fetchone("SELECT * FROM tests WHERE id = ?", (attempt["test_id"],))
    questions = db.fetchall(
        "SELECT * FROM questions WHERE test_id = ? ORDER BY order_index, id",
        (attempt["test_id"],),
    )

    total_score = 0.0
    max_score = 0.0

    for q in questions:
        max_score += float(q["points"] or 0)
        opts = [
            dict(o)
            for o in db.fetchall(
                "SELECT id, text, is_correct FROM options WHERE question_id = ?",
                (q["id"],),
            )
        ]
        ans = db.fetchone(
            "SELECT * FROM answers WHERE attempt_id = ? AND question_id = ?",
            (attempt_id, q["id"]),
        )
        selected = ans["selected"] if ans else ""

        awarded, is_correct = score_answer(
            qtype=q["qtype"],
            points=float(q["points"] or 0),
            selected=selected,
            options=opts,
            open_answers=q["open_answers"] or "",
            partial_credit=partial_credit,
        )
        total_score += awarded

        if ans:
            db.update(
                "answers",
                {
                    "is_correct": (1 if is_correct else 0) if is_correct is not None else None,
                    "points_awarded": awarded,
                },
                "id = ?",
                (ans["id"],),
            )
        else:
            db.insert(
                "answers",
                {
                    "attempt_id": attempt_id,
                    "question_id": q["id"],
                    "selected": "",
                    "is_correct": 0,
                    "points_awarded": 0.0,
                },
            )

    percent = round((total_score / max_score * 100) if max_score > 0 else 0.0, 2)
    passed = None
    if test and test["pass_percent"] is not None:
        passed = percent >= float(test["pass_percent"])

    db.update(
        "attempts",
        {
            "score": total_score,
            "max_score": max_score,
            "percent": percent,
            "passed": (1 if passed else 0) if passed is not None else None,
        },
        "id = ?",
        (attempt_id,),
    )

    logger.info(
        "Attempt %s scored: %.2f / %.2f (%.1f%%) passed=%s",
        attempt_id,
        total_score,
        max_score,
        percent,
        passed,
    )
    return {
        "score": total_score,
        "max_score": max_score,
        "percent": percent,
        "passed": passed,
    }
