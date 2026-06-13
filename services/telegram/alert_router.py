"""Two-channel Telegram alert routing — PRIMARY vs VERBOSE.

Per TZ-DASHBOARD-AND-TELEGRAM-USABILITY-PHASE-1 P2 + TELEGRAM_EMITTERS_INVENTORY §5.

Channels:
  PRIMARY  — default, always-on. Receives high-signal emitters:
             #1 LIQ_CASCADE, #2 BOUNDARY_BREACH, #3 PNL_EVENT/PNL_EXTREME,
             #6 POSITION_CHANGE, #7 PARAM_CHANGE, #8 BOT_STATE_CHANGE,
             #9 REGIME_CHANGE, #10 MARGIN_ALERT, #11 ENGINE_ALERT,
             #12 LIQ_CLUSTER_BUILD, #13 SETUP_DETECTOR (SETUP_ON/SETUP_OFF only),
             #16 LEVEL_BREAK (when within proximity of operator-critical levels)
  VERBOSE  — opt-in via /verbose toggle. Receives low-signal emitters:
             #4 RSI_EXTREME / auto_edge_alerts, #5 SETUP_DETECTOR DEEP / cluster

Subscription model:
  - PRIMARY: every allowed chat in ALLOWED_CHAT_IDS receives by default.
  - VERBOSE: per-chat opt-in stored on disk in data/telegram/verbose_subs.json.
    Operator runs `/verbose on` (or `/verbose`) to subscribe; `/verbose off` to
    unsubscribe. Default = OFF.

This module is a *pure routing decision layer*. It does NOT send messages
itself. Callers (worker threads) ask `route_decision(emitter, event_meta)` and
receive `(channels: set[str])` — the caller then sends to whichever subset of
chats matches each channel's subscriber list.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_VERBOSE_SUBS_PATH = _ROOT / "data" / "telegram" / "verbose_subs.json"

PRIMARY = "PRIMARY"
VERBOSE = "VERBOSE"
ROUTINE = "ROUTINE"   # 2026-05-11: low-signal grid/layer events, sent to a separate TG chat

# Emitter → channel mapping. Per TELEGRAM_EMITTERS_INVENTORY §5 + TZ brief.
# Unlisted emitters default to PRIMARY (conservative — operator opts out via
# explicit suppression, not silent default).
_EMITTER_CHANNEL: dict[str, str] = {
    # PRIMARY (high-signal, regulation-relevant)
    "LIQ_CASCADE":        PRIMARY,
    "BOUNDARY_BREACH":    PRIMARY,
    "PNL_EVENT":          PRIMARY,
    "PNL_EXTREME":        PRIMARY,
    "POSITION_CHANGE":    PRIMARY,
    "PARAM_CHANGE":       PRIMARY,
    "BOT_STATE_CHANGE":   PRIMARY,
    "REGIME_CHANGE":      PRIMARY,
    "MARGIN_ALERT":       PRIMARY,
    "ENGINE_ALERT":       PRIMARY,
    "LIQ_CLUSTER_BUILD":  PRIMARY,
    "SETUP_ON":           PRIMARY,    # setup_detector primary edge events
    "SETUP_OFF":          PRIMARY,
    "GRID_EXHAUSTION":    PRIMARY,    # ВЕРХ/НИЗ ИСТОЩАЕТСЯ — operator decision input
    "P15_OPEN":           PRIMARY,    # начало цикла P-15 — оператор должен видеть
    "P15_CLOSE":          PRIMARY,    # завершение цикла P-15
    "ALT_GUARD":          PRIMARY,    # 2026-06-10: сторож живых альт-гридов (net-0/SL/памп)
    "MA_CROSS":           PRIMARY,    # 2026-06-13: H5-кросс сигналы (~5/мес, оператор видит)
    # ROUTINE (low-signal noise, separate chat by default)
    "P15_REENTRY":        ROUTINE,    # повторное открытие слоя после harvest
    "P15_HARVEST":        ROUTINE,    # частичное закрытие 50%
    "LEVEL_BREAK":        ROUTINE,    # пробой уровня без other context
    "LIQ_PRE_CASCADE":    ROUTINE,    # 2026-06-10: liq-cluster early-warning спамил
                                      # основную ленту (Win-фидбек) — в тихий канал
    "PAPER_TRADE":        ROUTINE,    # confirmation paper-trade entry
    "alt_decorr":         ROUTINE,    # 2026-05-29 alt decorr-divergence — shadow until
                                      # live paper proves edge (backtest weak), then promote
    # VERBOSE (low-signal, opt-in via /verbose)
    "RSI_EXTREME":        VERBOSE,
    "AUTO_EDGE_ALERT":    VERBOSE,    # auto_edge_alerts SETUP_ON/SETUP_OFF (#4)
    "SETUP_DETECTOR_DEEP": VERBOSE,   # cluster / deep-context events (#5)
}


def channel_for(emitter: str) -> str:
    """Return the channel (PRIMARY or VERBOSE) for an emitter type.

    Unknown emitters default to PRIMARY (fail-safe — operator should never miss
    a real event because of a routing typo). To put a new emitter on VERBOSE,
    add it to _EMITTER_CHANNEL explicitly.
    """
    return _EMITTER_CHANNEL.get(emitter, PRIMARY)


# ── Verbose subscription registry ──────────────────────────────────────────


@dataclass
class _SubsState:
    verbose_chat_ids: set[int]


class VerboseSubscriptionRegistry:
    """Persistent per-chat VERBOSE-channel subscription registry.

    Disk format (JSON):
        {"verbose_chat_ids": [123, 456]}

    Thread-safe via a coarse mutex; load is lazy and on every change we save.
    """

    def __init__(self, state_path: Path = _VERBOSE_SUBS_PATH) -> None:
        self.state_path = state_path
        self._lock = threading.Lock()
        self._state = _SubsState(verbose_chat_ids=set())
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("verbose_subs.load_failed path=%s", self.state_path)
            return
        ids_raw = raw.get("verbose_chat_ids", []) if isinstance(raw, dict) else []
        clean: set[int] = set()
        for v in ids_raw:
            try:
                clean.add(int(v))
            except (TypeError, ValueError):
                continue
        self._state.verbose_chat_ids = clean

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.state_path.write_text(
                json.dumps({"verbose_chat_ids": sorted(self._state.verbose_chat_ids)},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("verbose_subs.save_failed path=%s", self.state_path)

    def is_subscribed(self, chat_id: int) -> bool:
        with self._lock:
            return int(chat_id) in self._state.verbose_chat_ids

    def subscribe(self, chat_id: int) -> bool:
        """Return True if state changed (was not already subscribed)."""
        with self._lock:
            cid = int(chat_id)
            if cid in self._state.verbose_chat_ids:
                return False
            self._state.verbose_chat_ids.add(cid)
            self._save()
            logger.info("verbose_subs.subscribe chat_id=%s", cid)
            return True

    def unsubscribe(self, chat_id: int) -> bool:
        """Return True if state changed (was subscribed)."""
        with self._lock:
            cid = int(chat_id)
            if cid not in self._state.verbose_chat_ids:
                return False
            self._state.verbose_chat_ids.discard(cid)
            self._save()
            logger.info("verbose_subs.unsubscribe chat_id=%s", cid)
            return True

    def toggle(self, chat_id: int) -> bool:
        """Toggle subscription. Return True if now subscribed."""
        with self._lock:
            cid = int(chat_id)
            if cid in self._state.verbose_chat_ids:
                self._state.verbose_chat_ids.discard(cid)
                now_subscribed = False
            else:
                self._state.verbose_chat_ids.add(cid)
                now_subscribed = True
            self._save()
            logger.info("verbose_subs.toggle chat_id=%s now_subscribed=%s",
                        cid, now_subscribed)
            return now_subscribed

    def subscribed_chat_ids(self) -> set[int]:
        with self._lock:
            return set(self._state.verbose_chat_ids)


# ── Routing helper ──────────────────────────────────────────────────────────


def select_recipients(
    emitter: str,
    *,
    primary_chat_ids: Iterable[int],
    verbose_registry: VerboseSubscriptionRegistry,
) -> list[int]:
    """Return chat IDs that should receive this emitter's alert.

    For PRIMARY emitters: every chat in primary_chat_ids.
    For VERBOSE emitters: only chats that have opted in via /verbose.
    """
    channel = channel_for(emitter)
    primary = list(primary_chat_ids)
    if channel == PRIMARY:
        return primary
    # VERBOSE — intersect primary_chat_ids with verbose subscribers (so a chat
    # that is not in ALLOWED_CHAT_IDS cannot subscribe to verbose by accident).
    verbose_subs = verbose_registry.subscribed_chat_ids()
    return [cid for cid in primary if cid in verbose_subs]


# ── /verbose command handler ──────────────────────────────────────────────


def handle_verbose_command(
    chat_id: int,
    args: str,
    registry: VerboseSubscriptionRegistry,
) -> str:
    """Process `/verbose [on|off|status]` and return user-facing reply text.

    Pure function — caller sends the returned text to the chat.
    """
    arg = (args or "").strip().lower()
    if arg in ("status", "?"):
        if registry.is_subscribed(chat_id):
            return (
                "🔊 VERBOSE подписка: ВКЛЮЧЕНА.\n"
                "Получаешь PRIMARY (всегда) + VERBOSE (RSI, deep-setup).\n"
                "Отключить: /verbose off"
            )
        return (
            "🔇 VERBOSE подписка: ВЫКЛЮЧЕНА (по умолчанию).\n"
            "Получаешь только PRIMARY (LIQ, BOUNDARY, PNL, REGIME и пр.).\n"
            "Включить: /verbose on"
        )
    if arg in ("on", "вкл", "1", ""):
        # empty arg → toggle ON (operator-friendly default)
        if not arg:
            now_on = registry.toggle(chat_id)
        else:
            registry.subscribe(chat_id)
            now_on = True
        if now_on:
            return (
                "🔊 VERBOSE подписка ВКЛЮЧЕНА.\n"
                "Теперь получаешь RSI extremes, deep setup-detector события "
                "и другой низко-сигнальный поток.\n"
                "Отключить: /verbose off"
            )
        return (
            "🔇 VERBOSE подписка ВЫКЛЮЧЕНА.\n"
            "Теперь получаешь только PRIMARY канал."
        )
    if arg in ("off", "выкл", "0"):
        registry.unsubscribe(chat_id)
        return (
            "🔇 VERBOSE подписка ВЫКЛЮЧЕНА.\n"
            "Теперь получаешь только PRIMARY канал."
        )
    return (
        "Использование: /verbose [on|off|status]\n"
        "Без аргумента — переключить подписку."
    )
