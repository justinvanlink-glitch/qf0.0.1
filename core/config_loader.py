"""
Завантаження та валідація конфігурації SecureTest.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Шлях до config.json відносно кореня проєкту (або поруч із .exe після збірки)
DEFAULT_CONFIG_NAME = "config.json"


class ConfigError(Exception):
    """Помилка завантаження або валідації конфігурації."""


def _find_config_path() -> Path:
    """Знаходить config.json: поруч із виконуваним файлом або в корені проєкту."""
    import sys

    # Після PyInstaller
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        # Під час розробки: core/ -> securetest/
        base = Path(__file__).resolve().parent.parent

    candidate = base / DEFAULT_CONFIG_NAME
    if candidate.is_file():
        return candidate

    # Спроба в поточній робочій директорії
    cwd_candidate = Path.cwd() / DEFAULT_CONFIG_NAME
    if cwd_candidate.is_file():
        return cwd_candidate

    raise ConfigError(
        f"Файл конфігурації '{DEFAULT_CONFIG_NAME}' не знайдено. "
        f"Очікуваний шлях: {candidate}"
    )


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """
    Завантажує config.json і повертає словник.

    Args:
        config_path: явний шлях до файлу (опційно).

    Returns:
        Словник конфігурації.

    Raises:
        ConfigError: якщо файл відсутній або містить невалідний JSON.
    """
    path = Path(config_path) if config_path else _find_config_path()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        raise ConfigError(f"Файл конфігурації не знайдено: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Невалідний JSON у {path}: {exc}") from exc

    _validate_config(data)
    logger.info("Конфігурацію завантажено з %s", path)
    return data


def _validate_config(data: dict[str, Any]) -> None:
    """Базова перевірка обов'язкових ключів."""
    required = [
        "db_path",
        "organization",
        "smtp",
        "otp_ttl_minutes",
        "otp_max_failed",
        "otp_resend_cooldown_sec",
        "otp_max_requests_per_hour",
        "partial_credit",
        "show_score_to_student",
        "screenshot_interval_sec",
        "screenshot_quality",
        "process_blacklist",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        raise ConfigError(f"У конфігурації відсутні ключі: {', '.join(missing)}")

    org = data.get("organization", {})
    if not isinstance(org, dict) or "name" not in org or "accent_color" not in org:
        raise ConfigError("organization має містити name та accent_color")

    smtp = data.get("smtp", {})
    for key in ("host", "port", "security", "from_address", "from_name"):
        if key not in smtp:
            raise ConfigError(f"smtp.{key} обов'язковий")


def get_db_path(config: dict[str, Any] | None = None) -> Path:
    """Повертає абсолютний шлях до файлу БД."""
    if config is None:
        config = load_config()
    db_path = Path(config["db_path"])
    if not db_path.is_absolute():
        # Відносно директорії config.json
        config_dir = _find_config_path().parent
        db_path = config_dir / db_path
    return db_path.resolve()


def save_config(data: dict[str, Any], config_path: str | Path | None = None) -> None:
    """Зберігає конфігурацію назад у файл (наприклад, після встановлення пароля адміна)."""
    path = Path(config_path) if config_path else _find_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Конфігурацію збережено в %s", path)
