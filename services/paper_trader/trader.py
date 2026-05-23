"""Paper trader v0.1 — opens/closes simulated trades from setup signals.

Strategy:
  - Sizing: $10,000 notional fixed (per operator decision 2026-05-07)
  - Confidence filter: ≥60% (per operator)
  - Long setups (long_*) → buy at entry, exit at SL/TP1/TP2
  - Short setups (short_*) → sell at entry, exit at SL/TP1/TP2
  - TP1: 50% close. TP2: full close. SL: full close. Time stop: 24h.

Each event written to state/paper_trades.jsonl with full reasoning.
Telegram alerts for opens/exits at confidence ≥ 0.6.
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from services.paper_trader import journal
from services.paper_trader.cascade_filter import should_block_entry
from services.paper_trader.regime_filter import should_block_for_instability
from services.paper_trader.streak_guard import should_pause
from services.setup_detector.models import Setup, SetupType

logger = logging.getLogger(__name__)

PAPER_NOTIONAL_USD = 10_000.0
CONFIDENCE_THRESHOLD = 60.0  # %
TIME_STOP_HOURS = 24
# 2026-05-23 LMD audit: 16/60 closes were EXPIRE-profitable (median
# 22.8h held) → TIME_STOP fires before TP can be reached. Plan to bump
# only for ELITE tier (per elite_tiers) — needs tier-conditional logic
# in update_open_trades, not a global constant change. Kept at 24h for
# now to preserve test_time_stop_24h; tier-conditional follow-up.


def _setup_side(setup_type: SetupType) -> str:
    v = setup_type.value
    if v.startswith("long_"):
        return "long"
    if v.startswith("short_"):
        return "short"
    return "n/a"


def _format_basis(setup: Setup) -> str:
    """Compact reason string from setup.basis."""
    if not setup.basis:
        return "n/a"
    parts = []
    for b in setup.basis[:6]:  # cap to 6 items
        parts.append(f"{b.label}={b.value}")
    return ", ".join(parts)


def open_paper_trade(setup: Setup) -> Optional[dict]:
    """Decide if we should open a paper trade for this setup; if yes, log it.

    Returns the OPEN event dict if opened, None if filtered out.
    """
    side = _setup_side(setup.setup_type)
    if side not in ("long", "short"):
        return None  # grid/defensive setups not paper-traded
    if setup.confidence_pct < CONFIDENCE_THRESHOLD:
        return None
    if setup.entry_price is None or setup.stop_price is None:
        return None
    if setup.tp1_price is None and setup.tp2_price is None:
        return None

    pair = getattr(setup, "pair", "BTCUSDT") or "BTCUSDT"

    paused, streak, pause_reason = should_pause(pair=pair)
    if paused:
        logger.info(
            "paper_trader.entry_blocked_by_streak pair=%s type=%s %s",
            pair, setup.setup_type.value, pause_reason,
        )
        return None

    blocked, recent_vol = should_block_entry(side, pair=pair)
    if blocked:
        logger.info(
            "paper_trader.entry_blocked_by_cascade side=%s pair=%s type=%s recent_liq_btc=%.1f",
            side, pair, setup.setup_type.value, recent_vol,
        )
        return None

    regime_blocked, low_stab = should_block_for_instability()
    if regime_blocked:
        logger.info(
            "paper_trader.entry_blocked_by_regime type=%s stability=%.2f",
            setup.setup_type.value, low_stab if low_stab is not None else 0.0,
        )
        return None

    entry = float(setup.entry_price)
    if entry <= 0:
        return None
    # Elite-tier sizing: ELITE/STRONG buckets get 1.3-2x notional, WEAK
    # buckets get 0.25x. Defaults to 1.0 when no rule matches.
    from services.setup_detector.elite_tiers import classify_setup
    _tier = classify_setup(setup.setup_type.value, setup.regime_label,
                           setup.session_label,
                           getattr(setup, "pair", "BTCUSDT"))
    size_usd = round(PAPER_NOTIONAL_USD * _tier.size_mult, 2)
    size_btc = round(size_usd / entry, 6)
    now = datetime.now(timezone.utc)
    trade_id = f"pt-{now.strftime('%Y-%m-%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    record = {
        "ts": now.isoformat(),
        "trade_id": trade_id,
        "action": "OPEN",
        "side": side,
        "setup_type": setup.setup_type.value,
        "setup_id": setup.setup_id,
        "pair": getattr(setup, "pair", "BTCUSDT"),  # multi-symbol support 2026-05-08
        "entry": entry,
        "size_usd": size_usd,
        "size_btc": size_btc,
        "elite_tier": _tier.tier,
        "elite_rule_id": _tier.rule_id,
        "sl": float(setup.stop_price),
        "tp1": float(setup.tp1_price) if setup.tp1_price else None,
        "tp2": float(setup.tp2_price) if setup.tp2_price else None,
        "rr_planned": setup.risk_reward,
        "regime_at_entry": setup.regime_label,
        "session_at_entry": setup.session_label,
        "confidence_pct": setup.confidence_pct,
        "strength": setup.strength,
        "expires_at": setup.expires_at.isoformat(),
        "time_stop_at": (now + timedelta(hours=TIME_STOP_HOURS)).isoformat(),
        "reason": _format_basis(setup),
    }
    journal.append_event(record)
    logger.info(
        "paper_trader.opened trade_id=%s side=%s type=%s entry=%.2f conf=%.1f",
        trade_id, side, setup.setup_type.value, entry, setup.confidence_pct,
    )
    return record


def open_paper_trade_from_proposal(proposal) -> Optional[dict]:
    """Open a paper trade from an operator-confirmed Proposal.

    Mirrors open_paper_trade() but with operator_confirmed=True flag. The
    confidence threshold is bypassed because the operator has explicitly
    approved the trade after seeing the proposal card.

    Used by the Telegram /confirm <token> handler.
    """
    side = proposal.side
    if side not in ("long", "short"):
        return None
    entry = float(proposal.entry)
    if entry <= 0 or proposal.sl <= 0:
        return None
    size_btc = round(PAPER_NOTIONAL_USD / entry, 6)
    now = datetime.now(timezone.utc)
    trade_id = f"pt-{now.strftime('%Y-%m-%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    record = {
        "ts": now.isoformat(),
        "trade_id": trade_id,
        "action": "OPEN",
        "side": side,
        "setup_type": proposal.setup_type,
        "setup_id": proposal.setup_id or trade_id,
        "entry": entry,
        "size_usd": PAPER_NOTIONAL_USD,
        "size_btc": size_btc,
        "sl": float(proposal.sl),
        "tp1": float(proposal.tp1) if proposal.tp1 else None,
        "tp2": float(proposal.tp2) if proposal.tp2 else None,
        "rr_planned": proposal.rr,
        "confidence_pct": proposal.confidence,
        "strength": proposal.strength,
        "expires_at": (now + timedelta(hours=TIME_STOP_HOURS)).isoformat(),
        "time_stop_at": (now + timedelta(hours=TIME_STOP_HOURS)).isoformat(),
        "reason": f"Operator-confirmed proposal token={proposal.token}",
        "operator_confirmed": True,
        "proposal_token": proposal.token,
        "decided_by": proposal.decided_by,
    }
    journal.append_event(record)
    logger.info(
        "paper_trader.opened_from_proposal trade_id=%s token=%s type=%s entry=%.2f",
        trade_id, proposal.token, proposal.setup_type, entry,
    )
    return record


def _compute_exit_pnl(open_record: dict, exit_price: float) -> tuple[float, float]:
    """Return (realized_pnl_usd, rr_realized) for a paper trade close.

    Long: pnl = (exit - entry) × size_btc
    Short: pnl = (entry - exit) × size_btc
    rr_realized = pnl / max_loss_at_sl (positive ratio)
    """
    side = open_record["side"]
    entry = float(open_record["entry"])
    sl = float(open_record["sl"])
    size_btc = float(open_record["size_btc"])
    if side == "long":
        pnl = (exit_price - entry) * size_btc
        max_loss = abs(entry - sl) * size_btc
    else:
        pnl = (entry - exit_price) * size_btc
        max_loss = abs(sl - entry) * size_btc
    rr = pnl / max_loss if max_loss > 0 else 0.0
    return round(pnl, 2), round(rr, 2)


def _hours_in_trade(open_record: dict, now: datetime) -> float:
    open_ts = datetime.fromisoformat(open_record["ts"])
    if open_ts.tzinfo is None:
        open_ts = open_ts.replace(tzinfo=timezone.utc)
    return round((now - open_ts).total_seconds() / 3600, 2)


def update_open_trades(
    current_price: float | dict[str, float],
    *,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Check all open trades; close any that hit SL/TP/time-stop.

    `current_price` is either a single float (legacy: applied to all open
    trades regardless of pair — for BTCUSDT-only deployments) OR a
    dict[symbol -> price] for multi-symbol deployments. When dict, each
    trade is matched against price for its `pair` field; trades with a
    pair missing from the dict are skipped (no false TP/SL).

    Returns list of close events emitted (for Telegram notification).
    """
    now = now or datetime.now(timezone.utc)
    opens = journal.open_trades()
    closed_events: list[dict] = []
    is_multi = isinstance(current_price, dict)

    for trade in opens:
        # Resolve the price to use for this trade.
        trade_pair = trade.get("pair") or "BTCUSDT"
        if is_multi:
            trade_price = current_price.get(trade_pair)
            if trade_price is None or trade_price <= 0:
                continue   # no price for this pair this tick — skip cleanly
        else:
            trade_price = float(current_price)

        # 2026-05-11 fix: P-15 setups are managed by their own state machine
        # (see services/setup_detector/p15_rolling.py). They emit OPEN/HARVEST/
        # REENTRY/CLOSE events without a fixed SL/TP — exit decisions come
        # from R%/K%/dd_cap logic, not price levels. So they don't carry
        # sl/tp1/tp2 in paper_trades.jsonl. Skip them in this generic loop
        # — they don't need SL/TP/timestop monitoring here.
        # Was causing KeyError: 'sl' every loop tick.
        if (trade.get("strategy") == "p15"
                or str(trade.get("setup_type", "")).startswith("p15_")):
            continue
        # Other defensive: legacy/partial trade record without sl entirely.
        if "sl" not in trade:
            continue

        side = trade["side"]
        entry = float(trade["entry"])
        sl = float(trade["sl"])
        tp1 = trade.get("tp1")
        tp2 = trade.get("tp2")
        time_stop = datetime.fromisoformat(trade["time_stop_at"])
        if time_stop.tzinfo is None:
            time_stop = time_stop.replace(tzinfo=timezone.utc)

        action = None
        exit_price = None

        # Check SL hit (priority — risk first)
        if side == "long" and trade_price <= sl:
            action, exit_price = "SL", sl
        elif side == "short" and trade_price >= sl:
            action, exit_price = "SL", sl
        # Check TP2 (full close)
        elif side == "long" and tp2 is not None and trade_price >= tp2:
            action, exit_price = "TP2", tp2
        elif side == "short" and tp2 is not None and trade_price <= tp2:
            action, exit_price = "TP2", tp2
        # Check TP1 (partial close — but for v0.1 we treat as full close to keep accounting simple)
        elif side == "long" and tp1 is not None and trade_price >= tp1:
            action, exit_price = "TP1", tp1
        elif side == "short" and tp1 is not None and trade_price <= tp1:
            action, exit_price = "TP1", tp1
        # Time stop
        elif now >= time_stop:
            action, exit_price = "EXPIRE", trade_price

        if action is None:
            continue

        pnl, rr = _compute_exit_pnl(trade, exit_price)
        event = {
            "ts": now.isoformat(),
            "trade_id": trade["trade_id"],
            "action": action,
            "side": side,
            "setup_type": trade["setup_type"],
            "exit_price": exit_price,
            "realized_pnl_usd": pnl,
            "rr_realized": rr,
            "hours_in_trade": _hours_in_trade(trade, now),
        }
        journal.append_event(event)
        closed_events.append(event)
        logger.info(
            "paper_trader.closed trade_id=%s action=%s pnl=%.2f rr=%.2f",
            trade["trade_id"], action, pnl, rr,
        )

    return closed_events


