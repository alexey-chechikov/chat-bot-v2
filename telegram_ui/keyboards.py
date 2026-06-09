from __future__ import annotations

from typing import Any, Dict

from telebot.types import ReplyKeyboardMarkup, KeyboardButton


def _btn(text: str) -> KeyboardButton:
    return KeyboardButton(text)


def _norm_upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "y", "on", "да"}:
        return True
    if s in {"false", "0", "no", "n", "off", "нет"}:
        return False
    return bool(value)


def build_main_keyboard() -> ReplyKeyboardMarkup:
    """Trader-first layout. Updated 2026-05-11 per operator feedback.

    Row 1 — что сейчас (state, открытые сделки с цифрами, гинари-боты)
    Row 2 — что делать (утро + рынок + грид-решение)
    Row 3 — история и алерты + помощь

    Убраны разработческие команды (/pipeline /precision /histogram /inspect
    /cron) с кнопок — доступны текстом для дебага. P-15 включён в /setups
    как часть «открытые позиции» вместе с paper trades.
    """
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    # Row 1 — состояние
    kb.row(_btn("/status"), _btn("/setups"), _btn("/ginarea"))
    # Row 2 — решения (/card — 4ч-карточка-брифинг по запросу, 2026-06-10)
    kb.row(_btn("/card"), _btn("/morning_brief"), _btn("/advise"), _btn("FINAL DECISION"))
    # Row 3 — история + помощь
    kb.row(_btn("/changelog"), _btn("/watch"), _btn("HELP"))
    return kb


def build_debug_keyboard() -> ReplyKeyboardMarkup:
    return build_main_keyboard()


def build_dynamic_keyboard(state: Dict[str, Any] | None = None) -> ReplyKeyboardMarkup:
    return build_main_keyboard()
