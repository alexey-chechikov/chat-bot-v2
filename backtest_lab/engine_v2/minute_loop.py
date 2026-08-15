"""Minute-resolution GinArea backtest loop."""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .bot import GinareaBot, OHLCBar
from .portfolio import Portfolio, PortfolioSnapshot

if TYPE_CHECKING:
    from .policies import Policy
    from .regime_detector import RegimeDetector

log = logging.getLogger(__name__)


@dataclass
class BarSnapshot:
    bar_idx: int
    ts: str
    close: float
    portfolio: PortfolioSnapshot
    # bot_id -> (position_size, avg_entry, unrealized_pnl_raw)
    bot_states: dict[str, tuple[float, float, float]]


@dataclass
class BacktestResult:
    initial_balance: float
    final_equity: float
    final_wallet: float
    max_drawdown: float
    total_realized_pnl_usd: float
    total_entries: int
    total_exits: int
    liquidated: bool
    bars_run: int
    bar_snapshots: list[BarSnapshot] = field(default_factory=list)
    boundary_changes: int = 0  # total RAISE_BORDER_TOP + LOWER_BORDER_BOTTOM events


def load_ohlcv(
    path: Path | str,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> list[OHLCBar]:
    """
    Load 1m OHLCV from btcusdt_1m_2y.csv.
    Columns: Date,Open,High,Low,Close,Volume
    Timestamps: '2024-04-20 15:23:00+00:00'

    start_ts / end_ts: ISO string prefix — rows where ts < start_ts are skipped,
    rows where ts > end_ts stop iteration.
    """
    bars: list[OHLCBar] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row["Date"]
            if start_ts and ts < start_ts:
                continue
            if end_ts and ts > end_ts:
                break
            bars.append(OHLCBar(
                ts=ts,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume") or 0),
            ))
    return bars


def _apply_action(bot: GinareaBot, action: "Action") -> bool:  # noqa: F821
    """Apply action to bot. Returns True if a boundary was modified."""
    from .policies import ActionType
    if action.type == ActionType.STOP_BOT:
        bot.is_active = False
        return False
    elif action.type == ActionType.RESUME_BOT:
        bot.is_active = True
        if bot.position_size() == 0.0 and bot.out_stop_group is None:
            bot.is_indicator_passed = False
            bot.last_in_price = None
        return False
    elif action.type == ActionType.RAISE_BORDER_TOP:
        log.debug(
            "Bot %s: raise boundaries_upper %.2f -> %.2f",
            bot.cfg.bot_id, bot.cfg.boundaries_upper, action.value,
        )
        bot.cfg.boundaries_upper = action.value
        return True
    elif action.type == ActionType.LOWER_BORDER_BOTTOM:
        log.debug(
            "Bot %s: lower boundaries_lower %.2f -> %.2f",
            bot.cfg.bot_id, bot.cfg.boundaries_lower, action.value,
        )
        bot.cfg.boundaries_lower = action.value
        return True
    return False


def run_backtest(
    bots: list[GinareaBot],
    bars: list[OHLCBar],
    initial_balance_usd: float,
    min_margin_ratio: float = 0.0055,
    snapshot_every: int = 1,
    policy: "Policy | None" = None,
    detector: "RegimeDetector | None" = None,
) -> BacktestResult:
    """
    Run minute-resolution backtest on pre-loaded bars.

    snapshot_every=1  → record BarSnapshot after every bar (needed for validation).
    snapshot_every=0  → no snapshots (faster canonical runs).
    """
    portfolio = Portfolio(initial_balance_usd, min_margin_ratio)
    bar_snapshots: list[BarSnapshot] = []
    bars_run = 0
    _use_policy = policy is not None and detector is not None
    _local_high: float = 0.0
    _local_low: float = float("inf")
    _boundary_changes: int = 0

    for bar_idx, bar in enumerate(bars):
        if _use_policy:
            from .regime_detector import Regime
            regime = detector.classify(bars, bar_idx)  # type: ignore[union-attr]

            if regime in (Regime.STRONG_UP, Regime.CRITICAL_UP):
                if bar.high > _local_high:
                    _local_high = bar.high
            else:
                _local_high = 0.0

            if regime in (Regime.STRONG_DOWN, Regime.CRITICAL_DOWN):
                if bar.low < _local_low:
                    _local_low = bar.low
            else:
                _local_low = float("inf")

            policy.pre_bar(bar, bar_idx)  # type: ignore[union-attr]

            for bot in bots:
                for action in policy.on_bar(bot, regime, bar, _local_high, _local_low):  # type: ignore[union-attr]
                    if _apply_action(bot, action):
                        _boundary_changes += 1

        for bot in bots:
            bot.step(bar, bar_idx)
        bars_run += 1

        pf_snap = portfolio.snapshot(bots, bar.close)

        if snapshot_every > 0 and bar_idx % snapshot_every == 0:
            bot_states: dict[str, tuple[float, float, float]] = {}
            for bot in bots:
                bot_states[bot.cfg.bot_id] = (
                    bot.position_size(),
                    bot.avg_entry(),
                    bot.unrealized_pnl(bar.close),
                )
            bar_snapshots.append(BarSnapshot(
                bar_idx=bar_idx,
                ts=bar.ts,
                close=bar.close,
                portfolio=pf_snap,
                bot_states=bot_states,
            ))

        if pf_snap.liquidated:
            log.warning("Portfolio liquidated at bar %d ts=%s price=%.2f", bar_idx, bar.ts, bar.close)
            break

    if bars_run == 0:
        return BacktestResult(
            initial_balance=initial_balance_usd,
            final_equity=initial_balance_usd,
            final_wallet=initial_balance_usd,
            max_drawdown=0.0,
            total_realized_pnl_usd=0.0,
            total_entries=0,
            total_exits=0,
            liquidated=False,
            bars_run=0,
            bar_snapshots=[],
            boundary_changes=0,
        )

    final_snap = portfolio.snapshot(bots, bars[bars_run - 1].close)

    return BacktestResult(
        initial_balance=initial_balance_usd,
        final_equity=final_snap.equity_usd,
        final_wallet=final_snap.wallet_balance_usd,
        max_drawdown=final_snap.max_drawdown,
        total_realized_pnl_usd=final_snap.realized_pnl_usd,
        total_entries=sum(b.in_count for b in bots),
        total_exits=sum(b.out_count for b in bots),
        liquidated=final_snap.liquidated,
        bars_run=bars_run,
        bar_snapshots=bar_snapshots,
        boundary_changes=_boundary_changes,
    )
