"""Session Breakout live loop — TG-эмиттер + outcome tracker.

Mirrors services/range_hunter/loop.py architecture.
"""
from __future__ import annotations

import asyncio
import csv
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from services.session_breakout.journal import (
    JOURNAL_PATH,
    append_signal,
    boundary_already_fired,
    mark_user_action,
    read_all,
    signal_id_from_ts,
    update_record,
)
from services.session_breakout.signal import (
    DEFAULT_PARAMS,
    SessionBreakoutParams,
    SessionBreakoutSignal,
    compute_signal,
    format_tg_card,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"

POLL_INTERVAL_SEC = 60


# ──────────────────────────────────────────────────────────────────────
# Data load
# ──────────────────────────────────────────────────────────────────────

def _load_recent_1m(needed_hours: int = 30,
                    csv_path: Path = MARKET_1M_CSV) -> Optional[pd.DataFrame]:
    """Load tail of market_1m.csv as DataFrame with DatetimeIndex (UTC).

    needed_hours: at least 24h+entry_window+session for prior session lookback.
    """
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path)
    except OSError:
        return None
    if df.empty or "ts_utc" not in df.columns:
        return None
    df["ts"] = pd.to_datetime(df["ts_utc"], format="ISO8601",
                                errors="coerce", utc=True)
    df = df.dropna(subset=["ts"]).sort_values("ts")
    cutoff = pd.Timestamp.utcnow() - pd.Timedelta(hours=needed_hours)
    df = df[df["ts"] >= cutoff]
    if df.empty:
        return None
    df = df.set_index("ts")
    if not {"high", "low", "close"}.issubset(df.columns):
        return None
    return df[["high", "low", "close"]].astype(float)


# ──────────────────────────────────────────────────────────────────────
# Signal emission
# ──────────────────────────────────────────────────────────────────────

def _build_keyboard(signal_id: str):
    try:
        from telebot import types
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ Placed", callback_data=f"sb:placed:{signal_id}"),
            types.InlineKeyboardButton("⏭ Skip", callback_data=f"sb:skip:{signal_id}"),
        )
        return kb
    except Exception:
        return None


def check_and_emit(*, send_fn: Optional[Callable] = None,
                   params: SessionBreakoutParams = DEFAULT_PARAMS,
                   csv_path: Path = MARKET_1M_CSV,
                   journal_path: Path = JOURNAL_PATH,
                   now: Optional[datetime] = None,
                   ) -> Optional[dict]:
    """One signal tick. Returns fired signal record or None."""
    if now is None:
        now = datetime.now(timezone.utc)
    df = _load_recent_1m(csv_path=csv_path)
    if df is None or len(df) < 60:
        return None

    sig = compute_signal(df, now=now, params=params)
    if sig is None:
        return None

    # Dedup: one signal per (transition, day)
    day_iso = now.strftime("%Y-%m-%d")
    if boundary_already_fired(sig.transition, day_iso, path=journal_path):
        return None

    record = {
        "signal_id": signal_id_from_ts(now, sig.side),
        "ts_signal": sig.ts,
        **asdict(sig),
        "user_action": None,
        "placed_at": None,
        "decision_latency_sec": None,
        "exit_ts": None,
        "exit_reason": None,
        "exit_price": None,
        "pnl_usd": None,
    }
    append_signal(record, path=journal_path)

    # Фильтр переходов (оператор 2026-07-21: «оставляй лондон») — остальные
    # копятся в журнал молча и получают исход теневым учётом.
    from services.session_breakout.stats import tg_allowed
    if send_fn is not None and tg_allowed(sig.transition):
        expiry = now + timedelta(hours=sig.hold_h)
        try:
            text = format_tg_card(sig, expiry_ts=expiry)
            send_fn(text, reply_markup=_build_keyboard(record["signal_id"]))
        except Exception:
            logger.exception("session_breakout.send_failed")
    elif send_fn is not None:
        logger.info("session_breakout.silent_journal transition=%s (TG-фильтр)",
                    sig.transition)

    logger.info("session_breakout.signal side=%s transition=%s entry=%.0f stop=%.0f tp=%.0f",
                sig.side, sig.transition, sig.entry, sig.stop, sig.tp)
    return record


# ──────────────────────────────────────────────────────────────────────
# Outcome tracker — оценивает placed signals
# ──────────────────────────────────────────────────────────────────────

# BitMEX taker fee (linear XBTUSDT)
TAKER_FEE_PCT = 0.075
MAKER_REBATE_PCT = 0.04    # XBTUSDT linear: мейкер получает ребейт 0.04%/сторону
MAKER_WAIT_MIN = 15        # сколько ждём налива лимитки на уровне входа


