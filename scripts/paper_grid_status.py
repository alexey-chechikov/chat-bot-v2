"""Paper grid live status — visibility into ETH/XRP paper grids without waiting
for the daily aggregate to be written.

Reads:
  state/paper_grid_<symbol>_state.json     — current running state
  state/paper_grid_<symbol>.jsonl          — past daily aggregates (if any)

Shows:
  - Current position + unrealized
  - Today running PnL (cash + rebates + unrealized)
  - Hourly fill rate / volume rate
  - Projection to end-of-day net at current rate
  - Comparison vs sweet-spot expectation ($2200 ETH / $5500 XRP per day)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"

SYMBOLS = ["ETHUSDT", "XRPUSDT"]
EXPECTED_DAILY_NET = {"ETHUSDT": 2245, "XRPUSDT": 5497}  # sweet-spot sweep


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _fetch_mid(symbol: str) -> float | None:
    """Latest mid from deriv_live.json."""
    d = _read_json(STATE_DIR / "deriv_live.json")
    if not d:
        return None
    try:
        return float(d.get(symbol, {}).get("mark_price") or 0) or None
    except (TypeError, ValueError):
        return None


def _report_symbol(symbol: str) -> str:
    state = _read_json(STATE_DIR / f"paper_grid_{symbol}_state.json")
    history = _read_jsonl(STATE_DIR / f"paper_grid_{symbol}.jsonl")
    if not state:
        return f"\n=== {symbol} ===\n  state not found (бот не стартовал?)"

    mid = _fetch_mid(symbol) or float(state.get("anchor") or 0)
    pos = float(state.get("pos_native") or 0)
    avg_entry = float(state.get("avg_entry") or 0)
    sign = 1 if pos > 0 else -1 if pos < 0 else 0
    unrealized = abs(pos) * (mid - avg_entry) * sign if avg_entry and pos else 0.0

    day = state.get("day_state") or {}
    start_cash = day.get("start_cash", 0.0)
    start_rebates = day.get("start_rebates", 0.0)
    start_vol = day.get("start_vol", 0.0)
    start_fills = day.get("start_fills", 0)

    realized_today = state.get("cash_usd", 0.0) - start_cash
    rebates_today = state.get("rebates_usd", 0.0) - start_rebates
    vol_today = state.get("volume_usd", 0.0) - start_vol
    fills_today = state.get("fills", 0) - start_fills
    net_today = realized_today + rebates_today + unrealized

    # Time since day start (UTC)
    today_utc = datetime.now(timezone.utc).date()
    seconds_into_day = (datetime.now(timezone.utc)
                         - datetime(today_utc.year, today_utc.month, today_utc.day,
                                     tzinfo=timezone.utc)).total_seconds()
    hours_into_day = max(seconds_into_day / 3600.0, 0.01)
    projected_eod = net_today / hours_into_day * 24.0 if hours_into_day > 0 else 0
    expected = EXPECTED_DAILY_NET.get(symbol, 0)
    pace_pct = projected_eod / expected * 100 if expected else 0

    lines = [
        f"\n=== {symbol} (paper grid) ===",
        f"  anchor: ${state.get('anchor'):,.4f}   mid: ${mid:,.4f}",
        f"  position: {pos:+.4f} native  avg_entry: ${avg_entry:,.4f}",
        f"  unrealized: ${unrealized:+,.2f}",
        f"  inventory cap: {state.get('inventory_cap_native'):.4f} native "
            f"({abs(pos)/state.get('inventory_cap_native',1)*100:.0f}% utilized)",
        "",
        f"  TODAY ({today_utc}):",
        f"    fills:      {fills_today}",
        f"    volume:     ${vol_today:,.0f}",
        f"    realized:   ${realized_today:+,.2f}",
        f"    rebates:    ${rebates_today:+,.2f}",
        f"    unrealized: ${unrealized:+,.2f}",
        f"    net:        ${net_today:+,.2f}  ({hours_into_day:.1f}h elapsed)",
        "",
        f"  EOD PROJECTION (at current rate):",
        f"    projected net: ${projected_eod:+,.2f}",
        f"    expected (sweep): ${expected:,.0f}",
        f"    pace: {pace_pct:.0f}%   {'🟢 on/ahead' if pace_pct >= 80 else '🟡 below pace' if pace_pct >= 30 else '🔴 well below' if expected else ''}",
    ]
    if state.get("halted"):
        lines.append(f"  ⚠ HALTED until {state.get('halt_until_ts')}")
    if history:
        lines.append("")
        lines.append("  PAST DAYS:")
        for row in history[-5:]:
            lines.append(f"    {row.get('date')}  net=${row.get('net_usd'):+,.2f}  "
                          f"vol=${row.get('volume_usd'):,.0f}  fills={row.get('fills')}  "
                          f"realized=${row.get('realized_usd'):+,.2f}  "
                          f"rebates=${row.get('rebates_usd'):+,.2f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=SYMBOLS + ["all"], default="all")
    args = ap.parse_args()
    symbols = SYMBOLS if args.symbol == "all" else [args.symbol]
    for s in symbols:
        print(_report_symbol(s))


if __name__ == "__main__":
    main()
