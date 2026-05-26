from __future__ import annotations

import logging
import threading
from typing import Optional

import config

logger = logging.getLogger(__name__)


class TelegramAlertClient:
    """Singleton client used by the orchestrator to push Telegram alerts."""

    _instance: Optional["TelegramAlertClient"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._bot = None
        self._chat_ids: list[int] = []
        self._enabled = False
        self._init_client()

    @classmethod
    def instance(cls) -> "TelegramAlertClient":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    def _init_client(self) -> None:
        token = str(getattr(config, "BOT_TOKEN", "") or "").strip()
        chat_raw = str(getattr(config, "CHAT_ID", "") or "").strip()
        enabled = bool(getattr(config, "ENABLE_TELEGRAM", True))

        if not enabled:
            logger.info("[ALERT CLIENT] Telegram disabled via ENABLE_TELEGRAM=false")
            return

        if not token or ":" not in token:
            logger.warning("[ALERT CLIENT] BOT_TOKEN not set, alerts will be logged only")
            return

        chat_ids = self._parse_chat_ids(chat_raw)
        if not chat_ids:
            logger.warning("[ALERT CLIENT] CHAT_ID not set, alerts will be logged only")
            return

        try:
            import telebot

            self._bot = telebot.TeleBot(token, parse_mode=None)
            self._chat_ids = chat_ids
            self._enabled = True
            logger.info("[ALERT CLIENT] Initialized for %d chat(s)", len(chat_ids))
        except Exception as exc:
            logger.error("[ALERT CLIENT] Init failed: %s", exc)

    @staticmethod
    def _parse_chat_ids(raw: str) -> list[int]:
        out: list[int] = []
        seen: set[int] = set()
        for part in str(raw or "").replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                value = int(part)
            except ValueError:
                continue
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def is_enabled(self) -> bool:
        return self._enabled and self._bot is not None

    def send(self, text: str) -> bool:
        if not self.is_enabled():
            return False
        from services.common.tg_send_with_retry import send_with_retry
        result = send_with_retry(self._bot, self._chat_ids, text,
                                  where="alert_client")
        return any(result.values())