def simulate_maker(record: dict, df, entry_ts, expiry) -> dict:
    """Честная симуляция мейкер-исполнения: лимитка НА уровне входа.

    Ключевое отличие от наивного «те же сделки дешевле»: лимитку наливают
    только если цена вернётся к уровню (для шорта — вверх к entry, для лонга —
    вниз). На пробое цена уходит ОТ уровня, поэтому часть сделок не состоится
    вовсе — это и есть цена мейкер-исполнения, которую нельзя игнорировать.

    Вход — мейкер (ребейт), выход — тейкер (консервативно).
    """
    side = record["side"]
    entry = float(record["entry"])
    stop = float(record["stop"])
    tp = float(record["tp"])
    size_usd = float(record["size_usd"])
    out = {"maker_filled": False, "maker_fill_ts": None,
           "maker_exit_reason": None, "pnl_maker_real_usd": None}

    # окно ожидания налива — со следующего бара (на баре сигнала цена уже на
    # уровне, засчитывать это как гарантированный налив нечестно)
    wait = df[(df.index > entry_ts)
              & (df.index <= entry_ts + timedelta(minutes=MAKER_WAIT_MIN))]
    if wait.empty:
        return out
    if side == "long":
        hits = wait.index[wait["low"] <= entry]
    else:
        hits = wait.index[wait["high"] >= entry]
    if not len(hits):
        return out                      # лимитку не налили — сделки не было

    fill_ts = hits[0]
    out["maker_filled"] = True
    out["maker_fill_ts"] = fill_ts.isoformat(timespec="seconds")

    path = df[(df.index > fill_ts) & (df.index <= expiry)]
    exit_price, reason = None, None
    for ts_bar, row in path.iterrows():
        hi, lo = float(row["high"]), float(row["low"])
        if side == "long":
            if lo <= stop:
                exit_price, reason = stop, "sl_hit"
                break
            if hi >= tp:
                exit_price, reason = tp, "tp_hit"
                break
        else:
            if hi >= stop:
                exit_price, reason = stop, "sl_hit"
                break
            if lo <= tp:
                exit_price, reason = tp, "tp_hit"
                break
    if exit_price is None:
        if path.empty:
            return out                  # ещё в процессе
        exit_price, reason = float(path["close"].iloc[-1]), "timeout"

    if side == "long":
        gross = size_usd * (exit_price - entry) / entry
    else:
        gross = size_usd * (entry - exit_price) / entry
    # вход мейкером (ребейт), выход тейкером
    fees = size_usd * (TAKER_FEE_PCT / 100.0) - size_usd * (MAKER_REBATE_PCT / 100.0)
    out["maker_exit_reason"] = reason
    out["pnl_maker_real_usd"] = round(gross - fees, 2)
    return out


