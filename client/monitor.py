"""
Моніторинг процесів з чорного списку та періодичні скріншоти.
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)


class ProcessMonitor(QObject):
    """
    Кожні interval_sec перевіряє чорний список процесів.
    При виявленні викликає on_violation(process_name).
    """

    def __init__(
        self,
        blacklist: list[str],
        on_violation: Callable[[str], None],
        interval_sec: int = 5,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.blacklist = [b.lower() for b in blacklist if b]
        self.on_violation = on_violation
        self._seen: set[str] = set()  # щоб не спамити одним і тим же процесом
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        self._interval_ms = max(2000, interval_sec * 1000)

    def start(self) -> None:
        if not self.blacklist:
            logger.info("Чорний список процесів порожній — моніторинг вимкнено")
            return
        self._timer.start(self._interval_ms)
        self._check()

    def stop(self) -> None:
        self._timer.stop()

    def _check(self) -> None:
        try:
            import psutil
        except ImportError:
            logger.warning("psutil не встановлено — моніторинг процесів недоступний")
            self._timer.stop()
            return

        try:
            names = set()
            for proc in psutil.process_iter(["name"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if name:
                        names.add(name)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            for bl in self.blacklist:
                bl_lower = bl.lower()
                # Порівняння з і без .exe
                matches = [
                    n for n in names
                    if n == bl_lower or n == bl_lower + ".exe" or bl_lower in n
                ]
                for m in matches:
                    key = m
                    if key not in self._seen:
                        self._seen.add(key)
                        logger.warning("Виявлено процес з чорного списку: %s", m)
                        self.on_violation(m)
        except Exception:
            logger.exception("Помилка перевірки процесів")


class PeriodicScreenshot(QObject):
    """Періодичний скріншот кожні interval_sec."""

    def __init__(
        self,
        interval_sec: int,
        on_capture: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_capture = on_capture
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._interval_ms = max(10000, interval_sec * 1000)

    def start(self) -> None:
        self._timer.start(self._interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        try:
            self.on_capture()
        except Exception:
            logger.exception("Помилка періодичного скріншота")
