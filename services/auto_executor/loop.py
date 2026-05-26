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
ENTRY_TIMEOUT_MIN = 5            # if limit not filled after this, market fallback
LOT_SIZE = 100                   # BitMEX XBTUSDT lotSize
LOTS_PER_TRADE = 100             # 100 lots = 0.0001 BTC = ~$7.70 at $77k
BITMEX_SYMBOL = "XBTUSDT"        # UI: "BTCUSDT"; API: "XBTUSDT"

# Hybrid entry policy (2026-05-26): try post-only limit first, fall back
# to market if not filled within ENTRY_TIMEOUT_MIN. SL/TP are recalculated
# off the actual market fill, preserving the setup's planned R:R.
ENTRY_MODE_LIMIT = "limit"
ENTRY_MODE_MARKET_FALLBACK = "market_fallback"


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


def _est_pnl_usd_long(qty_btc: float, entry: float, exit_: float) -> float:
    """Linear PnL: (exit - entry) * qty_btc (USDT-margined linear contract)."""
    return (exit_ - entry) * qty_btc


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


def _market_fallback_enter(state: State, client: BitMEXClient,
                            pos: Position) -> None:
    """Limit didn't fill in time — place a market BUY for the same qty,
    pull the actual fill price, slide SL/TP relative to it. Sets status
    to 'filled' with entry_mode='market_fallback'.
    """
    notifier.send(notifier.card_market_fallback_start(pos))
    # 1) place market BUY (no execInst Close — we're opening, not flattening)
    market_cl_ord = f"mkt-{pos.cl_ord_id}"
    try:
        r = client._request(  # type: ignore[attr-defined]
            "POST", "/api/v1/order",
            body={
                "symbol": pos.bitmex_symbol,
                "side": "Buy",
                "orderQty": int(pos.qty_lots),
                "ordType": "Market",
                "clOrdID": market_cl_ord,
            },
        )
    except BitMEXError as exc:
        notifier.send(notifier.card_error("market_fallback_place_failed", exc))
        logger.exception("auto_executor.market_fallback_place_failed id=%s",
                          pos.setup_id)
        state.open_position = None
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
    """If the entry limit got filled, promote to filled.
    If timeout passes without fill → cancel + market-fallback (hybrid mode).
    """
    pos = state.open_position
    if pos is None or pos.status != "placed":
        return
    placed_at = _from_iso(pos.placed_at) or _now()
    timeout = placed_at.timestamp() + ENTRY_TIMEOUT_MIN * 60
    if pos.entry_order_id is None:
        logger.warning("auto_executor.placed_without_orderid id=%s — dropping",
                        pos.setup_id)
        state.open_position = None
        return
    try:
        order = client.get_order(pos.entry_order_id)
    except BitMEXError:
        logger.warning("auto_executor.get_order_failed id=%s — will retry",
                        pos.entry_order_id)
        return
    if order is None:
        logger.warning("auto_executor.order_not_found id=%s — clearing",
                        pos.entry_order_id)
        state.open_position = None
        return
    status = (order.get("ordStatus") or "").lower()
    if status == "filled":
        pos.status = "filled"
        pos.filled_at = _now().isoformat(timespec="seconds")
        pos.avg_entry_price = float(order.get("avgPx") or pos.entry_price)
        pos.entry_mode = ENTRY_MODE_LIMIT
        logger.info("auto_executor.filled_limit id=%s avg=%.1f",
                     pos.setup_id, pos.avg_entry_price)
        notifier.send(notifier.card_filled(pos))
        return
    if status in ("canceled", "cancelled", "rejected", "expired"):
        logger.info("auto_executor.entry_terminal_status id=%s status=%s",
                     pos.setup_id, status)
        state.open_position = None
        return
    # still working — if past the limit window, switch to market
    if _now().timestamp() >= timeout:
        logger.info("auto_executor.limit_timeout_market_fallback id=%s",
                     pos.setup_id)
        try:
            client.cancel_order(pos.entry_order_id)
        except BitMEXError:
            logger.warning("auto_executor.cancel_failed id=%s — proceeding to market",
                            pos.entry_order_id)
        _market_fallback_enter(state, client, pos)


