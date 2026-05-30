"""Main async loop for auto_executor.

Tick rhythm (TICK_INTERVAL_SEC):
  1. Refresh balance from BitMEX, roll daily-pnl counter if new UTC day.
  2. If we have an open position:
       a. If status=placed, look up the entry order — promote to filled
          when BitMEX reports it as Filled (or set status=cancelled if
          order is gone). Notify FILLED.
       b. If status=filled, check current price vs SL/TP1/EXPIRE.
          On first trigger → place market SELL to flatten, mark closed,
          append outcome to outcomes.jsonl, run kill-switch eval.
  3. If we are FREE (no open position) AND no global freeze, read new
     entries from state/setups.jsonl since saved byte offset. For each
     long_pdl_bounce / long_multi_divergence setup on BTCUSDT:
       gates.can_open → if allowed, place limit BUY and persist.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from services.auto_executor import gates, notifier
from services.auto_executor.bitmex_client import BitMEXClient, BitMEXError
from services.auto_executor.state import (
    OFFSET_PATH,
    OUTCOMES_PATH,
    STATE_PATH,
    KillState,
    Position,
    State,
    append_outcome,
    load_offset,
    load_state,
    reset_daily_pnl_if_new_day,
    save_offset,
    save_state,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SETUPS_JSONL = ROOT / "state" / "setups.jsonl"

# ─── Tuning ────────────────────────────────────────────────────────
TICK_INTERVAL_SEC = 30           # how often to poll
ENTRY_TIMEOUT_MIN = 5            # if limit not filled after this: cancel (see below)
# 2026-05-30 reality-filter finding: in the 6 live trades, EVERY market_fallback
# entry hit SL (4/4) while EVERY clean limit fill did NOT (2/2 flat). Chasing a
# non-filling post-only limit at market = entering adverse momentum + paying
# +0.23% slippage. So when the limit doesn't fill in ENTRY_TIMEOUT_MIN we now
# CANCEL and skip the trade (limit-only entry) instead of market-falling-back.
MARKET_FALLBACK_ENABLED = False
LOT_SIZE = 100                   # BitMEX XBTUSDT lotSize
LOTS_PER_TRADE = 100             # 100 lots = 0.0001 BTC = ~$7.70 at $77k
BITMEX_SYMBOL = "XBTUSDT"        # UI: "BTCUSDT"; API: "XBTUSDT"
MAX_PARALLEL = 3                 # backtest 2026-05-27: 1→3 +44% PnL, DD 3.5%→5.9%
                                  # — sweet spot. 2 is worse than 1 (cluster losses);
                                  # 4+ has diminishing returns.

# Hybrid entry policy (2026-05-26): try post-only limit first, fall back
# to market if not filled within ENTRY_TIMEOUT_MIN. SL/TP are recalculated
# off the actual market fill, preserving the setup's planned R:R.
ENTRY_MODE_LIMIT = "limit"
ENTRY_MODE_MARKET_FALLBACK = "market_fallback"

# Per-setup parameter overrides — picked from backtest 2026-05-27 on
# n=46 historical long_pdl_bounce signals against market_1m.csv. Optimal
# combo SL 0.40% / TP 0.70% / hold 6h gave +0.108%/trade after 0.10% RT
# fees vs ~+0.05%/trade with the setup_detector's emitted SL/TP. The
# setup_detector's values stay in the journal for audit, but the
# autotrader places orders against these fixed %-distances.
# long_multi_divergence keeps its own SL/TP — fixed-grid backtest was
# negative EV (pattern-geometry stop/TP is intrinsic to that detector).
# 2026-05-30 REVERTED the tp1.5/sl0.5 "exit edge": it was a 20-day May regime
# fluke. The 2-YEAR backtest (tools/_setup_2y_backtest.py, real detectors over 2y
# frozen price) gave WR 32% / EV −0.18% / PF 0.42 on n=2049, NEGATIVE every year
# (2024/2025/2026). Lesson: time-split within ONE regime ≠ OOS; only multi-year
# multi-regime validation counts. No 2y-robust exit edge in these setups → keep
# the prior conservative pdl_bounce override, no dump_reversal override.
SETUP_OVERRIDES: dict[str, dict] = {
    "long_pdl_bounce": {
        "sl_pct": 0.40,
        "tp1_pct": 0.70,
        "tp2_pct": 1.00,
        "hold_hours": 6,
    },
}


# ─── Helpers ───────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _read_new_setups(offset: int) -> tuple[list[dict], int]:
    """Read setups.jsonl from byte offset to EOF. Returns (records, new_offset).

    Robust against partial last line — if EOF in middle of a record,
    keep the partial line's start as the new offset so we re-read next tick.
    """
    if not SETUPS_JSONL.exists():
        return [], offset
    records: list[dict] = []
    try:
        with SETUPS_JSONL.open("rb") as f:
            f.seek(offset)
            buf = f.read()
        # if we got nothing new, return same offset
        if not buf:
            return [], offset
        text = buf.decode("utf-8", errors="replace")
        # split into lines, keeping track of bytes per line
        new_offset = offset
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            if not stripped:
                new_offset += len(line.encode("utf-8"))
                continue
            if not line.endswith("\n") and not line.endswith("\r\n"):
                # partial line at EOF — leave its bytes unread, will revisit
                break
            new_offset += len(line.encode("utf-8"))
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError:
                logger.warning("auto_executor.setups_parse_failed line=%r", stripped[:200])
        return records, new_offset
    except OSError:
        logger.exception("auto_executor.setups_read_failed")
        return [], offset


def _calc_qty_lots() -> int:
    """Return the BitMEX orderQty in raw contract units. Must be multiple of LOT_SIZE."""
    # constant for now — could be made dynamic against current price if we want fixed-USD sizing.
    return LOTS_PER_TRADE


def _lots_to_btc(lots: int) -> float:
    """XBTUSDT: 100 lots = 0.0001 BTC."""
    return lots / 1_000_000.0


# ─── Phase-2b: multi-symbol (alt) sizing ───────────────────────────────────
# BitMEX linear-perp symbols (BTC is the special "XBT" ticker).
SYMBOL_MAP = {"BTCUSDT": "XBTUSDT", "ETHUSDT": "ETHUSDT", "XRPUSDT": "XRPUSDT"}
TARGET_NOMINAL_USD = 8.0       # micro target; ETH min lot (~$20) overrides upward
NOMINAL_GUARD_MAX_USD = 30.0   # HARD safety: never place a position above this


def _bitmex_symbol(pair: str) -> str:
    return SYMBOL_MAP.get(pair, pair)


def _qty_from_instrument(inst: dict, price: float,
                         target_usd: float = TARGET_NOMINAL_USD
                         ) -> tuple[int, float, float]:
    """Pure: size a micro position from live instrument specs.

    underlying_qty = orderQty / underlyingToPositionMultiplier (BitMEX linear).
    Returns (qty_lots, qty_underlying, nominal_usd). (0,0,0) if unsafe
    (price<=0, bad specs, or nominal would exceed the hard guard).
    """
    try:
        lot = int(inst.get("lotSize") or 0)
        u2p = float(inst.get("underlyingToPositionMultiplier") or 0)
    except (TypeError, ValueError):
        return 0, 0.0, 0.0
    if lot <= 0 or u2p <= 0 or price <= 0:
        return 0, 0.0, 0.0
    raw = target_usd / price * u2p          # contracts for target nominal
    lots = max(lot, round(raw / lot) * lot)  # at least 1 lot-unit, multiple of lotSize
    qty_under = lots / u2p
    nominal = qty_under * price
    if nominal > NOMINAL_GUARD_MAX_USD or lots <= 0:
        return 0, 0.0, 0.0
    return int(lots), qty_under, nominal


def _size_for_symbol(client: BitMEXClient, bsym: str, price: float
                     ) -> tuple[int, float, float]:
    """Fetch instrument + size. (0,0,0) on any failure (caller skips the trade)."""
    if bsym == "XBTUSDT":
        # keep the proven BTC path exactly (100 lots = 0.0001 BTC ≈ $7-8)
        qb = _lots_to_btc(LOTS_PER_TRADE)
        return LOTS_PER_TRADE, qb, qb * price
    try:
        inst = client.get_instrument(bsym)
    except BitMEXError:
        logger.warning("auto_executor.instrument_fetch_failed sym=%s", bsym)
        return 0, 0.0, 0.0
    return _qty_from_instrument(inst, price)


def _est_pnl_usd_long(qty_btc: float, entry: float, exit_: float) -> float:
    """Linear PnL: (exit - entry) * qty_btc (USDT-margined linear contract)."""
    return (exit_ - entry) * qty_btc


# ─── Side-aware primitives (2026-05-29 phase-2: SHORT support) ──────────
# Pure functions, unit-tested for inversion. LONG branches reproduce the prior
# long-only behaviour byte-for-byte; SHORT branches mirror them.
def _est_pnl_usd(side: str, qty_btc: float, entry: float, exit_: float) -> float:
    """Linear PnL. long: (exit-entry)·q ; short: (entry-exit)·q."""
    if side == "short":
        return (entry - exit_) * qty_btc
    return (exit_ - entry) * qty_btc


def _sl_tp_prices(side: str, entry: float, sl_pct: float,
                  tp1_pct: float, tp2_pct: float) -> tuple[float, float, float]:
    """SL/TP from % distances. long: sl below / tp above; short: inverted."""
    if side == "short":
        sl = entry * (1 + sl_pct / 100.0)
        tp1 = entry * (1 - tp1_pct / 100.0)
        tp2 = entry * (1 - tp2_pct / 100.0)
    else:
        sl = entry * (1 - sl_pct / 100.0)
        tp1 = entry * (1 + tp1_pct / 100.0)
        tp2 = entry * (1 + tp2_pct / 100.0)
    return round(sl, 1), round(tp1, 1), round(tp2, 1)


def _hit_reason(side: str, last: float, sl_price: float,
                tp1_price: float) -> Optional[str]:
    """Which exit (if any) the last price triggers. Inverted for short."""
    if side == "short":
        if last >= sl_price:
            return "sl"
        if last <= tp1_price:
            return "tp1"
    else:
        if last <= sl_price:
            return "sl"
        if last >= tp1_price:
            return "tp1"
    return None


def _open_order_side(side: str) -> str:
    """Order side to OPEN a position. long→Buy, short→Sell."""
    return "Sell" if side == "short" else "Buy"


def _exit_order_side(side: str) -> str:
    """Order side to FLATTEN/reduce a position. long→Sell, short→Buy."""
    return "Buy" if side == "short" else "Sell"


# ─── Tick ──────────────────────────────────────────────────────────
def _refresh_balance_and_daily(state: State, client: BitMEXClient) -> None:
    try:
        m = client.get_margin("USDt")
        # walletBalance is in micro-USDT (1e6 = $1)
        wallet = float(m.get("walletBalance", 0)) / 1_000_000.0
        avail = float(m.get("availableMargin", 0)) / 1_000_000.0
        state.kill.last_known_balance_usd = max(wallet, avail)
        state.kill.last_balance_check = _now().isoformat(timespec="seconds")
    except BitMEXError:
        logger.warning("auto_executor.balance_refresh_failed (non-fatal)")
    reset_daily_pnl_if_new_day(state.kill)


def _recalc_sl_tp_for_fill(pos: Position, actual_entry: float) -> None:
    """Slide SL/TP to preserve the setup's planned %-distance from entry.

    Mutates `pos` in place. If actual_entry == 0 (degenerate), no-op."""
    if not actual_entry or actual_entry <= 0:
        return
    original_entry = pos.entry_price
    sl_dist_pct = (original_entry - pos.sl_price) / original_entry
    tp1_dist_pct = (pos.tp1_price - original_entry) / original_entry
    tp2_dist_pct = ((pos.tp2_price - original_entry) / original_entry
                     if pos.tp2_price else 0)
    pos.sl_price = round(actual_entry * (1 - sl_dist_pct), 1)
    pos.tp1_price = round(actual_entry * (1 + tp1_dist_pct), 1)
    if pos.tp2_price:
        pos.tp2_price = round(actual_entry * (1 + tp2_dist_pct), 1)


def _market_fallback_enter_multi(state: State, client: BitMEXClient,
                                   pos: Position) -> None:
    """Multi-position variant — drops THIS position from state.open_positions on error,
    not the whole list. Mutates `pos` in place on success."""
    notifier.send(notifier.card_market_fallback_start(pos))
    # 1) place market order to OPEN (no execInst Close — opening, not flattening).
    #    long→Buy, short→Sell.
    market_cl_ord = f"mkt-{pos.cl_ord_id}"
    try:
        r = client._request(  # type: ignore[attr-defined]
            "POST", "/api/v1/order",
            body={
                "symbol": pos.bitmex_symbol,
                "side": _open_order_side(pos.side),
                "orderQty": int(pos.qty_lots),
                "ordType": "Market",
                "clOrdID": market_cl_ord,
            },
        )
    except BitMEXError as exc:
        notifier.send(notifier.card_error("market_fallback_place_failed", exc))
        logger.exception("auto_executor.market_fallback_place_failed id=%s",
                          pos.setup_id)
        # drop ONLY this position; keep other open positions intact
        try:
            state.open_positions.remove(pos)
        except ValueError:
            pass
        return
    # 2) figure out actual avg fill — order response often has avgPx;
    #    if not, poll position next tick. For now take avgPx or fallback
    #    to last_price + tiny taker slippage estimate.
    avg_fill = float(r.get("avgPx") or 0.0) if isinstance(r, dict) else 0.0
    if avg_fill <= 0:
        try:
            position_now = client.get_position(pos.bitmex_symbol)
            if position_now:
                avg_fill = float(position_now.get("avgEntryPrice") or 0.0)
        except BitMEXError:
            pass
    if avg_fill <= 0:
        try:
            avg_fill = client.get_last_price(pos.bitmex_symbol)
        except BitMEXError:
            avg_fill = pos.entry_price  # last resort — won't trigger SL/TP shift
    # 3) update position
    pos.avg_entry_price = avg_fill
    _recalc_sl_tp_for_fill(pos, avg_fill)
    pos.entry_order_id = str(r.get("orderID")) if isinstance(r, dict) else pos.entry_order_id
    pos.cl_ord_id = market_cl_ord
    pos.status = "filled"
    pos.filled_at = _now().isoformat(timespec="seconds")
    pos.entry_mode = ENTRY_MODE_MARKET_FALLBACK
    logger.info(
        "auto_executor.market_fallback_filled id=%s avg=%.1f new_sl=%.1f new_tp1=%.1f",
        pos.setup_id, avg_fill, pos.sl_price, pos.tp1_price,
    )
    notifier.send(notifier.card_filled(pos))


def _manage_placed(state: State, client: BitMEXClient) -> None:
    """Iterate over all 'placed' positions:
       - promote to 'filled' if BitMEX shows Filled
       - drop if Canceled/Rejected/Expired
       - market-fallback when ENTRY_TIMEOUT_MIN passes without fill.
    """
    drop_indices: list[int] = []
    for idx, pos in enumerate(list(state.open_positions)):
        if pos.status != "placed":
            continue
        placed_at = _from_iso(pos.placed_at) or _now()
        timeout = placed_at.timestamp() + ENTRY_TIMEOUT_MIN * 60
        if pos.entry_order_id is None:
            logger.warning("auto_executor.placed_without_orderid id=%s — dropping",
                            pos.setup_id)
            drop_indices.append(idx)
            continue
        try:
            order = client.get_order(pos.entry_order_id)
        except BitMEXError:
            logger.warning("auto_executor.get_order_failed id=%s — will retry",
                            pos.entry_order_id)
            continue
        if order is None:
            logger.warning("auto_executor.order_not_found id=%s — clearing",
                            pos.entry_order_id)
            drop_indices.append(idx)
            continue
        status = (order.get("ordStatus") or "").lower()
        if status == "filled":
            pos.status = "filled"
            pos.filled_at = _now().isoformat(timespec="seconds")
            pos.avg_entry_price = float(order.get("avgPx") or pos.entry_price)
            pos.entry_mode = ENTRY_MODE_LIMIT
            logger.info("auto_executor.filled_limit id=%s avg=%.1f",
                         pos.setup_id, pos.avg_entry_price)
            notifier.send(notifier.card_filled(pos))
            continue
        if status in ("canceled", "cancelled", "rejected", "expired"):
            logger.info("auto_executor.entry_terminal_status id=%s status=%s",
                         pos.setup_id, status)
            drop_indices.append(idx)
            continue
        # still working — limit window elapsed.
        if _now().timestamp() >= timeout:
            try:
                client.cancel_order(pos.entry_order_id)
            except BitMEXError:
                logger.warning("auto_executor.cancel_failed id=%s", pos.entry_order_id)
            if MARKET_FALLBACK_ENABLED:
                logger.info("auto_executor.limit_timeout_market_fallback id=%s", pos.setup_id)
                _market_fallback_enter_multi(state, client, pos)
            else:
                # 2026-05-30: limit-only — skip the trade rather than chase at market
                # (market_fallback was 4/4 SL in live data).
                logger.info("auto_executor.limit_timeout_skip id=%s (fallback disabled)",
                             pos.setup_id)
                drop_indices.append(idx)
    # remove dropped (in reverse to keep indices valid)
    for idx in reversed(drop_indices):
        if 0 <= idx < len(state.open_positions):
            state.open_positions.pop(idx)


def _manage_filled(state: State, client: BitMEXClient) -> None:
    """Iterate over filled positions; close each on SL/TP1/EXPIRE.

    IMPORTANT: BitMEX nets positions per symbol — if we hold 3 trades of
    100 lots each, BitMEX shows ONE position of 300 lots. To exit only
    trade A we send a SELL Market of 100 lots WITHOUT execInst=Close
    (Close would flatten the whole 300-lot netted position). Plain qty
    sell reduces by the exact amount.
    """
    if not state.open_positions:
        return
    # Per-symbol last price, fetched once per distinct symbol per tick (phase-2b).
    price_cache: dict[str, float] = {}

    def _last_for(sym: str) -> float:
        if sym not in price_cache:
            try:
                price_cache[sym] = client.get_last_price(sym)
            except BitMEXError:
                logger.warning("auto_executor.last_price_failed sym=%s (non-fatal)", sym)
                price_cache[sym] = 0.0
        return price_cache[sym]

    drop_indices: list[int] = []
    for idx, pos in enumerate(list(state.open_positions)):
        if pos.status != "filled":
            continue
        last = _last_for(pos.bitmex_symbol)
        if last <= 0:
            continue
        reason: Optional[str] = _hit_reason(pos.side, last, pos.sl_price, pos.tp1_price)
        if reason is None and _from_iso(pos.expires_at) and _now() >= _from_iso(pos.expires_at):
            reason = "expire"
        if reason is None:
            continue
        # Close at market — reduce by exact qty, NO execInst=Close (would flatten
        # the netted total). Side is opposite the position: long→Sell, short→Buy.
        try:
            client._request(  # type: ignore[attr-defined]
                "POST", "/api/v1/order",
                body={
                    "symbol": pos.bitmex_symbol,
                    "side": _exit_order_side(pos.side),
                    "orderQty": int(pos.qty_lots),
                    "ordType": "Market",
                    "clOrdID": f"exit-{pos.cl_ord_id}"[:36],
                },
            )
        except BitMEXError as exc:
            notifier.send(notifier.card_error("market_exit_failed", exc))
            logger.exception("auto_executor.market_exit_failed id=%s", pos.setup_id)
            continue
        pos.status = "closed"
        pos.closed_at = _now().isoformat(timespec="seconds")
        pos.exit_reason = reason
        pos.avg_exit_price = last
        entry_for_pnl = pos.avg_entry_price or pos.entry_price
        pos.realized_pnl_usd = _est_pnl_usd(pos.side, pos.qty_btc, entry_for_pnl, last)
        append_outcome(pos)
        gates.record_outcome_update_killstate(
            state.kill, setup_type=pos.setup_type,
            pnl_usd=float(pos.realized_pnl_usd or 0.0),
        )
        notifier.send(notifier.card_closed(pos))
        drop_indices.append(idx)
    # Remove closed positions from the live list
    for idx in reversed(drop_indices):
        if 0 <= idx < len(state.open_positions):
            state.open_positions.pop(idx)
    if drop_indices:
        _maybe_freeze_setups(state)


def _maybe_freeze_setups(state: State) -> None:
    """Re-evaluate the 7d kill-switch against outcomes.jsonl.

    Bucket outcomes by setup_type, look at last 7d window, freeze
    setups whose WR drops below threshold."""
    from datetime import timedelta
    cutoff = _now() - timedelta(days=7)
    by_setup: dict[str, list[float]] = {}
    if not OUTCOMES_PATH.exists():
        return
    try:
        for line in OUTCOMES_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _from_iso(rec.get("closed_at"))
            if ts is None or ts < cutoff:
                continue
            pnl = rec.get("realized_pnl_usd")
            if pnl is None:
                continue
            st_type = rec.get("setup_type", "?")
            # 2026-05-29: after a manual unfreeze, only count trades closed AFTER
            # the unfreeze ts — gives the setup a fresh window instead of instant
            # re-freeze by the same losing streak.
            unfrozen = _from_iso(state.kill.unfrozen_at.get(st_type))
            if unfrozen is not None and ts <= unfrozen:
                continue
            by_setup.setdefault(st_type, []).append(float(pnl))
    except OSError:
        return
    newly = gates.evaluate_killswitch_per_setup(state.kill, outcomes_by_setup=by_setup)
    for st in newly:
        notifier.send(notifier.card_freeze(
            f"setup={st}", "7d WR < 50% (n≥5) — manual /unfreeze to resume",
        ))


def _try_open_new(state: State, client: BitMEXClient, offset: int) -> int:
    """Look for new setups since `offset` and act on every allowed one
    up to MAX_PARALLEL concurrent positions. Returns new offset."""
    if len(state.open_positions) >= MAX_PARALLEL:
        return offset  # full — defer reading until a slot frees
    records, new_offset = _read_new_setups(offset)
    if not records:
        return new_offset
    for setup in records:
        # re-check slot availability each iter (may have placed one in this loop)
        if len(state.open_positions) >= MAX_PARALLEL:
            break
        st = str(setup.get("setup_type", ""))
        pair = str(setup.get("pair", ""))
        if st not in gates.ALLOWED_SETUPS or pair not in gates.ALLOWED_PAIRS:
            continue  # not interesting, but offset already advanced past it
        # check expires — skip stale (older than 60 min)
        detected_at = _from_iso(setup.get("detected_at"))
        if detected_at and (_now() - detected_at).total_seconds() > 3600:
            logger.info("auto_executor.skip_stale id=%s age_min=%.1f",
                         setup.get("setup_id"),
                         (_now() - detected_at).total_seconds() / 60)
            continue
        # cheap fast-fail gates first (don't burn API on current_price for obvious skips)
        ok, reason = gates.can_open(setup, state, current_price=None)
        if not ok:
            logger.info("auto_executor.skip id=%s reason=%s",
                         setup.get("setup_id"), reason)
            notifier.send(notifier.card_skipped(st, reason))
            continue
        bsym = _bitmex_symbol(pair)   # phase-2b: per-pair BitMEX symbol
        # confirm slippage isn't already blown out
        try:
            last = client.get_last_price(bsym)
        except BitMEXError:
            last = 0.0
        ok2, reason2 = gates.can_open(setup, state, current_price=last)
        if not ok2:
            logger.info("auto_executor.skip_slippage id=%s reason=%s",
                         setup.get("setup_id"), reason2)
            notifier.send(notifier.card_skipped(st, reason2))
            continue
        # size from live instrument specs (per-symbol); skip if unsafe/zero
        entry_price = float(setup.get("entry_price"))
        qty_lots, qty_under, nominal = _size_for_symbol(client, bsym, last or entry_price)
        if qty_lots <= 0:
            logger.info("auto_executor.skip_sizing id=%s sym=%s (zero/guarded)",
                         setup.get("setup_id"), bsym)
            continue
        cl_ord = f"ae-{uuid.uuid4().hex[:18]}"
        side = str(setup.get("side", "long")).lower()  # phase-2: side-aware
        # Apply per-setup parameter override (backtest-optimal). Falls back
        # to setup_detector's per-signal values for setups that don't have
        # an entry in SETUP_OVERRIDES (e.g. long_multi_divergence — fixed
        # grid was -EV on n=62; trust the detector's pattern-geometry stops).
        override = SETUP_OVERRIDES.get(st)
        if override:
            sl_price, tp1_price, tp2_price = _sl_tp_prices(
                side, entry_price, override["sl_pct"],
                override["tp1_pct"], override["tp2_pct"])
            from datetime import timedelta as _td
            expires_at = (detected_at + _td(hours=override["hold_hours"])).isoformat(timespec="seconds")
            logger.info("auto_executor.using_override setup=%s side=%s sl=%.2f%% tp1=%.2f%% hold=%dh",
                         st, side, override["sl_pct"], override["tp1_pct"], override["hold_hours"])
        else:
            sl_price = float(setup.get("stop_price"))
            tp1_price = float(setup.get("tp1_price"))
            tp2_price = float(setup.get("tp2_price") or 0.0)
            expires_at = str(setup.get("expires_at", ""))
        try:
            if side == "short":
                order = client.place_limit_sell(bsym, qty_lots, entry_price,
                                                 cl_ord_id=cl_ord, post_only=True)
            else:
                order = client.place_limit_buy(bsym, qty_lots, entry_price,
                                                cl_ord_id=cl_ord, post_only=True)
        except BitMEXError as exc:
            notifier.send(notifier.card_error("place_limit_entry_failed", exc))
            logger.exception("auto_executor.place_limit_failed id=%s",
                              setup.get("setup_id"))
            break  # don't try more setups this tick
        pos = Position(
            setup_id=str(setup.get("setup_id", cl_ord)),
            setup_type=st,
            pair=pair,
            bitmex_symbol=bsym,
            side=side,
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            expires_at=expires_at,
            qty_lots=qty_lots,
            qty_btc=qty_under,           # underlying qty (BTC/ETH/XRP) per-symbol
            nominal_usd=nominal,
            cl_ord_id=cl_ord,
            entry_order_id=order.get("orderID"),
            status="placed",
        )
        state.open_positions.append(pos)
        notifier.send(notifier.card_placed(pos))
        logger.info("auto_executor.placed id=%s type=%s qty=%d entry=%.1f open_count=%d",
                     pos.setup_id, st, qty_lots, entry_price,
                     len(state.open_positions))
        # continue the loop — may take more setups up to MAX_PARALLEL
    return new_offset


# ─── Public loop ───────────────────────────────────────────────────
async def auto_executor_loop(stop_event: asyncio.Event,
                              interval_sec: float = TICK_INTERVAL_SEC) -> None:
    """Run forever (until stop_event) — one tick every interval_sec.

    Exceptions inside _tick are caught and logged; the loop never dies.
    """
    logger.info("auto_executor_loop.start interval=%ds symbol=%s setups=%s",
                 interval_sec, BITMEX_SYMBOL, list(gates.ALLOWED_SETUPS))
    try:
        client = BitMEXClient.from_env()
    except Exception:
        logger.exception("auto_executor.client_init_failed — loop will not run")
        return
    state = load_state()
    offset = load_offset()
    # First-run alignment: if there's no offset and no open position, fast-forward
    # to the current EOF of setups.jsonl so we don't react to stale setups from days ago.
    if offset == 0 and state.open_position is None and SETUPS_JSONL.exists():
        try:
            offset = SETUPS_JSONL.stat().st_size
            save_offset(offset)
            logger.info("auto_executor.first_run fastforward offset=%d", offset)
        except OSError:
            pass
    notifier.send(f"🤖 auto_executor STARTED  symbol={BITMEX_SYMBOL} "
                   f"size={LOTS_PER_TRADE}lots setups={list(gates.ALLOWED_SETUPS)}")

    while not stop_event.is_set():
        try:
            _refresh_balance_and_daily(state, client)
            _manage_placed(state, client)
            _manage_filled(state, client)
            offset = _try_open_new(state, client, offset)
            save_offset(offset)
            save_state(state)
        except Exception:
            logger.exception("auto_executor.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()),
                                    timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
    logger.info("auto_executor_loop.stop")
    notifier.send("🛑 auto_executor STOPPED")
