"""Exit-parameter optimization on the FIXED per-pair price.

Lead: setups with very low SL-rate (e.g. long_double_bottom 1 SL / 42) have GOOD
entry timing — price rarely goes against you — but mostly TIME OUT before a too-far
TP. So the question isn't "is the entry good" (it is) but "are TP/SL/window tuned".
Re-simulate each setup's real trades against its own pair's 1m price under a grid
of (tp%, sl%, window) and find net-positive cells. Fees 0.165% RT.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
SETUPS = ROOT / "state" / "setups.jsonl"
FEES = 0.165
TARGETS = ("long_double_bottom", "long_pdl_bounce", "long_dump_reversal",
           "long_mega_dump_bounce")
TPS = (0.4, 0.6, 0.8, 1.0, 1.5)
SLS = (0.5, 0.75, 1.0, 1.5)
WINDOWS = (120, 240, 480, 720)
_cache = {}


def prices(pair):
    if pair not in _cache:
        fp = ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv"
        if not fp.exists():
            _cache[pair] = pd.DataFrame()
            return _cache[pair]
        df = pd.read_csv(fp)
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        _cache[pair] = df.set_index("ts")[["high", "low", "close"]].sort_index()
    return _cache[pair]


def sim(px, det, entry, tp_pct, sl_pct, window):
    end = det + timedelta(minutes=window)
    fwd = px.loc[(px.index >= det) & (px.index <= end)]
    if fwd.empty:
        return None
    tp = entry * (1 + tp_pct / 100)
    sl = entry * (1 - sl_pct / 100)
    for _, row in fwd.iterrows():
        if row["low"] <= sl:
            return -sl_pct - FEES
        if row["high"] >= tp:
            return tp_pct - FEES
    return (float(fwd["close"].iloc[-1]) / entry - 1) * 100 - FEES


def main():
    setups = []
    for l in SETUPS.read_text().splitlines():
        if not l.strip():
            continue
        try:
            s = json.loads(l)
        except ValueError:
            continue
        if s.get("setup_type") in TARGETS and float(s.get("recommended_size_btc") or 0) > 0:
            setups.append(s)
    print(f"target setups: {len(setups)}")

    # precompute per setup its real trade context
    trades = []
    for s in setups:
        try:
            det = datetime.fromisoformat(s["detected_at"].replace("Z", "+00:00"))
            if det.tzinfo is None:
                det = det.replace(tzinfo=timezone.utc)
            entry = float(s.get("entry_price") or 0)
        except (KeyError, ValueError, TypeError):
            continue
        if entry <= 0:
            continue
        trades.append((s["setup_type"], s.get("pair") or "BTCUSDT", det, entry))

    out = []
    for st in TARGETS:
        st_tr = [t for t in trades if t[0] == st]
        if len(st_tr) < 10:
            continue
        best = None
        for tp in TPS:
            for sl in SLS:
                for w in WINDOWS:
                    pnls = []
                    for _, pair, det, entry in st_tr:
                        px = prices(pair)
                        if px.empty:
                            continue
                        r = sim(px, det, entry, tp, sl, w)
                        if r is not None:
                            pnls.append(r)
                    if len(pnls) < 10:
                        continue
                    n = len(pnls)
                    wins = sum(1 for p in pnls if p > 0)
                    ev = sum(pnls) / n
                    gl = -sum(p for p in pnls if p < 0)
                    gw = sum(p for p in pnls if p > 0)
                    pf = gw / gl if gl > 0 else 999
                    cell = (ev, n, round(wins/n*100, 0), round(pf, 2), tp, sl, w)
                    if best is None or ev > best[0]:
                        best = cell
        if best:
            ev, n, wr, pf, tp, sl, w = best
            out.append((ev, st, n, wr, pf, tp, sl, w))

    print("\nBEST exit-params per setup (real per-pair price, net of fees):")
    print(f"{'setup':24s} {'n':>4} {'WR%':>5} {'PF':>6} {'tp%':>5} {'sl%':>5} {'win(min)':>9} {'EV%/tr':>8}")
    for ev, st, n, wr, pf, tp, sl, w in sorted(out, reverse=True):
        flag = "🟢" if ev > 0 else "🔴"
        print(f"{st:24s} {n:>4} {wr:>5.0f} {pf:>6} {tp:>5} {sl:>5} {w:>9} {ev:>+7.3f} {flag}")

    # baseline (current live params ~ setup's own): show double_bottom default-ish
    print("\n(current live defaults were typically tp~0.7-1% / window 120m → mostly timeout)")


if __name__ == "__main__":
    main()