def evaluate_outcome(record: dict, df: pd.DataFrame, *,
                     now: Optional[datetime] = None) -> Optional[dict]:
    """Simulate hold path: check if TP/SL hit or hold expired.

    Returns dict of updates or None if still in progress.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        ts_sig = datetime.fromisoformat(record["ts_signal"])
    except (KeyError, ValueError):
        return None
    # 2026-07-21: раньше исход считался ТОЛЬКО для user_action=="placed" —
    # оператор кнопки не жмёт, поэтому за 2 месяца не записалось ни одного
    # исхода и у семьи не было живой статистики. Теперь считаем ВСЕ сигналы
    # (теневой учёт), различая их полем tracked_as.
    placed_at = record.get("placed_at")
    if placed_at:
        try:
            entry_ts = datetime.fromisoformat(placed_at)
        except ValueError:
            entry_ts = ts_sig
    else:
        entry_ts = ts_sig

    hold_h = int(record.get("hold_h", 3))
    expiry = entry_ts + timedelta(hours=hold_h)

    if df.empty:
        return None
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
        df = df.copy()
        df.index = idx

    win = df[(df.index >= entry_ts) & (df.index <= min(now, expiry))]
    if win.empty:
        return None

    side = record["side"]
    entry = float(record["entry"])
    stop = float(record["stop"])
    tp = float(record["tp"])
    size_usd = float(record["size_usd"])

    exit_ts: Optional[datetime] = None
    exit_reason: Optional[str] = None
    exit_price: Optional[float] = None

    for ts_bar, row in win.iterrows():
        hi = float(row["high"])
        lo = float(row["low"])
        if side == "long":
            if lo <= stop:
                exit_ts, exit_reason, exit_price = ts_bar, "sl_hit", stop
                break
            if hi >= tp:
                exit_ts, exit_reason, exit_price = ts_bar, "tp_hit", tp
                break
        else:
            if hi >= stop:
                exit_ts, exit_reason, exit_price = ts_bar, "sl_hit", stop
                break
            if lo <= tp:
                exit_ts, exit_reason, exit_price = ts_bar, "tp_hit", tp
                break

    if exit_ts is None:
        if now >= expiry:
            exit_ts = expiry
            exit_reason = "timeout"
            exit_price = float(win["close"].iloc[-1])
        else:
            return None  # still in progress

    if side == "long":
        gross = size_usd * (exit_price - entry) / entry
    else:
        gross = size_usd * (entry - exit_price) / entry
    fees = size_usd * (TAKER_FEE_PCT / 100.0) * 2.0
    pnl_usd = gross - fees
    # «Что было бы мейкером» — карточка велит Market (тейкер) по $1.50/сделку
    # при среднем брутто ~$0.5, т.е. способ исполнения решает экономику семьи.
    # ВЕРХНЯЯ ГРАНИЦА: те же входы/выходы, но по мейкер-ребейту; риск
    # неисполнения лимитки (adverse selection) здесь НЕ учтён.
    maker_fees = -size_usd * (MAKER_REBATE_PCT / 100.0) * 2.0

    return {
        "exit_ts": exit_ts.isoformat(timespec="seconds"),
        "exit_reason": exit_reason,
        "exit_price": round(float(exit_price), 2),
        "pnl_usd": round(pnl_usd, 2),          # НЕТТО: комиссии уже вычтены
        "gross_usd": round(gross, 2),
        "fees_usd": round(fees, 2),
        "pnl_maker_usd": round(gross - maker_fees, 2),  # верхняя граница
        **simulate_maker(record, df, entry_ts, expiry),  # честная симуляция
        "tracked_as": ("placed" if record.get("user_action") == "placed"
                       else "shadow"),
    }


def check_outcomes(*, csv_path: Path = MARKET_1M_CSV,
                   journal_path: Path = JOURNAL_PATH,
                   send_fn: Optional[Callable] = None) -> int:
    """Check pending placed signals, update outcomes. Returns count updated."""
    rows = read_all(path=journal_path)
    # ВСЕ незакрытые сигналы, не только «placed» (теневой учёт — оператор
    # 2026-07-21: «веди статистику, накопишь — подведём итоги»)
    pending = [r for r in rows if r.get("exit_reason") is None]
    if not pending:
        return 0
    df = _load_recent_1m(needed_hours=12, csv_path=csv_path)
    if df is None:
        return 0
    updated = 0
    for r in pending:
        upd = evaluate_outcome(r, df)
        if upd is None:
            continue
        update_record(r["signal_id"], upd, path=journal_path)
        updated += 1
        # TG — только по реально размещённым; теневые копятся молча
        # (бюджет шума: 40 сигналов за 2 мес = 40 лишних сообщений)
        if send_fn is not None and upd.get("tracked_as") == "placed":
            try:
                msg = (f"📊 Session Breakout exit [{r['transition']} {r['side'].upper()}]\n"
                       f"  reason: {upd['exit_reason']}  exit: ${upd['exit_price']:,.2f}\n"
                       f"  PnL: ${upd['pnl_usd']:+,.2f}")
                send_fn(msg)
            except Exception:
                logger.exception("session_breakout.outcome_send_failed")
    return updated


# ──────────────────────────────────────────────────────────────────────
# Async loops
# ──────────────────────────────────────────────────────────────────────

async def session_breakout_signal_loop(stop_event: asyncio.Event, *,
                                        send_fn: Optional[Callable] = None,
                                        params: SessionBreakoutParams = DEFAULT_PARAMS,
                                        interval_sec: int = POLL_INTERVAL_SEC,
                                        ) -> None:
    logger.info("session_breakout.signal_loop.start interval=%ds tg=%s",
                interval_sec, "on" if send_fn else "off")
    while not stop_event.is_set():
        try:
            check_and_emit(send_fn=send_fn, params=params)
        except Exception:
            logger.exception("session_breakout.signal_loop_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
    logger.info("session_breakout.signal_loop.stopped")


async def session_breakout_outcome_loop(stop_event: asyncio.Event, *,
                                         send_fn: Optional[Callable] = None,
                                         interval_sec: int = POLL_INTERVAL_SEC,
                                         ) -> None:
    logger.info("session_breakout.outcome_loop.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            n = check_outcomes(send_fn=send_fn)
            if n:
                logger.info("session_breakout.outcomes_updated n=%d", n)
        except Exception:
            logger.exception("session_breakout.outcome_loop_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
    logger.info("session_breakout.outcome_loop.stopped")