def daily_summary(*, days_back: int = 1) -> dict:
    """Aggregate stats over last N days. Returns dict for Telegram daily message."""
    events = journal.read_all()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    recent = []
    for e in events:
        try:
            ts = datetime.fromisoformat(e["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                recent.append(e)
        except (KeyError, ValueError):
            continue

    opens = [e for e in recent if e.get("action") == "OPEN"]
    closes = [e for e in recent if e.get("action") in ("TP1", "TP2", "SL", "EXPIRE")]
    wins = [e for e in closes if (e.get("realized_pnl_usd") or 0) > 0]
    losses = [e for e in closes if (e.get("realized_pnl_usd") or 0) <= 0]

    net_pnl = sum(e.get("realized_pnl_usd") or 0 for e in closes)
    rr_values = [e.get("rr_realized") for e in closes if e.get("rr_realized") is not None]
    avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0.0

    by_type = Counter(e["setup_type"] for e in opens)

    # Per-setup-type performance: closes only (where we have realized_pnl).
    by_type_perf: dict[str, dict] = {}
    for stype in {e.get("setup_type") for e in closes if e.get("setup_type")}:
        type_closes = [e for e in closes if e.get("setup_type") == stype]
        type_wins = [e for e in type_closes if (e.get("realized_pnl_usd") or 0) > 0]
        type_losses = [e for e in type_closes if (e.get("realized_pnl_usd") or 0) <= 0]
        type_net = sum(e.get("realized_pnl_usd") or 0 for e in type_closes)
        type_rrs = [e.get("rr_realized") for e in type_closes if e.get("rr_realized") is not None]
        gross_win = sum(e.get("realized_pnl_usd") or 0 for e in type_wins)
        gross_loss = -sum(e.get("realized_pnl_usd") or 0 for e in type_losses)
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        by_type_perf[stype] = {
            "n_closes": len(type_closes),
            "n_wins": len(type_wins),
            "n_losses": len(type_losses),
            "net_pnl_usd": round(type_net, 2),
            "win_rate_pct": round(100 * len(type_wins) / max(1, len(type_closes)), 1),
            "avg_rr": round(sum(type_rrs) / len(type_rrs), 2) if type_rrs else 0.0,
            "pf": pf,
        }

    return {
        "days_back": days_back,
        "n_opens": len(opens),
        "n_closes": len(closes),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "net_pnl_usd": round(net_pnl, 2),
        "avg_rr": avg_rr,
        "win_rate_pct": round(100 * len(wins) / max(1, len(closes)), 1),
        "by_setup_type": dict(by_type),
        "by_setup_type_perf": by_type_perf,
    }
