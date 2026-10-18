from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_DIR = 'logs'
APP_LOG_FILE = os.path.join(LOG_DIR, 'app.log')
ERROR_LOG_FILE = os.path.join(LOG_DIR, 'errors.log')


def _console_level(level: int) -> int:
    # Под launchd stderr = logs/launchd_app_runner.err без ротации, и INFO там
    # дублирует app.log (09.10.2026: 634 из 652 МБ). В терминале — как было.
    try:
        is_tty = sys.stderr.isatty()
    except (AttributeError, ValueError):
        is_tty = False
    return level if is_tty else max(level, logging.WARNING)


def setup_logging(level: int = logging.INFO) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    root = logging.getLogger()
    if getattr(setup_logging, '_configured', False):
        return

    root.setLevel(level)
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')

    console = logging.StreamHandler()
    console.setLevel(_console_level(level))
    console.setFormatter(formatter)

    app_file = RotatingFileHandler(APP_LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    app_file.setLevel(level)
    app_file.setFormatter(formatter)

    error_file = RotatingFileHandler(ERROR_LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(formatter)

    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(app_file)
    root.addHandler(error_file)

    setup_logging._configured = True
