"""Decision gates — pure functions, easy to unit-test.

Every gate returns (allow: bool, reason: str). Caller logs reason for
suppressed signals so we can audit later why a setup wasn't taken.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from services.auto_executor.state import KillState, Position, State

logger = logging.getLogger(__name__)

# ─── Tuning (mirrors what was agreed with the operator 2026-05-24) ───
ALLOWED_PAIRS = ("BTCUSDT",)
# 2026-05-30 REALITY-FILTER re-grade (docs/STRATEGIES/REALITY_FILTER_REGRADE.md,
# truth = setup_precision_outcomes.jsonl, NOT paper). Paper was systematically
# inflated (intrabar-touch TP + EXPIRE-in-profit). Honest net-of-cost survivors:
#   long_double_bottom +0.88%, long_dump_reversal +0.66%, long_pdl_bounce +0.62%.
# REMOVED long_multi_divergence (honest −21%, 54/57 TIMEOUT — paper "champion"
# was a timeout machine). REVERTED the 2026-05-29 SHORT enablement: short_div_bos
# / short_double_top were promoted on debunked paper PF; honest precision n=1 each,
# negative. SHORT code stays (built+tested) but GATED OFF until an honest short
# edge appears. Side-aware execution + kill-switch + paper_wr_gate still active.
ALLOWED_SETUPS = ("long_pdl_bounce", "long_dump_reversal", "long_double_bottom")
ALLOWED_SIDES = ("long",)
MAX_PARALLEL = 3   # backtest 2026-05-27: 3 = sweet spot (1 too few, 2 has cluster losses)

DAILY_LOSS_LIMIT_USD = -3.0       # freeze for the day at or below this
BALANCE_FLOOR_USD = 40.0          # kill if available margin drops below
CONSECUTIVE_LOSSES_FREEZE_N = 5   # 5 losses in a row → 24h freeze
CONSECUTIVE_FREEZE_HOURS = 24
KILLSWITCH_WR_THRESHOLD_PCT = 50.0
KILLSWITCH_MIN_N = 5

ENTRY_SLIPPAGE_PCT = 0.30         # 2026-05-25: only reject if setup.entry > market
                                   # by more than 0.30% (post-only would cross).
                                   # When market is ABOVE setup.entry, our limit
                                   # simply sits as a bid — that's the desired path.


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ─── Individual gates ──────────────────────────────────────────────
def gate_setup_type(setup_type: str) -> tuple[bool, str]:
    if setup_type in ALLOWED_SETUPS:
        return True, "ok"
    return False, f"setup_type_not_allowed:{setup_type}"


def gate_pair(pair: str) -> tuple[bool, str]:
    if pair in ALLOWED_PAIRS:
        return True, "ok"
    return False, f"pair_not_allowed:{pair}"


def gate_side(side: str) -> tuple[bool, str]:
    if side in ALLOWED_SIDES:
        return True, "ok"
    return False, f"side_not_allowed:{side}"


def gate_max_parallel(state: State) -> tuple[bool, str]:
    open_count = sum(1 for p in state.open_positions if p.is_open())
    if open_count >= MAX_PARALLEL:
        ids = ",".join(p.setup_id for p in state.open_positions if p.is_open())
        return False, f"max_parallel_{MAX_PARALLEL}_busy_with:{ids}"
    return True, "ok"


def gate_daily_loss(state: State) -> tuple[bool, str]:
    if state.kill.daily_pnl_usd <= DAILY_LOSS_LIMIT_USD:
        return False, (f"daily_loss_hit pnl={state.kill.daily_pnl_usd:.2f} "
                       f"<= limit={DAILY_LOSS_LIMIT_USD}")
    return True, "ok"


def gate_balance_floor(state: State) -> tuple[bool, str]:
    if state.kill.last_known_balance_usd <= 0:
        # not yet checked — allow for first iteration; the loop will refresh
        return True, "balance_unknown_yet"
    if state.kill.last_known_balance_usd < BALANCE_FLOOR_USD:
        return False, (f"balance_below_floor={state.kill.last_known_balance_usd:.2f} "
                       f"< {BALANCE_FLOOR_USD}")
    return True, "ok"


def gate_global_freeze(state: State, now: Optional[datetime] = None) -> tuple[bool, str]:
    now = now or _now()
    until = _from_iso(state.kill.freeze_until)
    if until and until > now:
        return False, f"global_freeze_until={until.isoformat()}"
    return True, "ok"


def gate_setup_freeze(state: State, setup_type: str) -> tuple[bool, str]:
    frozen_at = state.kill.setup_frozen.get(setup_type)
    if frozen_at:
        return False, f"setup_frozen_by_killswitch_at={frozen_at}"
    return True, "ok"


def gate_paper_wr(setup_type: str) -> tuple[bool, str]:
    """Reuse paper_wr_gate — same bucket key as setup_detector emitter."""
    try:
        from services.common.paper_wr_gate import should_emit
    except ImportError:
        return True, "paper_wr_gate_unavailable"
    try:
        ok, reason = should_emit("setup_detector", setup_type)
    except Exception:
        logger.exception("auto_executor.paper_wr_gate_failed")
        return True, "paper_wr_gate_errored"
    return ok, reason


def gate_entry_slippage(setup_entry: float, current_price: float) -> tuple[bool, str]:
    """Skip only the scenario where setup.entry is ABOVE current market by
    more than ENTRY_SLIPPAGE_PCT — in that case our post-only BUY limit
    would cross the spread and BitMEX would reject it with execInst error.

    The opposite case (entry BELOW market) is *fine*: the limit sits in
    the bid book as a resting maker order, earning rebate if filled.
    Entry timeout (30 min) and dedup take care of stale ones.

    Previous version had the inequality reversed — it rejected good
    'resting bid' scenarios and let bad 'crossing limit' through. Fixed
    2026-05-25 after first live observation.
    """
    if current_price <= 0:
        return True, "current_price_unknown"
    # diff > 0 means setup.entry is above market
    diff_pct = (setup_entry - current_price) / current_price * 100.0
    if diff_pct > ENTRY_SLIPPAGE_PCT:
        return False, (f"limit_would_cross entry={setup_entry:.1f} "
                       f"now={current_price:.1f} above_market_by={diff_pct:+.2f}%")
    return True, "ok"


# ─── Composite ─────────────────────────────────────────────────────
def can_open(setup: dict, state: State, *,
              current_price: Optional[float] = None,
              now: Optional[datetime] = None) -> tuple[bool, str]:
    """Run every gate in order. Returns (allow, reason)."""
    checks: list[tuple[bool, str]] = [
        gate_setup_type(str(setup.get("setup_type", ""))),
        gate_pair(str(setup.get("pair", ""))),
        gate_side(str(setup.get("side", "long")).lower()),  # ALLOWED_SIDES gates it
        gate_max_parallel(state),
        gate_daily_loss(state),
        gate_balance_floor(state),
        gate_global_freeze(state, now=now),
        gate_setup_freeze(state, str(setup.get("setup_type", ""))),
        gate_paper_wr(str(setup.get("setup_type", ""))),
    ]
    if current_price is not None:
        checks.append(gate_entry_slippage(
            float(setup.get("entry_price", 0.0)), current_price,
        ))
    for ok, reason in checks:
        if not ok:
            return False, reason
    return True, "ok"


# ─── Killswitch update ─────────────────────────────────────────────
def record_outcome_update_killstate(kill: KillState, *, setup_type: str,
                                      pnl_usd: float,
                                      now: Optional[datetime] = None) -> None:
    """Mutates `kill` after a closed trade.

    - rolls daily PnL
    - tracks consecutive_losses (reset on win, +1 on loss)
    - triggers 24h freeze when 5 losses in a row
    """
    now = now or _now()
    # daily roll
    today = now.date().isoformat()
    if kill.daily_pnl_date != today:
        kill.daily_pnl_usd = 0.0
        kill.daily_pnl_date = today
    kill.daily_pnl_usd += pnl_usd

    if pnl_usd > 0:
        kill.consecutive_losses = 0
    else:
        kill.consecutive_losses += 1
        if kill.consecutive_losses >= CONSECUTIVE_LOSSES_FREEZE_N:
            freeze_until = now + _hours(CONSECUTIVE_FREEZE_HOURS)
            kill.freeze_until = freeze_until.isoformat(timespec="seconds")
            logger.warning("auto_executor.consecutive_loss_freeze "
                            "n=%d until=%s", kill.consecutive_losses,
                            kill.freeze_until)


def evaluate_killswitch_per_setup(kill: KillState, *, outcomes_by_setup: dict,
                                    now: Optional[datetime] = None) -> list[str]:
    """7d kill-switch: for each setup_type, if last-7d WR < threshold at
    n >= MIN_N, mark frozen. Returns list of newly-frozen setup_types."""
    now = now or _now()
    newly: list[str] = []
    for setup_type, pnls in outcomes_by_setup.items():
        if setup_type in kill.setup_frozen:
            continue  # already frozen — manual unfreeze required
        if len(pnls) < KILLSWITCH_MIN_N:
            continue
        wins = sum(1 for p in pnls if p > 0)
        wr_pct = 100.0 * wins / len(pnls)
        if wr_pct < KILLSWITCH_WR_THRESHOLD_PCT:
            kill.setup_frozen[setup_type] = now.isoformat(timespec="seconds")
            newly.append(setup_type)
            logger.warning("auto_executor.killswitch_frozen setup=%s "
                            "wr_pct=%.1f n=%d", setup_type, wr_pct, len(pnls))
    return newly


def _hours(n: int):
    from datetime import timedelta
    return timedelta(hours=n)
