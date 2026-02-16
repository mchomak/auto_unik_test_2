"""Загрузка и валидация конфигурации из .env файла."""

import logging
import os
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _get_env(key: str, default: str | None = None, required: bool = False) -> str:
    """Получить значение переменной окружения.

    Args:
        key: Имя переменной окружения.
        default: Значение по умолчанию.
        required: Если True и переменная не задана — завершить программу.

    Returns:
        Значение переменной окружения.
    """
    value = os.getenv(key, default)
    if required and not value:
        print(f"FATAL: обязательная переменная окружения {key} не задана. "
              f"Скопируйте .env.example в .env и заполните значения.")
        sys.exit(1)
    return value  # type: ignore[return-value]


def _get_bool(key: str, default: str = "false") -> bool:
    """Получить булево значение из переменной окружения."""
    return _get_env(key, default).lower() in ("true", "1", "yes")


def _get_int(key: str, default: str = "0") -> int:
    """Получить целочисленное значение из переменной окружения."""
    try:
        return int(_get_env(key, default))
    except ValueError:
        print(f"FATAL: переменная {key} должна быть целым числом.")
        sys.exit(1)


# ── Учётные данные ────────────────────────────────────────────────────
LOGIN: str = _get_env("LOGIN", required=True)
PASSWORD: str = _get_env("PASSWORD", required=True)

# ── Пути ──────────────────────────────────────────────────────────────
EXTENSION_PATH: str = _get_env("EXTENSION_PATH", required=True)
CHROME_PROFILE_PATH: str = _get_env("CHROME_PROFILE_PATH", "./chrome_profile")
COOKIES_FILE: str = _get_env("COOKIES_FILE", "./cookies.pkl")

# ── Список тестов ─────────────────────────────────────────────────────
_raw_urls: str = _get_env("TEST_URLS", "")
TEST_URLS: List[str] = [u.strip() for u in _raw_urls.split(",") if u.strip()]

# ── Режим работы ──────────────────────────────────────────────────────
TEST_MODE: bool = _get_bool("TEST_MODE", "false")
HEADLESS: bool = _get_bool("HEADLESS", "false")
WAIT_TIMEOUT: int = _get_int("WAIT_TIMEOUT", "10")
QUESTION_DELAY: int = _get_int("QUESTION_DELAY", "2")

# ── Логирование ───────────────────────────────────────────────────────
LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO").upper()

# Валидация уровня логирования
_valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
if LOG_LEVEL not in _valid_levels:
    print(f"WARNING: неизвестный уровень логирования '{LOG_LEVEL}', "
          f"используется INFO. Допустимые: {_valid_levels}")
    LOG_LEVEL = "INFO"

# ── Настройка логгера ─────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def setup_logging() -> logging.Logger:
    """Настроить корневой логгер: вывод в консоль и файл.

    Returns:
        Настроенный корневой логгер.
    """
    from datetime import datetime

    logger = logging.getLogger("test_automation")
    logger.setLevel(getattr(logging, LOG_LEVEL))

    formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")

    # Консольный хендлер
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Файловый хендлер
    log_filename = LOG_DIR / f"test_automation_{datetime.now():%Y-%m-%d}.log"
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
