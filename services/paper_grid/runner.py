"""Paper grid runner — per-symbol async loop.

Mirrors the logic of scripts/volume_farm_grid_backtest.py but runs LIVE on
1m bars fetched from Binance via core.data_loader. Tracks state across ticks
in state/paper_grid_<symbol>_state.json. Appends daily aggregate row to
state/paper_grid_<symbol>.jsonl.

Strategy per symbol (sweet-spot from 2026-05-17 sweep):
  grid_range_pct = 0.6
  grid_levels    = 120
  order_size_usd = 1000
  inventory_cap_usd_equiv = 7800  (converted to native at first tick)
  reanchor_drift_pct = 0.3
  hard_stop_unrealized_usd = -2000

Fees: ETHUSDT / XRPUSDT on BitMEX linear (maker -0.02% / taker +0.075%).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"

# Per-symbol sweet-spot params (from sweep — XBTUSD-inverse math; ETH/XRP linear
# fees are similar so directional results carry; absolute PnL will differ).
SYMBOL_PARAMS = {
    "ETHUSDT": {
        "grid_range_pct": 0.6,
        "grid_levels": 120,
        "order_size_usd": 1000.0,
        "inventory_cap_usd_equiv": 7800.0,
        "reanchor_drift_pct": 0.3,
        "reanchor_interval_min": 30,
        "hard_stop_unrealized_usd": -2000.0,
    },
    "XRPUSDT": {
        "grid_range_pct": 0.6,
        "grid_levels": 120,
        "order_size_usd": 1000.0,
        "inventory_cap_usd_equiv": 7800.0,
        "reanchor_drift_pct": 0.3,
        "reanchor_interval_min": 30,
        "hard_stop_unrealized_usd": -2000.0,
    },
}

# BitMEX linear (ETHUSDT/XRPUSDT) fees in bp
MAKER_BP_LINEAR = -2.0  # rebate
TAKER_BP_LINEAR = 7.5


@dataclass
class State:
    symbol: str
    anchor: float = 0.0
    last_reanchor_ts: Optional[str] = None
    last_processed_ts: Optional[str] = None
    pos_native: float = 0.0
    avg_entry: float = 0.0
    cash_usd: float = 0.0
    rebates_usd: float = 0.0
    volume_usd: float = 0.0
    fills: int = 0
    halted: bool = False
    halt_until_ts: Optional[str] = None
    inventory_cap_native: float = 0.0  # set on first tick from cap_usd / first_mid
    day_state: dict = field(default_factory=dict)  # rolling day aggregates


def _state_path(symbol: str) -> Path:
    return STATE_DIR / f"paper_grid_{symbol}_state.json"


def _journal_path(symbol: str) -> Path:
    return STATE_DIR / f"paper_grid_{symbol}.jsonl"


def _load_state(symbol: str) -> State:
    path = _state_path(symbol)
    if not path.exists():
        return State(symbol=symbol)
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return State(**d)
    except (OSError, json.JSONDecodeError, TypeError):
        logger.exception("paper_grid.load_state_failed symbol=%s", symbol)
        return State(symbol=symbol)


def _save_state(state: State) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _state_path(state.symbol).write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.exception("paper_grid.save_state_failed symbol=%s", state.symbol)


def _append_journal(symbol: str, record: dict) -> None:
    try:
        _journal_path(symbol).parent.mkdir(parents=True, exist_ok=True)
        with _journal_path(symbol).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("paper_grid.append_journal_failed symbol=%s", symbol)


def _fee_usd(notional_usd: float) -> float:
    """Maker fee on linear contract — negative = rebate (credit)."""
    return notional_usd * MAKER_BP_LINEAR / 10000.0


def _unrealized_usd(state: State, mark: float) -> float:
    """Linear contract PnL: qty_native * (mark - entry) * sign."""
    if state.pos_native == 0:
        return 0.0
    sign = 1 if state.pos_native > 0 else -1
    return abs(state.pos_native) * (mark - state.avg_entry) * sign


def _close_all(state: State, mark: float) -> None:
    if state.pos_native == 0:
        return
    notional = abs(state.pos_native) * mark
    sign_old = 1 if state.pos_native > 0 else -1
    realized = abs(state.pos_native) * (mark - state.avg_entry) * sign_old
    taker_fee = notional * TAKER_BP_LINEAR / 10000.0
    state.cash_usd += realized - taker_fee
    state.pos_native = 0.0
    state.avg_entry = 0.0


def _step_fill(state: State, params: dict, side: str, level: float) -> None:
    """One fill: side='buy' (long-side, lower-grid) or 'sell' (short-side, upper)."""
    qty_native = params["order_size_usd"] / level
    if side == "buy" and state.pos_native >= state.inventory_cap_native:
        return
    if side == "sell" and state.pos_native <= -state.inventory_cap_native:
        return

    signed_qty = qty_native if side == "buy" else -qty_native
    new_pos = state.pos_native + signed_qty

    if state.pos_native == 0 or (state.pos_native > 0 and signed_qty > 0) or (state.pos_native < 0 and signed_qty < 0):
        notional_old = state.avg_entry * abs(state.pos_native)
        notional_new = level * abs(signed_qty)
        if abs(new_pos) > 0:
            state.avg_entry = (notional_old + notional_new) / abs(new_pos)
    else:
        # reducing or flipping → realize partial
        closed_qty = min(abs(state.pos_native), abs(signed_qty))
        sign_old = 1 if state.pos_native > 0 else -1
        realized = closed_qty * (level - state.avg_entry) * sign_old
        state.cash_usd += realized
        if abs(signed_qty) > abs(state.pos_native):
            state.avg_entry = level

    state.pos_native = new_pos
    if abs(state.pos_native) < 1e-9:
        state.pos_native = 0.0
        state.avg_entry = 0.0
    state.fills += 1
    state.volume_usd += params["order_size_usd"]
    state.rebates_usd -= _fee_usd(params["order_size_usd"])  # rebate = positive credit


def _load_recent_1m(symbol: str, limit: int = 5):
    """Fetch last N 1m bars for symbol via Binance REST (cached)."""
    try:
        from core.data_loader import load_klines
        return load_klines(symbol=symbol, timeframe="1m", limit=limit)
    except Exception:
        logger.exception("paper_grid.load_klines_failed symbol=%s", symbol)
        return None


def _process_bar(state: State, params: dict, bar: dict) -> None:
    """Process one 1m OHLC bar against the virtual grid."""
    mid = float(bar["close"])
    high = float(bar["high"])
    low = float(bar["low"])

    # First bar — set anchor + cap
    if state.anchor == 0.0:
        state.anchor = mid
        state.inventory_cap_native = params["inventory_cap_usd_equiv"] / mid
        state.last_reanchor_ts = bar.get("ts_iso")

    # Hard-stop on unrealized DD
    unr_now = _unrealized_usd(state, mid)
    if not state.halted and unr_now < params["hard_stop_unrealized_usd"]:
        _close_all(state, mid)
        state.halted = True
        # Resume 60 min later
        from datetime import timedelta as _td
        state.halt_until_ts = (datetime.now(timezone.utc) + _td(minutes=60)).isoformat(timespec="seconds")
        logger.info("paper_grid.hard_stop symbol=%s unrealized=%.2f", state.symbol, unr_now)
        return
    if state.halted and state.halt_until_ts:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(state.halt_until_ts):
                state.halted = False
                state.anchor = mid
                state.last_reanchor_ts = bar.get("ts_iso")
        except ValueError:
            state.halted = False
        if state.halted:
            return

    # Reanchor on drift or interval
    drift = abs(mid - state.anchor) / state.anchor * 100.0 if state.anchor > 0 else 0
    do_reanchor = drift > params["reanchor_drift_pct"]
    if state.last_reanchor_ts:
        try:
            last = datetime.fromisoformat(state.last_reanchor_ts.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - last).total_seconds() / 60.0 >= params["reanchor_interval_min"]:
                do_reanchor = True
        except ValueError:
            pass
    if do_reanchor:
        state.anchor = mid
        state.last_reanchor_ts = bar.get("ts_iso")

    # Check each grid level
    half = params["grid_levels"] // 2
    step_pct = params["grid_range_pct"] / half
    for k in range(1, half + 1):
        buy_lvl = state.anchor * (1 - k * step_pct / 100.0)
        if low <= buy_lvl <= state.anchor:
            _step_fill(state, params, "buy", buy_lvl)
        sell_lvl = state.anchor * (1 + k * step_pct / 100.0)
        if state.anchor <= sell_lvl <= high:
            _step_fill(state, params, "sell", sell_lvl)


def _maybe_emit_daily(state: State, mark: float) -> None:
    """Append daily aggregate when day boundary crosses."""
    today = datetime.now(timezone.utc).date().isoformat()
    last_day = state.day_state.get("date")
    if last_day is None:
        state.day_state = {
            "date": today, "start_cash": state.cash_usd, "start_vol": state.volume_usd,
            "start_rebates": state.rebates_usd, "start_fills": state.fills,
        }
        return
    if last_day == today:
        return
    # Day boundary: emit aggregate for last_day
    unr = _unrealized_usd(state, mark)
    record = {
        "date": last_day, "symbol": state.symbol,
        "volume_usd": round(state.volume_usd - state.day_state["start_vol"], 2),
        "rebates_usd": round(state.rebates_usd - state.day_state["start_rebates"], 4),
        "realized_usd": round(state.cash_usd - state.day_state["start_cash"], 2),
        "fills": state.fills - state.day_state["start_fills"],
        "pos_native_eod": round(state.pos_native, 6),
        "unrealized_usd_eod": round(unr, 2),
        "net_usd": round(
            (state.cash_usd - state.day_state["start_cash"])
            + (state.rebates_usd - state.day_state["start_rebates"])
            + unr, 2),
        "halted": state.halted,
    }
    _append_journal(state.symbol, record)
    state.day_state = {
        "date": today, "start_cash": state.cash_usd, "start_vol": state.volume_usd,
        "start_rebates": state.rebates_usd, "start_fills": state.fills,
    }


async def paper_grid_loop(stop_event: asyncio.Event, *, symbol: str,
                          interval_sec: int = 60) -> None:
    """Per-symbol async loop. Ticks every minute, processes one 1m bar."""
    if symbol not in SYMBOL_PARAMS:
        logger.error("paper_grid.unknown_symbol %s", symbol)
        return
    params = SYMBOL_PARAMS[symbol]
    state = _load_state(symbol)
    logger.info("paper_grid.%s.start interval=%ds levels=%d size=$%d cap=$%d",
                symbol, interval_sec, params["grid_levels"], params["order_size_usd"],
                params["inventory_cap_usd_equiv"])

    while not stop_event.is_set():
        try:
            df = _load_recent_1m(symbol, limit=3)
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                bar = {
                    "open": latest.get("open"),
                    "high": latest.get("high"),
                    "low": latest.get("low"),
                    "close": latest.get("close"),
                    "ts_iso": str(latest.get("open_time")),
                }
                # De-dup: only process if we haven't seen this bar
                if state.last_processed_ts != bar["ts_iso"]:
                    _process_bar(state, params, bar)
                    state.last_processed_ts = bar["ts_iso"]
                _maybe_emit_daily(state, float(bar["close"]))
                _save_state(state)
        except Exception:
            logger.exception("paper_grid.%s.tick_failed", symbol)

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("paper_grid.%s.stopped", symbol)
