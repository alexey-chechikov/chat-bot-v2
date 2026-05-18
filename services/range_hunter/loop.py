"""Range Hunter live loop — генерирует TG-сигналы + следит за outcome.

Два независимых цикла:
1. signal_loop — раз в минуту читает market_live/market_1m.csv, считает фильтры,
   при срабатывании шлёт TG-карточку + пишет в журнал.
2. outcome_loop — раз в минуту проходит по pending signals (user_action="placed"),
   симулирует fill BUY/SELL/SL/timeout на свежих 1m данных, пишет результат.

Cooldown: 2h после signal (any direction) — не шлём повторных пока не пройдёт.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from services.range_hunter.signal import (
    DEFAULT_PARAMS,
    RangeHunterParams,
    RangeHunterSignal,
    compute_signal,
    format_tg_card,
)
from services.range_hunter.journal import (
    JOURNAL_PATH,
    append_signal,
    journal_path_for,
    pending_signals,
    read_all,
    signal_id_from_ts,
    update_record,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"
STATE_PATH = ROOT / "state" / "range_hunter_state.json"

POLL_INTERVAL_SEC = 60


# ──────────────────────────────────────────────────────────────────────
# Signal loop
# ──────────────────────────────────────────────────────────────────────

def _load_recent_1m(*, needed_bars: int, csv_path: Path = MARKET_1M_CSV,
                    symbol: str = "BTCUSDT",
                    bar_minutes: int = 1) -> Optional[pd.DataFrame]:
    """Load recent OHLCV. bar_minutes=1 returns native 1m, bar_minutes>1
    resamples 1m → bar_minutes.

    BTCUSDT 1m: market_live/market_1m.csv (Bybit WS stream).
    Другие символы / 5m+: fetch через core.data_loader (Binance REST, 12s TTL).
    """
    # Needed 1m bars: для 5m нужно needed_bars * 5 минутных баров
    raw_needed = needed_bars * max(1, bar_minutes)

    if symbol.upper() == "BTCUSDT" and csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
        except (OSError, pd.errors.ParserError):
            logger.exception("range_hunter.read_1m_failed symbol=%s", symbol)
            return None
        if df.empty or "ts_utc" not in df.columns:
            return None
        df["ts"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts"]).set_index("ts").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df.tail(raw_needed + 20)
    else:
        try:
            from core.data_loader import load_klines
            df = load_klines(symbol=symbol.upper(), timeframe="1m",
                              limit=max(raw_needed + 20, 300))
        except Exception:
            logger.exception("range_hunter.load_klines_failed symbol=%s", symbol)
            return None
        if df is None or df.empty:
            return None
        if not isinstance(df.index, pd.DatetimeIndex):
            for col in ("ts", "ts_utc", "timestamp", "open_time"):
                if col in df.columns:
                    df = df.set_index(pd.to_datetime(df[col], utc=True, errors="coerce"))
                    break
        df = df.sort_index()

    # Resample to bar_minutes if > 1
    if bar_minutes > 1:
        rule = f"{bar_minutes}min"
        df = df.resample(rule).agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
    return df.tail(needed_bars + 10)


def _last_signal_ts(*, journal_path: Path = JOURNAL_PATH) -> Optional[datetime]:
    """Время последнего сигнала (для cooldown)."""
    rows = read_all(path=journal_path)
    if not rows:
        return None
    try:
        last_iso = rows[-1].get("ts_signal", "")
        return datetime.fromisoformat(last_iso) if last_iso else None
    except (ValueError, TypeError):
        return None


def _build_signal_record(sig: RangeHunterSignal, *, symbol: str = "BTCUSDT",
                          variant: str = "1m") -> dict:
    """Compose journal record from signal."""
    return {
        "signal_id": signal_id_from_ts(datetime.fromisoformat(sig.ts),
                                         symbol=symbol, variant=variant),
        "ts_signal": sig.ts,
        "symbol": symbol.upper(),
        "variant": variant,
        "mid_signal": sig.mid,
        "buy_level": sig.buy_level,
        "sell_level": sig.sell_level,
        "stop_loss_pct": sig.stop_loss_pct,
        "size_usd": sig.size_usd,
        "size_btc": sig.size_btc,
        "contract": sig.contract,
        "hold_h": sig.hold_h,
        "range_4h_pct": sig.range_4h_pct,
        "atr_pct": sig.atr_pct,
        "trend_pct_per_h": sig.trend_pct_per_h,
        "levels_source": getattr(sig, "levels_source", "mid_symmetric"),
        "proximity_score": getattr(sig, "proximity_score", 0.0),
        "placed_at": None,
        "user_action": None,
        "decision_latency_sec": None,
        "buy_fill_ts": None,
        "sell_fill_ts": None,
        "exit_ts": None,
        "exit_reason": None,
        "legs_filled": None,
        "pnl_usd": None,
    }


def check_and_emit(*, send_fn: Optional[Callable] = None,
                   params: RangeHunterParams = DEFAULT_PARAMS,
                   csv_path: Path = MARKET_1M_CSV,
                   journal_path: Optional[Path] = None,
                   now: Optional[datetime] = None,
                   ) -> Optional[dict]:
    """One tick of signal-detection. Returns fired signal record or None.

    send_fn: callable(text, reply_markup=None) — для TG. Если None — только в журнал.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if journal_path is None:
        journal_path = journal_path_for(params.symbol,
                                         variant=getattr(params, "variant_name", "1m"))

    # Cooldown (per-symbol — журнал отдельный)
    last_ts = _last_signal_ts(journal_path=journal_path)
    if last_ts is not None:
        elapsed = (now - last_ts).total_seconds() / 3600.0
        if elapsed < params.cooldown_h:
            return None  # too soon

    bar_min = getattr(params, "bar_minutes", 1) or 1
    needed = params.lookback_h * 60 // bar_min  # bars в lookback с учётом TF
    df = _load_recent_1m(needed_bars=needed, csv_path=csv_path,
                          symbol=params.symbol, bar_minutes=bar_min)
    if df is None or len(df) < needed:
        return None

    sig = compute_signal(df, params)
    if sig is None:
        return None

    record = _build_signal_record(sig, symbol=params.symbol,
                                     variant=getattr(params, "variant_name", "1m"))
    append_signal(record, path=journal_path)

    if send_fn is not None:
        expiry = now + timedelta(hours=sig.hold_h)
        try:
            text = format_tg_card(sig, expiry_ts=expiry)
            # symbol уже в шапке через [SYMBOL] суффикс из format_tg_card
            send_fn(text, reply_markup=_build_keyboard(record["signal_id"]))
        except Exception:
            logger.exception("range_hunter.send_failed")

    logger.info("range_hunter.signal symbol=%s mid=%.0f range=%.2f%% atr=%.2f%% trend=%+.2f%%/h",
                params.symbol, sig.mid, sig.range_4h_pct, sig.atr_pct, sig.trend_pct_per_h)
    return record


