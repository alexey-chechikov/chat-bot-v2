"""Signal detection: LIQ_CASCADE, RSI_EXTREME, LEVEL_BREAK → signals.csv."""
from __future__ import annotations

import csv
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from market_collector.config import (
    LIQ_CASCADE_BTC_THRESHOLD,
    LIQ_CASCADE_WINDOW_SEC,
    LIQUIDATIONS_CSV,
    OHLCV_15M_CSV,
    OHLCV_1H_CSV,
    OHLCV_1M_CSV,
    RSI_15M_OVERBOUGHT,
    RSI_15M_OVERSOLD,
    RSI_1H_OVERBOUGHT,
    RSI_1H_OVERSOLD,
    SIGNAL_DEDUP_SEC,
    SIGNALS_CSV,
)
from market_collector.indicators import compute_rsi_from_csv
from market_collector.levels import get_levels

logger = logging.getLogger(__name__)
SIGNALS_HEADERS = ["ts_utc", "signal_type", "details_json"]
_write_lock = threading.Lock()


def _ts_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_signal(signal_type: str, details: dict) -> None:
    SIGNALS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        is_new = not SIGNALS_CSV.exists()
        with SIGNALS_CSV.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(SIGNALS_HEADERS)
            writer.writerow([_ts_utc_now(), signal_type, json.dumps(details, ensure_ascii=False)])
            fh.flush()


def _sum_liq_qty_recent(window_sec: int) -> float:
    if not LIQUIDATIONS_CSV.exists():
        return 0.0
    cutoff = time.time() - window_sec
    total = 0.0
    with LIQUIDATIONS_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                ts = datetime.fromisoformat(row.get("ts_utc", "")).timestamp()
                if ts >= cutoff:
                    total += float(row.get("qty", 0) or 0)
            except Exception:
                continue
    return total


def _get_current_price() -> float | None:
    if not OHLCV_1M_CSV.exists():
        return None
    last: float | None = None
    with OHLCV_1M_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                last = float(row["close"])
            except (KeyError, ValueError):
                pass
    return last


class TriggerChecker:
    def __init__(self, stop_event: threading.Event, params_csv: Path | None = None) -> None:
        self._stop = stop_event
        self._params_csv = params_csv
        self._last_fired: dict[str, float] = {}
        self._prev_price: float | None = None

    def _can_fire(self, key: str) -> bool:
        return time.time() - self._last_fired.get(key, 0.0) >= SIGNAL_DEDUP_SEC

    def _fire(self, signal_type: str, details: dict, dedup_key: str | None = None) -> None:
        key = dedup_key or signal_type
        self._last_fired[key] = time.time()
        _write_signal(signal_type, details)
        logger.info("trigger.fired signal=%s details=%s", signal_type, details)

    def _check_liq_cascade(self) -> None:
        if not self._can_fire("LIQ_CASCADE"):
            return
        total_qty = _sum_liq_qty_recent(LIQ_CASCADE_WINDOW_SEC)
        if total_qty >= LIQ_CASCADE_BTC_THRESHOLD:
            self._fire("LIQ_CASCADE", {
                "qty_btc": round(total_qty, 4),
                "window_sec": LIQ_CASCADE_WINDOW_SEC,
                "threshold": LIQ_CASCADE_BTC_THRESHOLD,
            })

    def _check_rsi_extreme(self) -> None:
        if not self._can_fire("RSI_EXTREME"):
            return
        rsi_1h = compute_rsi_from_csv(OHLCV_1H_CSV)
        if rsi_1h is not None:
            if rsi_1h > RSI_1H_OVERBOUGHT:
                self._fire("RSI_EXTREME", {"timeframe": "1h", "rsi": rsi_1h, "condition": "overbought"})
                return
            if rsi_1h < RSI_1H_OVERSOLD:
                self._fire("RSI_EXTREME", {"timeframe": "1h", "rsi": rsi_1h, "condition": "oversold"})
                return
        # 15m RSI_EXTREME отключён 2026-05-07 по требованию оператора:
        # 15m oversold/overbought = шум 30% времени без context, спамит чат.
        # RSI divergences остаются через services/market_intelligence/event_detectors/rsi_divergence.py
        # (там логика серьёзнее — price HH + RSI LH).

    def _check_level_break(self, price: float) -> None:
        if self._prev_price is None or self._prev_price == price:
            return
        levels = get_levels(self._prev_price, self._params_csv)
        for lvl in levels.above + levels.below:
            crossed = (
                (self._prev_price < lvl <= price) or
                (self._prev_price > lvl >= price)
            )
            if not crossed:
                continue
            dedup_key = f"LEVEL_BREAK_{int(lvl)}"
            if self._can_fire(dedup_key):
                direction = "up" if price > self._prev_price else "down"
                self._fire(
                    "LEVEL_BREAK",
                    {"level": lvl, "direction": direction, "price": round(price, 2)},
                    dedup_key=dedup_key,
                )
                # Paper-trade in break direction: continuation hypothesis.
                # Через weekly aggregator увидим какие уровни (по типу/величине)
                # дают edge — потом фильтр или промаут.
                try:
                    import sys as _sys
                    from pathlib import Path as _P
                    _sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
                    from services.paper_signal_tracker.journal import record_paper_signal
                    trade_side = "LONG" if direction == "up" else "SHORT"
                    record_paper_signal(
                        source="level_break", side=trade_side,
                        entry=float(price),
                        stop_pct=-0.5, tp_pct=0.75, hold_h=2,
                        context=f"break_{direction}_lvl_{int(lvl)}",
                    )
                except Exception:
                    logger.exception("trigger.level_break_paper_failed")

    def run(self, check_interval_sec: int = 30) -> None:
        while not self._stop.wait(check_interval_sec):
            try:
                self._check_liq_cascade()
                self._check_rsi_extreme()
                price = _get_current_price()
                if price is not None:
                    self._check_level_break(price)
                    self._prev_price = price
            except Exception:
                logger.exception("trigger_checker.loop_failed")
