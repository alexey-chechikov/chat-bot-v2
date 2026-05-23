"""p15 forensic — why 0/59 WR?

Reads state/p15_paper_trades.jsonl, analyses:
  - CLOSE reasons (the smoking-gun string field)
  - PnL by side / pair / layer count / hold time
  - HARVEST profits — does the strategy capture ANY upside before close
    drains it?
  - Time-from-OPEN-to-CLOSE distribution
  - avg_entry vs exit_price slip — how far against do closes happen?
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

P15 = Path("/Users/alexeychechikov/code/bot7/state/p15_paper_trades.jsonl")


def _read():
    out = []
    with P15.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def main():
    rows = _read()
    opens   = [r for r in rows if r.get("action") == "OPEN"]
    harv    = [r for r in rows if r.get("action") == "HARVEST"]
    closes  = [r for r in rows if r.get("action") == "CLOSE"]
    print(f"OPEN={len(opens)}  HARVEST={len(harv)}  CLOSE={len(closes)}")

    # --- CLOSE reasons (the smoking gun) ---
    print("\n=== CLOSE 'reason' distribution ===")
    by_reason = defaultdict(list)
    for c in closes:
        by_reason[c.get("reason", "(no reason)")].append(c)
    for r, items in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        pnls = [float(i.get("realized_pnl_usd") or 0) for i in items]
        wins = sum(1 for p in pnls if p > 0)
        s = sum(pnls)
        print(f"  '{r}'")
        print(f"     n={len(items)}  WR={100*wins/len(items):.0f}%  sum=${s:+.1f}  "
              f"mean=${s/len(items):+.2f}")

    # --- by side ---
    print("\n=== CLOSE PnL by side ===")
    by_side = defaultdict(list)
    for c in closes:
        by_side[c.get("side", "?")].append(float(c.get("realized_pnl_usd") or 0))
    for s, pnls in by_side.items():
        wins = sum(1 for p in pnls if p > 0)
        print(f"  {s:<8} n={len(pnls):>3}  WR={100*wins/len(pnls):>5.1f}%  "
              f"sum=${sum(pnls):>+8.1f}  median=${sorted(pnls)[len(pnls)//2]:>+7.2f}")

    # --- by pair ---
    print("\n=== CLOSE PnL by pair ===")
    by_pair = defaultdict(list)
    for c in closes:
        by_pair[c.get("pair", "?")].append(float(c.get("realized_pnl_usd") or 0))
    for p, pnls in sorted(by_pair.items(), key=lambda x: sum(x[1])):
        wins = sum(1 for v in pnls if v > 0)
        print(f"  {p:<10} n={len(pnls):>3}  WR={100*wins/len(pnls):>5.0f}%  "
              f"sum=${sum(pnls):>+7.1f}")

    # --- HARVEST profitability — does strategy ever capture upside? ---
    print("\n=== HARVEST partials — did the strategy ever take profit? ===")
    h_pnls = [float(h.get("realized_pnl_usd") or 0) for h in harv]
    if h_pnls:
        h_wins = sum(1 for p in h_pnls if p > 0)
        print(f"  n={len(h_pnls)}  WR={100*h_wins/len(h_pnls):.0f}%  "
              f"sum=${sum(h_pnls):+.1f}  mean=${sum(h_pnls)/len(h_pnls):+.2f}  "
              f"min=${min(h_pnls):+.2f}  max=${max(h_pnls):+.2f}")

    # --- avg_entry vs exit_price slip ---
    print("\n=== entry vs exit slippage on CLOSE ===")
    slips = []
    for c in closes:
        ae = float(c.get("p15_avg_entry") or 0)
        ep = float(c.get("exit_price") or 0)
        side = c.get("side")
        if ae <= 0 or ep <= 0:
            continue
        # signed slippage from entry IN THE DIRECTION OF LOSS
        if side == "long":
            slip_pct = (ep - ae) / ae * 100   # negative = adverse
        else:
            slip_pct = (ae - ep) / ae * 100   # negative = adverse
        slips.append(slip_pct)
    if slips:
        slips.sort()
        print(f"  n={len(slips)}  mean={sum(slips)/len(slips):+.3f}%  "
              f"median={slips[len(slips)//2]:+.3f}%  "
              f"p10={slips[len(slips)//10]:+.3f}%  "
              f"p90={slips[9*len(slips)//10]:+.3f}%")

    # --- layer-count distribution at CLOSE ---
    print("\n=== layer count at CLOSE ===")
    by_layer = defaultdict(list)
    for c in closes:
        by_layer[c.get("p15_layer", 0)].append(float(c.get("realized_pnl_usd") or 0))
    for k in sorted(by_layer):
        pnls = by_layer[k]
        w = sum(1 for p in pnls if p > 0)
        print(f"  layer={k}: n={len(pnls):>3}  WR={100*w/len(pnls):>5.0f}%  "
              f"sum=${sum(pnls):>+7.1f}")

    # --- hold time on CLOSE ---
    print("\n=== hold time (HARVEST → CLOSE) ===")
    # match OPEN→CLOSE by trade-flow setup_id might not work since events have own ids
    # use ts diff for closes that have explicit OPEN trace... simpler: just first OPEN by setup-id
    open_by_setup = {}
    for o in opens:
        sid = o.get("setup_id")
        if sid:
            open_by_setup.setdefault(sid, o)
    holds = []
    for c in closes:
        sid = c.get("setup_id")
        op = open_by_setup.get(sid)
        if not op:
            continue
        try:
            t1 = datetime.fromisoformat(c["ts"].replace("Z", "+00:00"))
            t0 = datetime.fromisoformat(op["ts"].replace("Z", "+00:00"))
            holds.append((t1 - t0).total_seconds() / 60.0)
        except (KeyError, ValueError):
            continue
    if holds:
        holds.sort()
        print(f"  n={len(holds)}  median={holds[len(holds)//2]:.1f}min  "
              f"p10={holds[len(holds)//10]:.0f}min  "
              f"p90={holds[9*len(holds)//10]:.0f}min")


if __name__ == "__main__":
    main()
