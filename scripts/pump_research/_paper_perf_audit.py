"""Audit of paper-trade performance across all three streams.

Sources:
  state/paper_signals.jsonl   — emitter signals (cascade_alert, etc.) with
                                 outcome + pnl_usd
  state/paper_trades.jsonl    — setup_detector paper trades (per setup_type)
  state/p15_paper_trades.jsonl — Phase-15 strategy paper trades

For each: WR, mean PnL, cumulative, top losers. Flag anything with
WR < 40% (n >= 10) as "actively losing — disable / fix".
"""
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
PSIG = ROOT / "state" / "paper_signals.jsonl"
PTRD = ROOT / "state" / "paper_trades.jsonl"
P15 = ROOT / "state" / "p15_paper_trades.jsonl"


def _read_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def audit_paper_signals():
    rows = _read_jsonl(PSIG)
    print(f"\n=== paper_signals.jsonl  (cascade_alert + similar emitters) ===")
    print(f"total rows: {len(rows)}")
    closed = [r for r in rows if r.get("outcome") and r.get("pnl_usd") is not None]
    print(f"closed (with outcome): {len(closed)}")
    if not closed:
        return
    cum = sum(r["pnl_usd"] for r in closed)
    print(f"cumulative paper PnL: ${cum:+.2f}")
    # by source + side
    by = defaultdict(list)
    for r in closed:
        key = (r.get("source", "?"), r.get("side", "?"))
        by[key].append(r["pnl_usd"])
    print(f"\n  {'source':<22} {'side':<5} {'n':>4} {'WR':>7} {'sum_pnl':>10} {'mean':>9}")
    for (src, side), pnls in sorted(by.items(), key=lambda x: -sum(x[1])):
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        wr = 100 * wins / n
        mean = sum(pnls) / n
        flag = "  🔴" if (wr < 40 and n >= 10) else ""
        print(f"  {src:<22} {side:<5} {n:>4} {wr:>6.1f}% ${sum(pnls):>+8.1f} ${mean:>+7.2f}{flag}")
    # by context (which liq-side/threshold cluster generated the signal)
    by_ctx = defaultdict(list)
    for r in closed:
        key = (r.get("source", "?"), r.get("side", "?"), r.get("context", ""))
        by_ctx[key].append(r["pnl_usd"])
    print(f"\n  per CONTEXT (top 10 by loss exposure):")
    print(f"  {'source':<14} {'side':<5} {'context':<25} {'n':>4} {'WR':>7} {'sum':>9}")
    for (src, side, ctx), pnls in sorted(by_ctx.items(), key=lambda x: sum(x[1]))[:10]:
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        wr = 100 * wins / n
        flag = "  🔴" if (wr < 40 and n >= 5) else ""
        print(f"  {src:<14} {side:<5} {ctx:<25} {n:>4} {wr:>6.1f}% ${sum(pnls):>+7.1f}{flag}")


def audit_paper_trades():
    rows = _read_jsonl(PTRD)
    print(f"\n\n=== paper_trades.jsonl  (setup_detector paper executions) ===")
    print(f"total rows: {len(rows)}")
    # rows include intermediate updates; closed = action in (TP1, TP2, SL, EXPIRE, STOP)
    closes = [r for r in rows if r.get("action") in ("TP1", "TP2", "SL", "EXPIRE", "STOP")
              and r.get("realized_pnl_usd") is not None]
    print(f"closes: {len(closes)}")
    if not closes:
        return
    cum = sum(r["realized_pnl_usd"] for r in closes)
    print(f"cumulative paper PnL: ${cum:+.2f}")
    by = defaultdict(list)
    for r in closes:
        by[r.get("setup_type", "?")].append((r["realized_pnl_usd"], r.get("action", "?")))
    print(f"\n  {'setup_type':<35} {'n':>4} {'WR':>7} {'sum_pnl':>10} {'mean':>9}  status")
    for st, lst in sorted(by.items(), key=lambda x: sum(p for p, _ in x[1])):
        n = len(lst)
        wins = sum(1 for p, _ in lst if p > 0)
        wr = 100 * wins / n
        s = sum(p for p, _ in lst)
        m = s / n
        flag = "🔴 active-loss" if (wr < 40 and n >= 10) else (
            "🟠 borderline" if (wr < 50 and n >= 10) else (
                "🟢 ok" if (wr >= 50 and n >= 10) else "·· small-n"))
        print(f"  {st:<35} {n:>4} {wr:>6.1f}% ${s:>+8.1f} ${m:>+7.2f}  {flag}")


def audit_p15():
    rows = _read_jsonl(P15)
    print(f"\n\n=== p15_paper_trades.jsonl ===")
    print(f"total rows: {len(rows)}")
    closes = [r for r in rows if r.get("action") in ("CLOSE", "EXPIRE", "STOP")
              and r.get("realized_pnl_usd") is not None]
    print(f"closes: {len(closes)}")
    if not closes:
        return
    cum = sum(r["realized_pnl_usd"] for r in closes)
    print(f"cumulative paper PnL: ${cum:+.2f}")
    by_side = defaultdict(list)
    for r in closes:
        by_side[r.get("side", "?")].append(r["realized_pnl_usd"])
    print(f"  {'side':<8} {'n':>4} {'WR':>7} {'sum_pnl':>10}")
    for s, pnls in by_side.items():
        n = len(pnls)
        w = sum(1 for p in pnls if p > 0)
        print(f"  {s:<8} {n:>4} {100*w/n:>6.1f}% ${sum(pnls):>+8.1f}")


def audit_rolling_drift():
    """7-day rolling WR for paper_signals — drift detector."""
    rows = _read_jsonl(PSIG)
    closed = [r for r in rows if r.get("outcome") and r.get("pnl_usd") is not None
              and r.get("exit_ts")]
    if len(closed) < 20:
        return
    print("\n\n=== drift: weekly rolling WR by source (paper_signals) ===")
    # group by source, build weekly cohorts
    by_src = defaultdict(list)
    for r in closed:
        try:
            t = datetime.fromisoformat(r["exit_ts"].replace("Z", "+00:00"))
            by_src[r.get("source", "?")].append((t, r["pnl_usd"]))
        except (ValueError, KeyError):
            continue
    for src, items in by_src.items():
        if len(items) < 10:
            continue
        items.sort()
        # 7d cohorts (rolling weekly buckets)
        buckets = defaultdict(list)
        for t, p in items:
            wk = t.isocalendar()[1]
            buckets[wk].append(p)
        print(f"\n  source={src}")
        for wk in sorted(buckets.keys()):
            lst = buckets[wk]
            n = len(lst)
            if n < 3:
                continue
            wr = 100 * sum(1 for p in lst if p > 0) / n
            s = sum(lst)
            print(f"    wk{wk:>2}  n={n:>3}  WR={wr:>5.1f}%  sum=${s:>+7.1f}")


def main():
    audit_paper_signals()
    audit_paper_trades()
    audit_p15()
    audit_rolling_drift()


if __name__ == "__main__":
    main()
