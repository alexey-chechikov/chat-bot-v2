"""Direct Telegram notification for TV webhook signals.

Uses requests (not the python-telegram-bot object) so it works from
any thread without an event loop. Config loaded once at module level.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_bot_token: str = ""
_chat_id: str = ""
_config_loaded = False

_TG_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _load_config() -> None:
    global _bot_token, _chat_id, _config_loaded
    if _config_loaded:
        return
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        # корневой config.py — тот же источник, что у telegram_alert_client
        # (BOT_TOKEN/CHAT_ID — константы модуля; CHAT_ID может быть списком через запятую)
        import config
        _bot_token = str(getattr(config, "BOT_TOKEN", "") or "").strip()
        chat_raw = str(getattr(config, "CHAT_ID", "") or "").strip()
        _chat_id = chat_raw.split(",")[0].strip()
    except Exception:
        logger.exception("tv_notify.config_load_failed")
    _config_loaded = True


def send_tv_signal(text: str, retries: int = 2) -> bool:
    """Send text to operator chat. Returns True on success. Never raises."""
    _load_config()
    if not _bot_token or not _chat_id:
        logger.warning("tv_notify.no_config — skipping TG send")
        return False
    try:
        import requests
    except ImportError:
        logger.error("tv_notify.requests_not_available")
        return False

    url = _TG_SEND_URL.format(token=_bot_token)
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                url,
                json={"chat_id": _chat_id, "text": text},
                timeout=8,
            )
            if resp.ok:
                return True
            logger.warning("tv_notify.send_failed status=%d body=%s", resp.status_code, resp.text[:200])
        except Exception:
            logger.exception("tv_notify.send_exception attempt=%d", attempt)
        if attempt < retries:
            time.sleep(2.0)
    return False
