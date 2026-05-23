"""Deep-dive: why does `long_multi_divergence` print money?

paper_trades.jsonl audit showed n=60 closes, WR 88.3%, +$5925 — 89% of
all setup_detector paper profit comes from this one setup type.
This script finds the CONDITIONS where it works best so we know whether
to (a) trust + size up, or (b) suspect leakage.
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
PTRD = ROOT / "state" / "paper_trades.jsonl"
SETUPS = ROOT / "state" / "setups.jsonl"

TARGET = "long_multi_divergence"


def load_paper_trades_lmd():
    """trade_id -> (open_record, close_record) for the target setup_type."""
    opens = {}
    closes = {}
    with PTRD.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("setup_type") != TARGET:
                continue
            tid = r.get("trade_id")
            if not tid:
                continue
            act = r.get("action")
            if act == "OPEN":
                opens[tid] = r
            elif act in ("TP1", "TP2", "SL", "EXPIRE", "CLOSE"):
                closes[tid] = r
    return opens, closes


def load_setups_by_id():
    sid_to_setup = {}
    with SETUPS.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                sid = r.get("setup_id")
                if sid:
                    sid_to_setup[sid] = r
            except json.JSONDecodeError:
                continue
    return sid_to_setup


def main():
    opens, closes = load_paper_trades_lmd()
    setups = load_setups_by_id()
    paired = []
    for tid, op in opens.items():
        cl = closes.get(tid)
        if not cl:
            continue
        sid = op.get("setup_id")
        st = setups.get(sid, {})
        paired.append({
            "trade_id": tid,
            "regime": op.get("regime_at_entry") or st.get("regime_label"),
            "session": op.get("session_at_entry") or st.get("session_label"),
            "pair": op.get("pair") or st.get("pair"),
            "conf": float(st.get("confidence_pct") or 0),
            "strength": int(st.get("strength") or 0),
            "basis_labels": [b.get("label") for b in (st.get("basis") or [])],
            "action": cl.get("action"),
            "pnl": float(cl.get("realized_pnl_usd") or 0),
            "rr_realized": float(cl.get("rr_realized") or 0),
            "hours": float(cl.get("hours_in_trade") or 0),
        })
    print(f"paired closed trades: {len(paired)}")
    if not paired:
        return
    total_pnl = sum(p["pnl"] for p in paired)
    wins = sum(1 for p in paired if p["pnl"] > 0)
    print(f"  cumulative paper PnL: ${total_pnl:+.2f}")
    print(f"  WR: {100*wins/len(paired):.1f}%   mean_pnl: ${total_pnl/len(paired):+.2f}")

    def _bucket_report(field, label):
        print(f"\n--- by {label} ---")
        buckets = defaultdict(list)
        for p in paired:
            buckets[p[field] or "?"].append(p["pnl"])
        for k, pnls in sorted(buckets.items(), key=lambda x: -sum(x[1])):
            n = len(pnls)
            w = sum(1 for v in pnls if v > 0)
            print(f"  {str(k):<22} n={n:>3}  WR={100*w/n:>5.1f}%  sum=${sum(pnls):>+8.1f}  mean=${sum(pnls)/n:>+7.2f}")

    _bucket_report("regime", "regime_at_entry")
    _bucket_report("session", "session")
    _bucket_report("pair", "pair")
    _bucket_report("action", "exit reason (sanity check)")

    print("\n--- by confidence_pct bucket ---")
    bins = [(0, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
    for lo, hi in bins:
        sub = [p for p in paired if lo <= p["conf"] < hi]
        if not sub:
            continue
        w = sum(1 for p in sub if p["pnl"] > 0)
        s = sum(p["pnl"] for p in sub)
        print(f"  conf [{lo:>2}-{hi:>3}): n={len(sub):>3}  WR={100*w/len(sub):>5.1f}%  sum=${s:>+8.1f}")

    print("\n--- by strength score ---")
    by_str = defaultdict(list)
    for p in paired:
        by_str[p["strength"]].append(p["pnl"])
    for k in sorted(by_str):
        pnls = by_str[k]
        w = sum(1 for v in pnls if v > 0)
        print(f"  strength={k:>2}: n={len(pnls):>3}  WR={100*w/len(pnls):>5.1f}%  sum=${sum(pnls):>+8.1f}")

    print("\n--- basis-component frequency (winners vs losers) ---")
    win_basis = defaultdict(int); loss_basis = defaultdict(int)
    win_n = 0; loss_n = 0
    for p in paired:
        if p["pnl"] > 0:
            win_n += 1
            for lbl in p["basis_labels"]:
                win_basis[lbl] += 1
        else:
            loss_n += 1
            for lbl in p["basis_labels"]:
                loss_basis[lbl] += 1
    print(f"  winners n={win_n}  losers n={loss_n}")
    all_labels = set(win_basis) | set(loss_basis)
    # leakage check: any basis label that contains future / outcome tokens?
    suspect = [l for l in all_labels if l and any(t in str(l).lower()
                                                    for t in ("future", "fwd", "outcome", "realized"))]
    if suspect:
        print(f"  ⚠ LEAKAGE CHECK — suspect labels: {suspect}")
    else:
        print("  ✓ no obvious leakage tokens in basis labels")
    # top components present-in-wins
    rows = []
    for lbl in all_labels:
        wn = win_basis.get(lbl, 0); ln = loss_basis.get(lbl, 0)
        if wn + ln < 5:
            continue
        win_rate_when_present = wn / max(wn + ln, 1)
        rows.append((lbl, wn, ln, win_rate_when_present))
    rows.sort(key=lambda x: -x[3])
    print(f"  {'basis_label':<60} {'win_n':>5} {'loss_n':>6} {'win-share':>10}")
    for lbl, wn, ln, wp in rows[:20]:
        print(f"  {str(lbl)[:60]:<60} {wn:>5} {ln:>6} {100*wp:>9.0f}%")

    print("\n--- hold time distribution ---")
    hours = [p["hours"] for p in paired]
    if hours:
        hours.sort()
        med = hours[len(hours)//2]
        print(f"  median: {med:.1f}h   p25: {hours[len(hours)//4]:.1f}h   "
              f"p75: {hours[3*len(hours)//4]:.1f}h   max: {hours[-1]:.1f}h")
    # exit reason vs hold
    print("  by exit reason:")
    by_act = defaultdict(list)
    for p in paired:
        by_act[p["action"]].append(p["hours"])
    for a, hs in by_act.items():
        if not hs:
            continue
        print(f"    {a:<8} n={len(hs):>3}  mean_hold={sum(hs)/len(hs):.1f}h")


if __name__ == "__main__":
    main()
