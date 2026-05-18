"""Spike-defensive detector — TG-only alert, no trading.

Trigger (all must hold):
  1. |close[t] - close[t-5min]| / close[t-5min] >= PRICE_MOVE_THRESHOLD_PCT
  2. taker_buy_pct >= TAKER_DOMINANT_PCT (for upspike) OR
     taker_sell_pct >= TAKER_DOMINANT_PCT (for downspike)
  3. oi_change_1h_pct >= OI_RISING_THRESHOLD_PCT (OI not bleeding off)

Emits one TG card per (symbol, direction) per cooldown window. Card text
reminds operator to close SHORT-bags (upspike) or LONG-bags (downspike) on
GinArea bots — they accumulate counter-trend exposure and a 1.5–3% spike
can wipe several days of grid PnL in minutes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DERIV_LIVE_PATH = ROOT / "state" / "deriv_live.json"
DEDUP_PATH = ROOT / "state" / "spike_alert_dedup.json"

POLL_INTERVAL_SEC = 60
WINDOW_MINUTES = 5  # 5-bar 1m window for price-move calc
PRICE_MOVE_THRESHOLD_PCT = 1.5
TAKER_DOMINANT_PCT = 75.0
OI_RISING_THRESHOLD_PCT = 0.0  # >=0 = not bleeding off; raise to e.g. 1.0 to require active OI growth
COOLDOWN_SEC = 1800  # 30 min between alerts per (symbol, direction)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "XRPUSDT")


def _load_dedup() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        return json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_dedup(d: dict) -> None:
    try:
        DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEDUP_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("spike_alert.dedup_save_failed")


def _read_deriv_live() -> dict:
    if not DERIV_LIVE_PATH.exists():
        return {}
    try:
        return json.loads(DERIV_LIVE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("spike_alert.deriv_live_read_failed")
        return {}


def _compute_move_pct(symbol: str) -> tuple[float, float] | None:
    """Returns (move_pct, current_close) where move_pct is signed
    (close[-1] - close[-WINDOW_MINUTES-1]) / close[-WINDOW_MINUTES-1] * 100.
    None on data error."""
    try:
        from core.data_loader import load_klines
        df = load_klines(symbol=symbol, timeframe="1m", limit=WINDOW_MINUTES + 2)
        if df is None or len(df) < WINDOW_MINUTES + 1:
            return None
        c_now = float(df["close"].iloc[-1])
        c_then = float(df["close"].iloc[-(WINDOW_MINUTES + 1)])
        if c_then <= 0:
            return None
        return (c_now - c_then) / c_then * 100.0, c_now
    except Exception:
        logger.exception("spike_alert.move_calc_failed symbol=%s", symbol)
        return None


def _format_alert(symbol: str, direction: str, move_pct: float, price: float,
                  taker_pct: float, oi_change_pct: float) -> str:
    arrow = "🚀" if direction == "up" else "📉"
    bag_warn = "SHORT-bags" if direction == "up" else "LONG-bags"
    side_taker = "buy" if direction == "up" else "sell"
    return (
        f"{arrow} СПАЙК {symbol} ({direction.upper()}) — закрой {bag_warn} на ботах\n"
        f"\n"
        f"Движение: {move_pct:+.2f}% за {WINDOW_MINUTES} мин\n"
        f"Цена: ${price:,.2f}\n"
        f"Taker {side_taker} dominant: {taker_pct:.1f}% (>{TAKER_DOMINANT_PCT:.0f}% порог)\n"
        f"OI 1h: {oi_change_pct:+.2f}% (поджатие/рост)\n"
        f"\n"
        f"Цель алерта: предотвратить просадку $4-7k от накопленных {bag_warn}.\n"
        f"Бот не торгует — это только напоминание оператору."
    )


def _check_one_symbol(symbol: str, deriv_live: dict, now: datetime,
                     dedup: dict, send_fn) -> None:
    sym_data = deriv_live.get(symbol)
    if not isinstance(sym_data, dict):
        return

    taker_buy = sym_data.get("taker_buy_pct")
    taker_sell = sym_data.get("taker_sell_pct")
    oi_change = sym_data.get("oi_change_1h_pct")
    if taker_buy is None or taker_sell is None or oi_change is None:
        return

    move = _compute_move_pct(symbol)
    if move is None:
        return
    move_pct, price = move

    if oi_change < OI_RISING_THRESHOLD_PCT:
        return  # OI bleeding off — likely closure, not impulsive spike

    # Upspike: |move|>=threshold AND positive AND taker_buy dominant
    if move_pct >= PRICE_MOVE_THRESHOLD_PCT and taker_buy >= TAKER_DOMINANT_PCT:
        direction = "up"
        taker_pct = taker_buy
    elif move_pct <= -PRICE_MOVE_THRESHOLD_PCT and taker_sell >= TAKER_DOMINANT_PCT:
        direction = "down"
        taker_pct = taker_sell
    else:
        return

    key = f"{symbol}_{direction}"
    last_sent_str = dedup.get(key)
    if last_sent_str:
        try:
            last_sent = datetime.fromisoformat(last_sent_str.replace("Z", "+00:00"))
            if (now - last_sent).total_seconds() < COOLDOWN_SEC:
                return
        except ValueError:
            pass

    text = _format_alert(symbol, direction, move_pct, price, taker_pct, oi_change)
    logger.info("spike_alert.fire symbol=%s dir=%s move=%.2f%% taker=%.1f%% oi=%.2f%%",
                symbol, direction, move_pct, taker_pct, oi_change)
    if send_fn is not None:
        try:
            send_fn(text)
        except Exception:
            logger.exception("spike_alert.send_failed symbol=%s", symbol)

    # Paper-trade BOTH directions (фейд + продолжение) — оператор спросил
    # "как использовать сигналы которые в обе стороны?". Через weekly
    # aggregator увидим какое направление имеет edge.
    if symbol == "BTCUSDT":
        try:
            from services.paper_signal_tracker.journal import record_paper_signal
            # fade: торгуем ПРОТИВ движения
            fade_side = "SHORT" if direction == "up" else "LONG"
            # continuation: торгуем ПО движению
            cont_side = "LONG" if direction == "up" else "SHORT"
            record_paper_signal(
                source="spike_alert", side=fade_side, entry=float(price),
                stop_pct=-0.5, tp_pct=0.75, hold_h=2,
                context=f"{direction}_fade_taker{taker_pct:.0f}",
                now=now,
            )
            record_paper_signal(
                source="spike_alert", side=cont_side, entry=float(price),
                stop_pct=-0.5, tp_pct=0.75, hold_h=2,
                context=f"{direction}_continuation_taker{taker_pct:.0f}",
                now=now,
            )
        except Exception:
            logger.exception("spike_alert.paper_signal_failed")

    dedup[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")


async def spike_alert_loop(stop_event: asyncio.Event, *, send_fn=None,
                           interval_sec: int = POLL_INTERVAL_SEC) -> None:
    """Async loop. Every 60s: check each symbol, fire on spike, dedup 30min."""
    if send_fn is None:
        logger.warning("spike_alert.no_send_fn — alerts будут только в логе")
    logger.info("spike_alert.start interval=%ds move>=%.1f%% taker>=%.0f%% oi>=%.1f%%",
                interval_sec, PRICE_MOVE_THRESHOLD_PCT, TAKER_DOMINANT_PCT, OI_RISING_THRESHOLD_PCT)

    while not stop_event.is_set():
        try:
            now = datetime.now(timezone.utc)
            deriv_live = _read_deriv_live()
            dedup = _load_dedup()
            for symbol in SYMBOLS:
                _check_one_symbol(symbol, deriv_live, now, dedup, send_fn)
            _save_dedup(dedup)
        except Exception:
            logger.exception("spike_alert.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
