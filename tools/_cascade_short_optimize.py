"""cascade_alert SHORT engine — parameter optimization.

The SHORT side (long_liq -> SHORT continuation) is the proven +EV engine
(PF 4.23, +$266 over n=33 closed). This re-simulates each recorded SHORT
signal from its real entry/ts against 1m BTC under a grid of (tp, stop, hold)
and liq/ADX filters to find the parameter region that maximises net EV/PF.

Current live params: tp 0.75%, stop 0.5%, hold 4h, no liq/ADX gate.

CAVEAT: n=39 (filters shrink it further) — coarse grid only, pick a stable
region, not the single best overfit cell. Fees 0.15% RT (XBTUSDT taker).

Output: docs/STRATEGIES/CASCADE_SHORT_OPTIMIZE.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.orchestrator.regime_classifier import calc_adx  # noqa: E402
from tools._gc_down_diagnostic import _load_1m, _resample, TFView, BTC_1M  # noqa: E402

OUT_MD = ROOT / "docs" / "STRATEGIES" / "CASCADE_SHORT_OPTIMIZE.md"
FEES_RT = 0.15

TPS = [0.5, 0.75, 1.0, 1.25, 1.5]
STOPS = [0.4, 0.5, 0.75, 1.0]
HOLDS = [4, 6, 8]


def _pt(s):
    try:
        return pd.Timestamp(str(s)).tz_convert("UTC")
    except Exception:
        return None


def _short_sim(entry, ts, hi, lo, cl, ts_ns, tp, stop, hold_h):
    pos = int(np.searchsorted(ts_ns, ts.value, side="left"))
    end = pos + hold_h * 60
    if pos >= len(cl) or end > len(cl) or entry <= 0:
        return None
    tp_px = entry * (1 - tp / 100.0)
    sl_px = entry * (1 + stop / 100.0)
    gross = None
    for i in range(pos, end):
        if hi[i] >= sl_px:      # stop (price rose) — check first (conservative)
            gross = -stop
            break
        if lo[i] <= tp_px:      # take profit (price fell)
            gross = tp
            break
    if gross is None:
        gross = (entry / float(cl[end - 1]) - 1.0) * 100.0
    return gross - FEES_RT


def _stats(pnls):
    n = len(pnls)
    if not n:
        return None
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    pf = (sum(wins) / sum(losses)) if losses else 999.0
    return {"n": n, "wr": round(len(wins) / n * 100, 1),
            "ev": round(sum(pnls) / n, 4), "pf": round(pf, 2),
            "usd": round(sum(pnls) * 10, 1)}  # size $1000 -> %*10


def main() -> int:
    rows = [json.loads(l) for l in open(ROOT / "state" / "paper_signals.jsonl") if l.strip()]
    sh = [r for r in rows if r.get("source") == "cascade_alert" and r.get("side") == "SHORT"
          and r.get("entry") and r.get("ts_signal")]
    px = _load_1m(BTC_1M).sort_values("ts")
    ts_ns = px["ts"].astype("int64").to_numpy()
    hi = px["high"].to_numpy(dtype=float)
    lo = px["low"].to_numpy(dtype=float)
    cl = px["close"].to_numpy(dtype=float)
    btc_1h = TFView(_resample(_load_1m(BTC_1M), "1h"))

    sig = []
    for r in sh:
        ts = _pt(r["ts_signal"])
        if ts is None:
            continue
        ctx = r.get("context", "")
        liq = float(ctx.split("_")[-1].replace("btc", "")) if "btc" in ctx else 0.0
        h1 = btc_1h.window_before(ts, 60)
        adx = 0.0
        if len(h1) >= 32:
            adx, _ = calc_adx([{"high": x.high, "low": x.low, "close": x.close}
                               for x in h1.itertuples()])
        sig.append({"entry": float(r["entry"]), "ts": ts, "liq": liq, "adx": adx})
    print(f"cascade SHORT resimmable: {len(sig)}")

    def run(subset, tp, stop, hold):
        pnls = []
        for s in subset:
            p = _short_sim(s["entry"], s["ts"], hi, lo, cl, ts_ns, tp, stop, hold)
            if p is not None:
                pnls.append(p)
        return _stats(pnls)

    md = ["# cascade_alert SHORT — parameter optimization", ""]
    md.append(f"Re-simulated **{len(sig)}** recorded SHORT signals from real entry/ts "
              "against 1m BTC. Current live: tp 0.75 / stop 0.5 / hold 4h. "
              f"Fees {FEES_RT}% RT, size $1000 (usd = %·10).")
    md.append("")
    base = run(sig, 0.75, 0.5, 4)
    md.append(f"**Baseline (live params, all SHORT):** n={base['n']} WR={base['wr']}% "
              f"EV={base['ev']:+.3f}% PF={base['pf']} PnL={base['usd']:+.1f}$")
    md.append("")

    # full grid on all SHORT, rank by EV with n guard
    md.append("## Top (tp/stop/hold) configs — all SHORT, ranked by PF·EV")
    md.append("")
    md.append("| tp | stop | hold | n | WR% | EV% | PF | PnL$ |")
    md.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    grid = []
    for tp in TPS:
        for stop in STOPS:
            for hold in HOLDS:
                st = run(sig, tp, stop, hold)
                if st and st["n"] >= 25:
                    grid.append((tp, stop, hold, st))
    grid.sort(key=lambda g: g[3]["ev"], reverse=True)
    for tp, stop, hold, st in grid[:10]:
        md.append(f"| {tp} | {stop} | {hold} | {st['n']} | {st['wr']} | "
                  f"{st['ev']:+.3f} | {st['pf']} | {st['usd']:+.1f} |")
    md.append("")

    # filter effect at best-region params
    best = grid[0] if grid else (0.75, 0.5, 4, base)
    btp, bstop, bhold = best[0], best[1], best[2]
    md.append(f"## Filter effect @ best region (tp {btp}/stop {bstop}/hold {bhold})")
    md.append("")
    md.append("| filter | n | WR% | EV% | PF | PnL$ |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for label, sub in [
        ("all SHORT", sig),
        ("liq>=5", [s for s in sig if s["liq"] >= 5]),
        ("liq>=10", [s for s in sig if s["liq"] >= 10]),
        ("ADX<25", [s for s in sig if s["adx"] < 25]),
        ("liq>=5 & ADX<25", [s for s in sig if s["liq"] >= 5 and s["adx"] < 25]),
    ]:
        st = run(sub, btp, bstop, bhold)
        if st:
            md.append(f"| {label} | {st['n']} | {st['wr']} | {st['ev']:+.3f} | "
                      f"{st['pf']} | {st['usd']:+.1f} |")
    md.append("")
    md.append(f"## Verdict")
    md.append("")
    md.append(f"Baseline live EV {base['ev']:+.3f}%/trade ({base['usd']:+.1f}$). "
              f"Best stable grid cell: tp {btp}/stop {bstop}/hold {bhold} "
              f"(EV {best[3]['ev']:+.3f}%, PF {best[3]['pf']}, n={best[3]['n']}). "
              "Apply the liq>=5 gate (drops 2 BTC noise) regardless. n is small — "
              "treat param change as provisional, confirm on accumulating live SHORT.")
    md.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
