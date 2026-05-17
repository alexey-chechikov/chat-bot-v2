"""Volume-farm grid backtest — LINEAR contract version (ETHUSDT / XRPUSDT).

Fork of scripts/volume_farm_grid_backtest.py with proper linear-contract math
for ETH/XRP. Key differences from inverse (XBTUSD):

  - Position math: `pos_native` in units of base asset (ETH, XRP, etc.)
  - PnL formula: `pnl_usd = qty_native * (exit - entry) * sign_old`
                 (NOT inverse `qty_usd * (1/entry - 1/exit)`)
  - Fees: linear BitMEX rates — maker rebate −0.02% RT, taker 0.075%
  - Inventory cap: in USD notional (`inventory_cap_usd`), converted on first bar

Inherits structure from the inverse version but with a clean per-contract
formula tree. Allows direct apples-to-apples comparison.

Usage:
    python scripts/volume_farm_grid_backtest_linear.py --symbol ETHUSDT
    python scripts/volume_farm_grid_backtest_linear.py --symbol XRPUSDT \\
        --range-pct 0.6 --levels 120 --size 1000 --cap-usd 7800
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "backtests" / "frozen"

# BitMEX linear (USDT-margined) Tier 1 fees
MAKER_BP = -2.0   # rebate (credit)
TAKER_BP = 7.5


@dataclass
class Params:
    symbol: str = "ETHUSDT"
    capital_usd: float = 15_000.0
    grid_range_pct: float = 0.6
    grid_levels: int = 120
    order_size_usd: float = 1000.0
    inventory_cap_usd: float = 7_800.0
    reanchor_drift_pct: float = 0.3
    reanchor_interval_min: int = 30
    hard_stop_unrealized_usd: float = -2_000.0


@dataclass
class State:
    anchor: float = 0.0
    last_reanchor_min: int = 0
    pos_native: float = 0.0
    avg_entry: float = 0.0
    cash_usd: float = 0.0
    rebates_usd: float = 0.0
    volume_usd: float = 0.0
    fills: int = 0
    halted: bool = False
    daily: list = field(default_factory=list)
    inventory_cap_native: float = 0.0


def _fee_usd(notional: float) -> float:
    return notional * MAKER_BP / 10000.0


def _unrealized_usd(state: State, mark: float) -> float:
    if state.pos_native == 0:
        return 0.0
    sign = 1 if state.pos_native > 0 else -1
    return abs(state.pos_native) * (mark - state.avg_entry) * sign


def _close_all_taker(state: State, mark: float) -> None:
    if state.pos_native == 0:
        return
    notional = abs(state.pos_native) * mark
    sign_old = 1 if state.pos_native > 0 else -1
    realized = abs(state.pos_native) * (mark - state.avg_entry) * sign_old
    taker_fee = notional * TAKER_BP / 10000.0
    state.cash_usd += realized - taker_fee
    state.pos_native = 0.0
    state.avg_entry = 0.0


def _step_fill(state: State, p: Params, side: str, level: float) -> None:
    qty_native = p.order_size_usd / level
    if side == "buy" and state.pos_native >= state.inventory_cap_native:
        return
    if side == "sell" and state.pos_native <= -state.inventory_cap_native:
        return

    signed_qty = qty_native if side == "buy" else -qty_native
    new_pos = state.pos_native + signed_qty

    if (state.pos_native == 0
            or (state.pos_native > 0 and signed_qty > 0)
            or (state.pos_native < 0 and signed_qty < 0)):
        # opening or adding
        notional_old = state.avg_entry * abs(state.pos_native)
        notional_new = level * abs(signed_qty)
        if abs(new_pos) > 0:
            state.avg_entry = (notional_old + notional_new) / abs(new_pos)
    else:
        # reducing / flipping
        closed_qty = min(abs(state.pos_native), abs(signed_qty))
        sign_old = 1 if state.pos_native > 0 else -1
        realized = closed_qty * (level - state.avg_entry) * sign_old
        state.cash_usd += realized
        if abs(signed_qty) > abs(state.pos_native):
            state.avg_entry = level

    state.pos_native = new_pos
    if abs(state.pos_native) < 1e-12:
        state.pos_native = 0.0
        state.avg_entry = 0.0
    state.fills += 1
    state.volume_usd += p.order_size_usd
    state.rebates_usd -= _fee_usd(p.order_size_usd)


def run(df: pd.DataFrame, p: Params) -> dict:
    s = State()
    first_close = float(df.iloc[0]["close"])
    s.anchor = first_close
    s.inventory_cap_native = p.inventory_cap_usd / first_close
    s.last_reanchor_min = 0

    half = p.grid_levels // 2
    step_pct = p.grid_range_pct / half
    last_day = None
    d_start = {"cash": 0.0, "vol": 0.0, "rebates": 0.0, "fills": 0}

    for i, row in enumerate(df.itertuples(index=False)):
        ts = row.ts
        h, l, c = float(row.high), float(row.low), float(row.close)
        mid = c

        # day boundary
        day = ts.date()
        if last_day is None:
            last_day = day
            d_start = {"cash": s.cash_usd, "vol": s.volume_usd,
                       "rebates": s.rebates_usd, "fills": s.fills}
        if day != last_day:
            unr = _unrealized_usd(s, mid)
            s.daily.append({
                "date": last_day,
                "volume_usd": s.volume_usd - d_start["vol"],
                "rebates_usd": s.rebates_usd - d_start["rebates"],
                "realized_usd": s.cash_usd - d_start["cash"],
                "fills": s.fills - d_start["fills"],
                "pos_native_eod": s.pos_native,
                "unrealized_usd_eod": unr,
            })
            last_day = day
            d_start = {"cash": s.cash_usd, "vol": s.volume_usd,
                       "rebates": s.rebates_usd, "fills": s.fills}

        # Hard stop
        unr_now = _unrealized_usd(s, mid)
        if not s.halted and unr_now < p.hard_stop_unrealized_usd:
            _close_all_taker(s, mid)
            s.halted = True
            continue
        if s.halted:
            if (i - s.last_reanchor_min) > 60:
                s.halted = False
                s.anchor = mid
                s.last_reanchor_min = i
            else:
                continue

        # Reanchor
        drift = abs(mid - s.anchor) / s.anchor * 100
        if drift > p.reanchor_drift_pct or (i - s.last_reanchor_min) >= p.reanchor_interval_min:
            s.anchor = mid
            s.last_reanchor_min = i

        # Grid levels
        for k in range(1, half + 1):
            buy_lvl = s.anchor * (1 - k * step_pct / 100.0)
            if l <= buy_lvl <= s.anchor:
                _step_fill(s, p, "buy", buy_lvl)
            sell_lvl = s.anchor * (1 + k * step_pct / 100.0)
            if s.anchor <= sell_lvl <= h:
                _step_fill(s, p, "sell", sell_lvl)

    final_mid = float(df.iloc[-1]["close"])
    unr_final = _unrealized_usd(s, final_mid)
    s.daily.append({
        "date": last_day,
        "volume_usd": s.volume_usd - d_start["vol"],
        "rebates_usd": s.rebates_usd - d_start["rebates"],
        "realized_usd": s.cash_usd - d_start["cash"],
        "fills": s.fills - d_start["fills"],
        "pos_native_eod": s.pos_native,
        "unrealized_usd_eod": unr_final,
    })

    days = pd.DataFrame(s.daily)
    days["net_usd"] = (days["rebates_usd"] + days["realized_usd"]
                       + days["unrealized_usd_eod"].diff().fillna(days["unrealized_usd_eod"]))
    return {
        "params": vars(p),
        "fee_struct": {"maker_bp": MAKER_BP, "taker_bp": TAKER_BP, "label": "linear"},
        "total_days": len(days),
        "total_volume_usd": float(days.volume_usd.sum()),
        "total_rebates_usd": float(days.rebates_usd.sum()),
        "total_realized_usd": float(days.realized_usd.sum()),
        "total_unrealized_eod_usd": float(unr_final),
        "total_net_usd": float(days.rebates_usd.sum() + days.realized_usd.sum() + unr_final),
        "avg_daily_volume_usd": float(days.volume_usd.mean()),
        "median_daily_volume_usd": float(days.volume_usd.median()),
        "avg_daily_net_usd": float(days.net_usd.mean()),
        "median_daily_net_usd": float(days.net_usd.median()),
        "best_day_net": float(days.net_usd.max()),
        "worst_day_net": float(days.net_usd.min()),
        "days_neg_net": int((days.net_usd < 0).sum()),
        "days_pos_net": int((days.net_usd > 0).sum()),
        "max_drawdown_in_run_usd": float(
            (days.net_usd.cumsum() - days.net_usd.cumsum().cummax()).min()
        ),
        "days_df": days,
    }


def load_price(symbol: str) -> pd.DataFrame:
    csv = DATA_DIR / f"{symbol}_1m_2y.csv"
    df = pd.read_csv(csv, usecols=["ts", "open", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="ETHUSDT", choices=["ETHUSDT", "XRPUSDT"])
    ap.add_argument("--range-pct", type=float, default=0.6)
    ap.add_argument("--levels", type=int, default=120)
    ap.add_argument("--size", type=float, default=1000.0)
    ap.add_argument("--cap-usd", type=float, default=7800.0)
    args = ap.parse_args()

    df = load_price(args.symbol)
    p = Params(
        symbol=args.symbol,
        grid_range_pct=args.range_pct,
        grid_levels=args.levels,
        order_size_usd=args.size,
        inventory_cap_usd=args.cap_usd,
    )
    print(f"=== {args.symbol} LINEAR grid backtest ===")
    print(f"  bars: {len(df):,}  {df.ts.iloc[0]} → {df.ts.iloc[-1]}")
    print(f"  params: range={p.grid_range_pct}%  levels={p.grid_levels}  "
          f"size=${p.order_size_usd}  cap=${p.inventory_cap_usd}")
    r = run(df, p)
    print(f"\n  total days:                 {r['total_days']:,}")
    print(f"  total volume:               ${r['total_volume_usd']:>14,.0f}")
    print(f"  total rebates:              ${r['total_rebates_usd']:>+14,.0f}")
    print(f"  total realized:             ${r['total_realized_usd']:>+14,.0f}")
    print(f"  final unrealized:           ${r['total_unrealized_eod_usd']:>+14,.0f}")
    print(f"  TOTAL NET:                  ${r['total_net_usd']:>+14,.0f}")
    print(f"  avg daily volume:           ${r['avg_daily_volume_usd']:>+14,.0f}")
    print(f"  avg daily net:              ${r['avg_daily_net_usd']:>+14,.2f}")
    print(f"  median daily net:           ${r['median_daily_net_usd']:>+14,.2f}")
    print(f"  best/worst day:             ${r['best_day_net']:>+14,.0f}  /  ${r['worst_day_net']:>+14,.0f}")
    print(f"  days +/-:                   {r['days_pos_net']:>6} / {r['days_neg_net']:>6}")
    print(f"  max DD cum net:             ${r['max_drawdown_in_run_usd']:>+14,.0f}")


if __name__ == "__main__":
    main()