def _manage_filled(state: State, client: BitMEXClient) -> None:
    """For an open long: check current price vs SL/TP1/EXPIRE. On trigger
    close at market, mark closed, record outcome, run kill-switch."""
    pos = state.open_position
    if pos is None or pos.status != "filled":
        return
    try:
        last = client.get_last_price(pos.bitmex_symbol)
    except BitMEXError:
        logger.warning("auto_executor.last_price_failed (non-fatal)")
        return
    if last <= 0:
        return
    reason: Optional[str] = None
    if last <= pos.sl_price:
        reason = "sl"
    elif last >= pos.tp1_price:
        reason = "tp1"
    elif _from_iso(pos.expires_at) and _now() >= _from_iso(pos.expires_at):
        reason = "expire"
    if reason is None:
        return
    # close at market
    try:
        client.place_market_exit_long(pos.bitmex_symbol, pos.qty_lots,
                                        cl_ord_id=f"exit-{pos.cl_ord_id}")
    except BitMEXError as exc:
        notifier.send(notifier.card_error("market_exit_failed", exc))
        logger.exception("auto_executor.market_exit_failed id=%s", pos.setup_id)
        return
    pos.status = "closed"
    pos.closed_at = _now().isoformat(timespec="seconds")
    pos.exit_reason = reason
    pos.avg_exit_price = last  # approximation; precise fill comes via position poll next tick
    entry_for_pnl = pos.avg_entry_price or pos.entry_price
    pos.realized_pnl_usd = _est_pnl_usd_long(pos.qty_btc, entry_for_pnl, last)
    append_outcome(pos)
    # Update killstate with this outcome
    gates.record_outcome_update_killstate(
        state.kill, setup_type=pos.setup_type,
        pnl_usd=float(pos.realized_pnl_usd or 0.0),
    )
    notifier.send(notifier.card_closed(pos))
    # check killswitch on outcomes file
    _maybe_freeze_setups(state)
    state.open_position = None


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
            by_setup.setdefault(rec.get("setup_type", "?"), []).append(float(pnl))
    except OSError:
        return
    newly = gates.evaluate_killswitch_per_setup(state.kill, outcomes_by_setup=by_setup)
    for st in newly:
        notifier.send(notifier.card_freeze(
            f"setup={st}", "7d WR < 50% (n≥5) — manual /unfreeze to resume",
        ))


def _try_open_new(state: State, client: BitMEXClient, offset: int) -> int:
    """Look for new setups since `offset` and act on the first allowed one.
    Returns new offset (advanced past every line seen, allowed or not)."""
    if state.open_position is not None:
        return offset  # busy — defer reading until free
    records, new_offset = _read_new_setups(offset)
    if not records:
        return new_offset
    for setup in records:
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
        # confirm slippage isn't already blown out
        try:
            last = client.get_last_price(BITMEX_SYMBOL)
        except BitMEXError:
            last = 0.0
        ok2, reason2 = gates.can_open(setup, state, current_price=last)
        if not ok2:
            logger.info("auto_executor.skip_slippage id=%s reason=%s",
                         setup.get("setup_id"), reason2)
            notifier.send(notifier.card_skipped(st, reason2))
            continue
        # place the order
        qty_lots = _calc_qty_lots()
        cl_ord = f"ae-{uuid.uuid4().hex[:18]}"
        entry_price = float(setup.get("entry_price"))
        try:
            order = client.place_limit_buy(BITMEX_SYMBOL, qty_lots, entry_price,
                                            cl_ord_id=cl_ord, post_only=True)
        except BitMEXError as exc:
            notifier.send(notifier.card_error("place_limit_buy_failed", exc))
            logger.exception("auto_executor.place_limit_failed id=%s",
                              setup.get("setup_id"))
            break  # don't try more setups this tick
        pos = Position(
            setup_id=str(setup.get("setup_id", cl_ord)),
            setup_type=st,
            pair=pair,
            bitmex_symbol=BITMEX_SYMBOL,
            side="long",
            entry_price=entry_price,
            sl_price=float(setup.get("stop_price")),
            tp1_price=float(setup.get("tp1_price")),
            tp2_price=float(setup.get("tp2_price") or 0.0),
            expires_at=str(setup.get("expires_at", "")),
            qty_lots=qty_lots,
            qty_btc=_lots_to_btc(qty_lots),
            nominal_usd=_lots_to_btc(qty_lots) * (last or entry_price),
            cl_ord_id=cl_ord,
            entry_order_id=order.get("orderID"),
            status="placed",
        )
        state.open_position = pos
        notifier.send(notifier.card_placed(pos))
        logger.info("auto_executor.placed id=%s type=%s qty=%d entry=%.1f",
                     pos.setup_id, st, qty_lots, entry_price)
        break  # only one position at a time
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