def _build_keyboard(signal_id: str):
    """Build inline keyboard for TG. Returns None if telebot не доступен."""
    try:
        from telebot import types  # noqa
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ Placed both", callback_data=f"rh:placed:{signal_id}"),
            types.InlineKeyboardButton("⏭ Skip", callback_data=f"rh:skip:{signal_id}"),
        )
        return kb
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────
# Outcome tracker
# ──────────────────────────────────────────────────────────────────────

# BitMEX fees (Tier 1, linear XBTUSDT)
MAKER_REBATE_PCT = 0.02   # +0.02% rebate
TAKER_FEE_PCT = 0.075


def evaluate_outcome(record: dict, df: pd.DataFrame, *,
                     now: Optional[datetime] = None) -> Optional[dict]:
    """Simulate fills of BUY/SELL legs and decide outcome.

    Returns dict of updates (buy_fill_ts/sell_fill_ts/exit_ts/exit_reason/legs_filled/pnl_usd)
    or None if outcome ещё не определён (timeout не наступил).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        ts_signal = datetime.fromisoformat(record["ts_signal"])
        placed_at = datetime.fromisoformat(record.get("placed_at") or record["ts_signal"])
    except (ValueError, TypeError):
        return None

    hold_h = int(record["hold_h"])
    deadline = placed_at + timedelta(hours=hold_h)
    deadline_reached = now >= deadline

    buy_level = float(record["buy_level"])
    sell_level = float(record["sell_level"])
    sl_pct = float(record["stop_loss_pct"])
    size_usd = float(record["size_usd"])
    mid_signal = float(record["mid_signal"])

    # Scan bars from placed_at to min(now, deadline)
    end_t = min(now, deadline)
    window = df[(df.index >= placed_at) & (df.index <= end_t)]
    if window.empty:
        if not deadline_reached:
            return None  # ждём данных
        # Бары пропали (нет 1m данных) — закроем как timeout без fill
        return _resolve_no_fill(end_t)

    buy_fill_ts = None
    sell_fill_ts = None
    for ts, bar in window.iterrows():
        if buy_fill_ts is None and float(bar["low"]) <= buy_level:
            buy_fill_ts = ts
        if sell_fill_ts is None and float(bar["high"]) >= sell_level:
            sell_fill_ts = ts
        if buy_fill_ts is not None and sell_fill_ts is not None:
            break

    # Если ничего не fill'нулось и до deadline ещё есть время — ждём
    if buy_fill_ts is None and sell_fill_ts is None and not deadline_reached:
        return None

    size_btc = size_usd / mid_signal

    # Case A: обе fill — pair_win
    if buy_fill_ts is not None and sell_fill_ts is not None:
        # spread = sell - buy. PnL = size_btc * spread. Plus 2x maker rebate.
        spread = sell_level - buy_level
        pnl_spread = size_btc * spread
        rebate = 2 * size_usd * (MAKER_REBATE_PCT / 100.0)
        pnl = pnl_spread + rebate
        exit_ts = max(buy_fill_ts, sell_fill_ts)
        return {
            "buy_fill_ts": buy_fill_ts.isoformat(),
            "sell_fill_ts": sell_fill_ts.isoformat(),
            "exit_ts": exit_ts.isoformat(),
            "exit_reason": "pair_win",
            "legs_filled": 2,
            "pnl_usd": round(pnl, 2),
        }

    # Case B: только BUY fill — стоп при движении против на sl_pct, иначе timeout
    if buy_fill_ts is not None and sell_fill_ts is None:
        sl_price = buy_level * (1 - sl_pct / 100.0)
        # ищем SL hit после buy_fill
        after_buy = window[window.index > buy_fill_ts]
        sl_idx = None
        for ts, bar in after_buy.iterrows():
            if float(bar["low"]) <= sl_price:
                sl_idx = ts
                break
        if sl_idx is not None:
            # taker exit at sl_price
            pnl_move = size_btc * (sl_price - buy_level)
            maker_in = size_usd * (MAKER_REBATE_PCT / 100.0)
            taker_out = size_usd * (TAKER_FEE_PCT / 100.0)
            pnl = pnl_move + maker_in - taker_out
            return {
                "buy_fill_ts": buy_fill_ts.isoformat(),
                "exit_ts": sl_idx.isoformat(),
                "exit_reason": "buy_stopped",
                "legs_filled": 1,
                "pnl_usd": round(pnl, 2),
            }
        if deadline_reached:
            # timeout exit at last close
            last_close = float(window["close"].iloc[-1])
            pnl_move = size_btc * (last_close - buy_level)
            maker_in = size_usd * (MAKER_REBATE_PCT / 100.0)
            taker_out = size_usd * (TAKER_FEE_PCT / 100.0)
            pnl = pnl_move + maker_in - taker_out
            return {
                "buy_fill_ts": buy_fill_ts.isoformat(),
                "exit_ts": end_t.isoformat(),
                "exit_reason": "buy_timeout",
                "legs_filled": 1,
                "pnl_usd": round(pnl, 2),
            }
        return None  # ждём

    # Case C: только SELL fill
    if sell_fill_ts is not None and buy_fill_ts is None:
        sl_price = sell_level * (1 + sl_pct / 100.0)
        after_sell = window[window.index > sell_fill_ts]
        sl_idx = None
        for ts, bar in after_sell.iterrows():
            if float(bar["high"]) >= sl_price:
                sl_idx = ts
                break
        if sl_idx is not None:
            pnl_move = size_btc * (sell_level - sl_price)
            maker_in = size_usd * (MAKER_REBATE_PCT / 100.0)
            taker_out = size_usd * (TAKER_FEE_PCT / 100.0)
            pnl = pnl_move + maker_in - taker_out
            return {
                "sell_fill_ts": sell_fill_ts.isoformat(),
                "exit_ts": sl_idx.isoformat(),
                "exit_reason": "sell_stopped",
                "legs_filled": 1,
                "pnl_usd": round(pnl, 2),
            }
        if deadline_reached:
            last_close = float(window["close"].iloc[-1])
            pnl_move = size_btc * (sell_level - last_close)
            maker_in = size_usd * (MAKER_REBATE_PCT / 100.0)
            taker_out = size_usd * (TAKER_FEE_PCT / 100.0)
            pnl = pnl_move + maker_in - taker_out
            return {
                "sell_fill_ts": sell_fill_ts.isoformat(),
                "exit_ts": end_t.isoformat(),
                "exit_reason": "sell_timeout",
                "legs_filled": 1,
                "pnl_usd": round(pnl, 2),
            }
        return None

    # Deadline reached, no fills
    if deadline_reached:
        return _resolve_no_fill(end_t)
    return None


def _resolve_no_fill(end_t: datetime) -> dict:
    return {
        "exit_ts": end_t.isoformat(),
        "exit_reason": "no_fill",
        "legs_filled": 0,
        "pnl_usd": 0.0,
    }


# ──────────────────────────────────────────────────────────────────────
# Hedge advisor + Cross-strategy confirmation
# ──────────────────────────────────────────────────────────────────────

HEDGE_SUGGEST_MIN_AGE_MIN = 30  # single-leg >30min — пора хеджить
CASCADE_DEDUP_PATH = ROOT / "state" / "cascade_alert_dedup.json"
CROSS_STRATEGY_MAX_AGE_MIN = 60  # cascade сработавший за час назад ещё актуален

# Map: какие cascade-сигналы ↔ ожидаемое направление цены (2026 edge profile).
# - SHORT cascade (shorts liquidated) → price continuation UP — survived в обоих периодах
# - LONG cascade (longs liquidated) → 2026 INVERSION: price continuation DOWN
#   (2024 был bounce up, edge инвертировался — см. cascade_backtest_combined)
# Mega 10BTC исключаем — отдельный edge.
CASCADE_BULL_SIGNALS = ("short_2.0", "short_5.0")     # → подтверждение LONG-orphan
CASCADE_BEAR_SIGNALS = ("long_2.0", "long_5.0")        # → подтверждение SHORT-orphan


def _check_cross_strategy_confirmation(orphan_side: str, *,
                                       now: Optional[datetime] = None,
                                       max_age_min: int = CROSS_STRATEGY_MAX_AGE_MIN,
                                       dedup_path: Path = CASCADE_DEDUP_PATH,
                                       ) -> list[dict]:
    """Cross-strategy hedge intelligence: вернуть cascade-сигналы которые
    подтверждают направление orphan-leg за последние max_age_min минут.

    orphan_side: 'LONG' | 'SHORT'.

    Возвращает список [{key, ts, age_min}, ...] или пустой список.

    Логика: если у нас уже открыта LONG-нога Range Hunter и ровно в это
    время бот зафаерил SHORT-cascade (= ожидание price up) — это
    БЕСПЛАТНОЕ подтверждение, хедж НЕ нужен, держим. Аналогично SHORT-
    нога + LONG-cascade (в 2026 это price down signal).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not dedup_path.exists():
        return []
    try:
        dedup = json.loads(dedup_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    candidates = CASCADE_BULL_SIGNALS if orphan_side == "LONG" else CASCADE_BEAR_SIGNALS
    found = []
    for key in candidates:
        ts_str = dedup.get(key)
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        age_min = (now - ts).total_seconds() / 60.0
        if 0 < age_min <= max_age_min:
            found.append({"key": key, "ts": ts.isoformat(), "age_min": round(age_min, 1)})
    return found


def hedge_advice(record: dict, df: pd.DataFrame, *, now: Optional[datetime] = None) -> Optional[str]:
    """Если у активного сетапа single-leg fill >30мин — вернуть TG-нудж.

    Хедж-режим:
      - LONG leg open (buy filled, sell ещё ждём) → советуем market SHORT
        на встречной бирже того же объёма. Дельта → 0, ждём sell_fill либо
        timeout. На timeout закрываем хедж + позицию (минус 2 taker, ~$8).
      - Аналогично SELL leg open → market LONG хедж.
    Vs текущий SL: вместо -$25.5 (SL hit + taker) кушаем -$8 (2×taker слиппедж).
    Save ~$17 на single-leg событии. В бэктесте 609 такого за 2y → +$10K/2y.

    TODO: автоматизация требует Binance/exchange API. Сейчас — только TG nudge.
    Cross-strategy: если в этот момент cascade-сигнал в ту же сторону что и
    наш orphan-leg — это free подтверждение, хедж НЕ нужен. (TODO: read
    state/cascade_alert_dedup.json для проверки.)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        placed_at = datetime.fromisoformat(record.get("placed_at") or record["ts_signal"])
    except (ValueError, TypeError, KeyError):
        return None
    if record.get("user_action") != "placed":
        return None
    if record.get("hedge_suggested_at"):
        return None  # уже отправляли — не дублируем

    buy_level = float(record["buy_level"])
    sell_level = float(record["sell_level"])
    size_usd = float(record["size_usd"])
    mid_signal = float(record["mid_signal"])

    window = df[(df.index >= placed_at) & (df.index <= now)]
    if window.empty:
        return None

    buy_filled = (window["low"] <= buy_level).any()
    sell_filled = (window["high"] >= sell_level).any()
    if buy_filled and sell_filled:
        return None  # обе fill — это уже pair_win, скоро resolve
    if not buy_filled and not sell_filled:
        return None  # нет fill — ничего хеджить

    # Один leg висит. Сколько он висит?
    if buy_filled:
        fill_ts = window.index[(window["low"] <= buy_level).values][0]
        side_open = "LONG"
        fill_px = buy_level
        hedge_dir = "SHORT"
    else:
        fill_ts = window.index[(window["high"] >= sell_level).values][0]
        side_open = "SHORT"
        fill_px = sell_level
        hedge_dir = "LONG"

    age_min = (now - fill_ts).total_seconds() / 60.0
    if age_min < HEDGE_SUGGEST_MIN_AGE_MIN:
        return None

    last_close = float(window["close"].iloc[-1])
    unrealized_pct = (last_close / fill_px - 1) * 100 * (1 if side_open == "LONG" else -1)

    # Cross-strategy confirmation check (Layer 9 из ROADMAP).
    # Если каскад в ту же сторону что и наш orphan — хедж НЕ нужен, держим.
    # Phase 1 audit 2026-05-18: passive confirmation без action = шум.
    # При наличии cascade-подтверждения просто SKIP hedge advice (молча).
    confirms = _check_cross_strategy_confirmation(side_open, now=now)
    if confirms:
        return None

    lines = [
        f"⚠️ HEDGE ADVISORY  {record['signal_id']}",
        f"Range Hunter: {side_open}-нога открыта {age_min:.0f} мин назад @ ${fill_px:,.0f}",
        f"Текущая цена ${last_close:,.0f}  (unrealized {unrealized_pct:+.2f}%)",
        f"Противоположная нога ${(sell_level if side_open=='LONG' else buy_level):,.0f} НЕ исполнена",
        "",
        f"Опция А (рекомендуем): захедж market {hedge_dir} ${size_usd:,.0f} на Binance.",
        f"  → дельта → 0, ждём оставшуюся ногу или таймаут.",
        f"  → cost: ~2× taker fee = ~$8 (vs SL hit ~$25).",
        "",
        f"Опция Б: закрыть {side_open}-ногу руками на market.",
        f"  → лосс = текущий unrealized × size + taker fee.",
        "",
        f"Опция В: ждать дальше (по умолчанию). SL сработает при движении 0.20% против.",
    ]
    return "\n".join(lines)


def check_outcomes(*, csv_path: Path = MARKET_1M_CSV,
                   journal_path: Path = JOURNAL_PATH,
                   symbol: str = "BTCUSDT",
                   bar_minutes: int = 1,
                   now: Optional[datetime] = None,
                   hedge_send_fn: Optional[Callable] = None) -> int:
    """One pass — try to resolve all pending signals. Returns count resolved."""
    if now is None:
        now = datetime.now(timezone.utc)
    pendings = pending_signals(path=journal_path)
    if not pendings:
        return 0
    # На 5m hold_h может быть 24 — даём 32h tail чтоб покрыть с запасом
    tail_bars = 32 * 60 // bar_minutes if bar_minutes > 1 else 24 * 60
    df = _load_recent_1m(needed_bars=tail_bars, csv_path=csv_path,
                          symbol=symbol, bar_minutes=bar_minutes)
    if df is None or df.empty:
        return 0
    n_resolved = 0
    for rec in pendings:
        upd = evaluate_outcome(rec, df, now=now)
        if upd is not None:
            update_record(rec["signal_id"], upd, path=journal_path)
            n_resolved += 1
            logger.info("range_hunter.outcome id=%s reason=%s pnl=%s",
                        rec["signal_id"], upd.get("exit_reason"), upd.get("pnl_usd"))
            continue
        # Сделка ещё не resolved — посмотрим, не пора ли советовать хедж
        if hedge_send_fn is not None:
            advice = hedge_advice(rec, df, now=now)
            if advice:
                try:
                    hedge_send_fn(advice)
                    update_record(rec["signal_id"],
                                  {"hedge_suggested_at": now.isoformat(timespec="seconds")},
                                  path=journal_path)
                except Exception:
                    logger.exception("range_hunter.hedge_send_failed")
    return n_resolved


# ──────────────────────────────────────────────────────────────────────
# Async loops
# ──────────────────────────────────────────────────────────────────────

async def range_hunter_signal_loop(stop_event: asyncio.Event, *,
                                   send_fn: Optional[Callable] = None,
                                   params: RangeHunterParams = DEFAULT_PARAMS,
                                   interval_sec: int = POLL_INTERVAL_SEC) -> None:
    logger.info("range_hunter.signal_loop.start symbol=%s interval=%ds width=%.2f%% hold=%dh",
                params.symbol, interval_sec, params.width_pct, params.hold_h)
    while not stop_event.is_set():
        try:
            check_and_emit(send_fn=send_fn, params=params)
        except Exception:
            logger.exception("range_hunter.signal_loop.tick_failed symbol=%s", params.symbol)
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("range_hunter.signal_loop.stopped symbol=%s", params.symbol)


async def range_hunter_outcome_loop(stop_event: asyncio.Event, *,
                                    hedge_send_fn: Optional[Callable] = None,
                                    params: RangeHunterParams = DEFAULT_PARAMS,
                                    interval_sec: int = POLL_INTERVAL_SEC) -> None:
    logger.info("range_hunter.outcome_loop.start symbol=%s interval=%ds hedge_advisor=%s",
                params.symbol, interval_sec, "on" if hedge_send_fn else "off")
    journal_path = journal_path_for(params.symbol,
                                      variant=getattr(params, "variant_name", "1m"))
    bar_min = getattr(params, "bar_minutes", 1) or 1
    while not stop_event.is_set():
        try:
            n = check_outcomes(hedge_send_fn=hedge_send_fn,
                                journal_path=journal_path,
                                symbol=params.symbol,
                                bar_minutes=bar_min)
            if n > 0:
                logger.info("range_hunter.outcome_loop.resolved symbol=%s n=%d", params.symbol, n)
        except Exception:
            logger.exception("range_hunter.outcome_loop.tick_failed symbol=%s", params.symbol)
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("range_hunter.outcome_loop.stopped symbol=%s", params.symbol)
