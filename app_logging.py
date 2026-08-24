"""
app_logging.py — единая настройка логов NutriClick (консоль + файл).

Зачем нужен файл
----------------
Пишет сообщения бота одновременно в консоль и в logs/bot.log с временными
метками и уровнями. Ротация по размеру, чтобы файл не раздувался.
Метки времени — Asia/Yekaterinburg (UTC+5), как у разработчика в ЕКБ.
Вызывается один раз в main() через setup_logging(); модули берут
logger = logging.getLogger(__name__).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

# Каталог и файл логов рядом с проектом.
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "bot.log"

# Ротация: до 5 МБ на файл, хранить 5 архивов (bot.log.1 …).
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# Часовой пояс логов и писем об ошибках (ЕКБ = UTC+5 круглый год).
LOG_TZ = ZoneInfo("Asia/Yekaterinburg")
LOG_TZ_LABEL = "UTC+5"

# Формат: время | уровень | модуль | сообщение
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


# Formatter с фиксированным TZ Asia/Yekaterinburg (не зависит от TZ контейнера/VPS).
# Используется setup_logging для консоли и bot.log.
class _YekaterinburgFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=LOG_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime(self.default_time_format)


# Текущее время в LOG_TZ строкой для писем / репортов.
# Используется error_notify и send_feedback_email.
def format_log_timestamp() -> str:
    return datetime.now(LOG_TZ).strftime(f"%Y-%m-%d %H:%M:%S {LOG_TZ_LABEL}")


# Настраивает root-логгер: консоль + rotating файл logs/bot.log.
# Используется в main() до старта polling; повторный вызов безопасен (no-op).
def setup_logging(*, level: int | None = None) -> Path:
    global _configured
    if _configured:
        return LOG_FILE

    if level is None:
        raw = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
        level = getattr(logging, raw, logging.INFO)

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = _YekaterinburgFormatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Сторонние библиотеки — без болтовни на INFO.
    for noisy in (
        "aiogram",
        "aiohttp",
        "asyncio",
        "urllib3",
        "httpx",
        "httpcore",
        "google_genai",
        "google.genai",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info("Логирование включено -> %s", LOG_FILE)
    return LOG_FILE
