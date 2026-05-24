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
ALLOWED_SETUPS = ("long_pdl_bounce", "long_multi_divergence")
ALLOWED_SIDES = ("long",)

DAILY_LOSS_LIMIT_USD = -3.0       # freeze for the day at or below this
BALANCE_FLOOR_USD = 40.0          # kill if available margin drops below
CONSECUTIVE_LOSSES_FREEZE_N = 5   # 5 losses in a row → 24h freeze
CONSECUTIVE_FREEZE_HOURS = 24
KILLSWITCH_WR_THRESHOLD_PCT = 50.0
KILLSWITCH_MIN_N = 5

ENTRY_SLIPPAGE_PCT = 0.10         # accept entry up to 0.10% above setup's entry_price


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
    if state.open_position is not None and state.open_position.is_open():
        return False, f"max_parallel_1_busy_with:{state.open_position.setup_id}"
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
    """We post-only buy at setup's entry_price. If market already moved
    above entry_price by more than ENTRY_SLIPPAGE_PCT, the limit will
    just sit unfilled — skip with a clear reason."""
    if current_price <= 0:
        return True, "current_price_unknown"
    diff_pct = (current_price - setup_entry) / setup_entry * 100.0
    if diff_pct > ENTRY_SLIPPAGE_PCT:
        return False, (f"slippage_too_far entry={setup_entry:.1f} "
                       f"now={current_price:.1f} diff={diff_pct:+.2f}%")
    return True, "ok"


# ─── Composite ─────────────────────────────────────────────────────
def can_open(setup: dict, state: State, *,
              current_price: Optional[float] = None,
              now: Optional[datetime] = None) -> tuple[bool, str]:
    """Run every gate in order. Returns (allow, reason)."""
    checks: list[tuple[bool, str]] = [
        gate_setup_type(str(setup.get("setup_type", ""))),
        gate_pair(str(setup.get("pair", ""))),
        gate_side("long"),  # we only do long setups
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
