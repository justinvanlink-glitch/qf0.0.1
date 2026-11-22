"""
Захоплення скріншотів (mss + Pillow).
Збереження JPEG у папку screenshots/ поруч із БД.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _screenshots_dir(db_path: Path) -> Path:
    d = db_path.parent / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def capture_screenshot(
    db,
    attempt_id: int,
    quality: int = 70,
    violation_id: int | None = None,
    is_periodic: bool = False,
) -> int | None:
    """
    Робить скріншот усіх моніторів, зберігає JPEG, записує в БД.
    Повертає id запису screenshots або None при помилці.
    """
    try:
        import mss
        from PIL import Image
    except ImportError as exc:
        logger.error("mss/Pillow не встановлено: %s", exc)
        return None

    try:
        with mss.mss() as sct:
            # Усі монітори (monitor 0 = virtual desktop)
            monitor = sct.monitors[0]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"a{attempt_id}_{ts}.jpg"
        out_dir = _screenshots_dir(db.db_path)
        file_path = out_dir / filename

        quality = max(10, min(95, int(quality)))
        img.save(str(file_path), "JPEG", quality=quality, optimize=True)

        sid = db.insert(
            "screenshots",
            {
                "attempt_id": attempt_id,
                "violation_id": violation_id,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "file_path": str(file_path),
                "is_periodic": 1 if is_periodic else 0,
            },
        )
        logger.info("Скріншот збережено: %s (id=%s)", file_path.name, sid)
        return sid
    except Exception:
        logger.exception("Помилка захоплення скріншота attempt=%s", attempt_id)
        return None
