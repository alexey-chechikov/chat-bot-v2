"""Outcome evaluator — читает pending paper signals, симулирует на 1m данных,
проверяет TP/SL/timeout, обновляет journal.
"""
from __future__ import annotations

import asyncio
import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from services.paper_signal_tracker.journal import (
    JOURNAL_PATH,
    TAKER_FEE_PCT,
    pending_signals,
    update_outcome,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"
TICK_INTERVAL_SEC = 300  # 5 min


def _load_recent_1m(needed_hours: int = 12,
                    csv_path: Path = MARKET_1M_CSV) -> list[tuple[datetime, float, float, float]]:
    """Return list of (ts, high, low, close) within last needed_hours."""
    if not csv_path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=needed_hours)
    out: list[tuple[datetime, float, float, float]] = []
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("ts_utc", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                try:
                    hi = float(row["high"])
                    lo = float(row["low"])
                    cl = float(row["close"])
                except (KeyError, ValueError):
                    continue
                out.append((ts, hi, lo, cl))
    except OSError:
        logger.exception("paper_signal.market_load_failed")
    out.sort(key=lambda t: t[0])
    return out


def _pnl_usd(side: str, entry: float, exit_price: float, size_usd: float) -> float:
    """Realized PnL net of 2× taker fees. Linear contract assumption (per $1 notional)."""
    if entry <= 0:
        return 0.0
    if side == "LONG":
        gross_pct = (exit_price - entry) / entry
    else:
        gross_pct = (entry - exit_price) / entry
    gross_usd = size_usd * gross_pct
    fees_usd = size_usd * (TAKER_FEE_PCT / 100.0) * 2.0
    return gross_usd - fees_usd


def evaluate_one(record: dict, bars: list[tuple[datetime, float, float, float]],
                 *, now: Optional[datetime] = None) -> Optional[dict]:
    """Check single pending signal against bars. Returns updates dict OR None if still pending."""
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        ts_sig = datetime.fromisoformat(record["ts_signal"])
    except (KeyError, ValueError):
        return None
    hold_h = int(record.get("hold_h", 4))
    expiry = ts_sig + timedelta(hours=hold_h)

    side = record["side"]
    entry = float(record["entry"])
    stop = float(record["stop"])
    tp = float(record["tp"])
    size_usd = float(record.get("size_usd", 1000.0))

    for ts_bar, hi, lo, cl in bars:
        if ts_bar < ts_sig:
            continue
        if ts_bar > expiry:
            break
        if side == "LONG":
            if lo <= stop:
                return {"outcome": "sl_hit", "exit_ts": ts_bar, "exit_price": stop,
                        "pnl_usd": _pnl_usd(side, entry, stop, size_usd)}
            if hi >= tp:
                return {"outcome": "tp_hit", "exit_ts": ts_bar, "exit_price": tp,
                        "pnl_usd": _pnl_usd(side, entry, tp, size_usd)}
        else:
            if hi >= stop:
                return {"outcome": "sl_hit", "exit_ts": ts_bar, "exit_price": stop,
                        "pnl_usd": _pnl_usd(side, entry, stop, size_usd)}
            if lo <= tp:
                return {"outcome": "tp_hit", "exit_ts": ts_bar, "exit_price": tp,
                        "pnl_usd": _pnl_usd(side, entry, tp, size_usd)}

    if now >= expiry and bars:
        last_close = bars[-1][3]
        return {"outcome": "timeout", "exit_ts": expiry, "exit_price": last_close,
                "pnl_usd": _pnl_usd(side, entry, last_close, size_usd)}
    return None


def _load_recent_1m_symbol(symbol: str, needed_hours: int
                           ) -> list[tuple[datetime, float, float, float]]:
    """Symbol-aware 1m bars. BTCUSDT uses the pre-collected CSV (fast); other
    symbols (alt TV signals, alt_decorr) fetch via the API loader."""
    if symbol.upper() in ("BTCUSDT", "", "BTC"):
        return _load_recent_1m(needed_hours=needed_hours)
    try:
        from core.data_loader import load_klines
        limit = min(1000, needed_hours * 60 + 10)
        df = load_klines(symbol=symbol, timeframe="1m", limit=limit)
        if df is None or df.empty:
            return []
        tcol = next((c for c in ("ts", "open_time", "timestamp") if c in df.columns), None)
        if tcol is None:
            return []
        import pandas as pd
        ts = pd.to_datetime(df[tcol], utc=True, errors="coerce")
        out = [(t.to_pydatetime(), float(h), float(lo), float(cl))
               for t, h, lo, cl in zip(ts, df["high"], df["low"], df["close"])
               if t is not None]
        out.sort(key=lambda x: x[0])
        return out
    except Exception:
        logger.exception("paper_signal.alt_market_load_failed symbol=%s", symbol)
        return []


def tick(*, journal_path: Path = JOURNAL_PATH,
         market_csv: Path = MARKET_1M_CSV,
         now: Optional[datetime] = None) -> int:
    pending = pending_signals(path=journal_path)
    if not pending:
        return 0
    # group by symbol so each signal resolves against its own instrument's bars
    by_symbol: dict[str, list[dict]] = {}
    for r in pending:
        by_symbol.setdefault(str(r.get("symbol", "BTCUSDT")).upper(), []).append(r)
    n = 0
    for symbol, recs in by_symbol.items():
        max_hold = max(int(r.get("hold_h", 4)) for r in recs) + 1
        if symbol in ("BTCUSDT", "", "BTC"):
            bars = _load_recent_1m(needed_hours=max_hold, csv_path=market_csv)
        else:
            bars = _load_recent_1m_symbol(symbol, needed_hours=max_hold)
        if not bars:
            continue
        for r in recs:
            upd = evaluate_one(r, bars, now=now)
            if upd is None:
                continue
            if update_outcome(r["signal_id"], upd["outcome"], upd["exit_ts"],
                              upd["exit_price"], upd["pnl_usd"], path=journal_path):
                n += 1
    return n


async def paper_signal_evaluator_loop(stop_event: asyncio.Event, *,
                                       interval_sec: int = TICK_INTERVAL_SEC) -> None:
    logger.info("paper_signal.evaluator.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            n = tick()
            if n:
                logger.info("paper_signal.outcomes_updated n=%d", n)
        except Exception:
            logger.exception("paper_signal.evaluator_tick_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
    logger.info("paper_signal.evaluator.stopped")
