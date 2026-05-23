"""LMD basis-component deep-dive — which basis labels predict the wins?

Joins long_multi_divergence setups (state/setups.jsonl, has `basis` array
with labelled features) with their closed paper trades
(state/paper_trades.jsonl) by setup_id. Per basis-label value, computes
how often that value appears in winners vs losers.

Goal: find which sub-feature(s) of the multi-divergence signal carry the
real edge — so we can tighten the detector to require them, or build a
second-tier "ELITE+" rule (e.g. only when agreeing_indicators contains X).
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
SETUPS = ROOT / "state" / "setups.jsonl"
PTRD = ROOT / "state" / "paper_trades.jsonl"


def _ts_key(iso_ts: str) -> str:
    """Round ISO timestamp to minute precision for fuzzy joins."""
    return (iso_ts or "")[:16]  # "2026-05-08T16:32"


def _load_lmd_setups() -> dict:
    """(ts_minute, pair) -> setup record (with basis array).

    setup_id hash suffix DIFFERS between setups.jsonl writer and the
    paper_trader OPEN writer (they generate independent uuids on the
    same market event). We join by (minute, pair) instead.
    """
    out = {}
    with SETUPS.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("setup_type") != "long_multi_divergence":
                    continue
                key = (_ts_key(r.get("detected_at", "")),
                       r.get("pair", "BTCUSDT"))
                out[key] = r
            except json.JSONDecodeError:
                continue
    return out


def _load_lmd_trades_paired():
    """Pairs OPEN→CLOSE by trade_id; returns list of {setup_id, pnl, action}."""
    opens, closes = {}, {}
    with PTRD.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("setup_type") != "long_multi_divergence":
                continue
            tid = r.get("trade_id")
            if not tid:
                continue
            act = r.get("action")
            if act == "OPEN":
                opens[tid] = r
            elif act in ("TP1", "TP2", "SL", "EXPIRE", "CLOSE"):
                closes[tid] = r
    paired = []
    for tid, op in opens.items():
        cl = closes.get(tid)
        if not cl:
            continue
        paired.append({
            "ts_min": _ts_key(op.get("ts", "")),
            "pair": op.get("pair", "BTCUSDT"),
            "pnl": float(cl.get("realized_pnl_usd") or 0),
            "action": cl.get("action"),
        })
    return paired


def main():
    setups = _load_lmd_setups()
    trades = _load_lmd_trades_paired()
    print(f"LMD setups with basis: {len(setups)}")
    print(f"LMD paired trades:     {len(trades)}")

    # join + bucket  (key = ts_min + pair; setup_id hashes differ across writers)
    joined = []
    for t in trades:
        s = setups.get((t["ts_min"], t["pair"]))
        if not s:
            continue
        joined.append({
            "pnl": t["pnl"],
            "action": t["action"],
            "basis": s.get("basis") or [],
            "regime": s.get("regime_label"),
            "session": s.get("session_label"),
            "pair": s.get("pair"),
            "confidence_pct": s.get("confidence_pct"),
        })
    print(f"joined (setup ∩ trade): {len(joined)}")
    if not joined:
        print("  (setups.jsonl may have rotated — old trades have no basis)")
        return
    wins = sum(1 for j in joined if j["pnl"] > 0)
    print(f"  overall WR on joined subset: {100*wins/len(joined):.1f}%")

    # === basis-label VALUE distribution: per (label, value) bucket ===
    by_lv = defaultdict(lambda: [0, 0])  # (label, str(value)) -> [n_win, n_loss]
    for j in joined:
        cls = "W" if j["pnl"] > 0 else "L"
        for b in j["basis"]:
            lbl = b.get("label", "?")
            val = b.get("value")
            # bucket numeric values into coarse bins; keep strings as-is
            if isinstance(val, (int, float)):
                # round to int for ints, 1-decimal for floats
                vkey = str(round(val, 1) if isinstance(val, float) else val)
            else:
                vkey = str(val)
            idx = 0 if cls == "W" else 1
            by_lv[(lbl, vkey)][idx] += 1

    # for each label, show which VALUES correlate with wins (>=5 occurrences)
    print("\n=== basis-label values — wins vs losses (n>=5) ===")
    by_label = defaultdict(list)
    for (lbl, val), (w, l) in by_lv.items():
        by_label[lbl].append((val, w, l))
    for lbl in sorted(by_label):
        rows = [(v, w, l) for v, w, l in by_label[lbl] if (w + l) >= 5]
        if not rows:
            continue
        print(f"\n  label='{lbl}':")
        rows.sort(key=lambda x: -(x[1] / max(x[1] + x[2], 1)))
        print(f"    {'value':<28} {'n':>4} {'wins':>5} {'WR':>7}")
        for v, w, l in rows:
            n = w + l
            wr = 100 * w / n
            print(f"    {v:<28} {n:>4} {w:>5} {wr:>6.1f}%")

    # === STRING-CONTAINS pivot for agreeing_indicators (most interesting) ===
    print("\n=== agreeing_indicators — does each indicator predict W? ===")
    indicator_stats = defaultdict(lambda: [0, 0])
    for j in joined:
        cls_idx = 0 if j["pnl"] > 0 else 1
        for b in j["basis"]:
            if b.get("label") != "agreeing_indicators":
                continue
            v = str(b.get("value") or "")
            for ind in v.replace(",", "+").split("+"):
                ind = ind.strip()
                if ind:
                    indicator_stats[ind][cls_idx] += 1
    print(f"  {'indicator':<20} {'n':>4} {'wins':>5} {'WR':>7}")
    rows = []
    for ind, (w, l) in indicator_stats.items():
        n = w + l
        if n >= 5:
            rows.append((ind, n, w, 100 * w / n))
    for ind, n, w, wr in sorted(rows, key=lambda x: -x[3]):
        print(f"  {ind:<20} {n:>4} {w:>5} {wr:>6.1f}%")

    # === confluence_count numeric distribution ===
    print("\n=== confluence_count — does more confluence predict W? ===")
    by_conf = defaultdict(lambda: [0, 0])
    for j in joined:
        cls_idx = 0 if j["pnl"] > 0 else 1
        for b in j["basis"]:
            if b.get("label") == "confluence_count":
                v = int(b.get("value") or 0)
                by_conf[v][cls_idx] += 1
    print(f"  {'count':>6} {'n':>4} {'wins':>5} {'WR':>7}")
    for c in sorted(by_conf):
        w, l = by_conf[c]
        n = w + l
        if n < 3:
            continue
        print(f"  {c:>6} {n:>4} {w:>5} {100*w/n:>6.1f}%")


if __name__ == "__main__":
    main()
