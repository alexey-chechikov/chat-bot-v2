"""Backtest the alt decorrelation-divergence signal (the LIVE detector's logic).

Combines the validated multi-indicator divergence engine (run ON the alt) with
the decorrelation gate (alt↔BTC 30-bar return-corr < gate). Shows the edge WITH
vs WITHOUT the corr gate, and the OOS split. Direction: bull div→LONG, bear→SHORT.

Output: docs/STRATEGIES/ALT_DECORR_BACKTEST.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools._gc_down_diagnostic import _load_1m, BTC_1M, ETH_1M, XRP_1M  # noqa: E402
from services.alt_decorr.loop import _detect_bearish_div_bars, CORR_GATE  # noqa: E402
from services.setup_detector.multi_asset_confluence import _detect_bullish_div_bars  # noqa: E402

OUT_MD = ROOT / "docs" / "STRATEGIES" / "ALT_DECORR_BACKTEST.md"
FEE = 0.15
SL, TP = 1.0, 2.0


def _res(df1m, rule):
    return (df1m.set_index("ts").resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna().reset_index())


def _roll_corr(a, b, w=30):
    n = len(a)
    out = np.full(n, np.nan)
    ar = np.diff(np.log(a)); br = np.diff(np.log(b))
    for i in range(w, n):
        sa, sb = ar[i-w:i-0], br[i-w:i-0]
        # align: returns index shifted by 1; use last w returns up to bar i
        sa = ar[i-w:i] if i <= len(ar) else ar[-w:]
        sb = br[i-w:i] if i <= len(br) else br[-w:]
        if sa.std() > 0 and sb.std() > 0:
            out[i] = np.corrcoef(sa, sb)[0, 1]
    return out


def _sim(close_hi_lo, i, side, hbars):
    cl, hi, lo = close_hi_lo
    if i + hbars >= len(cl):
        return None
    entry = cl[i]
    if side == "LONG":
        tp, sl = entry*(1+TP/100), entry*(1-SL/100)
        for j in range(i+1, i+hbars+1):
            if lo[j] <= sl: return -SL - FEE
            if hi[j] >= tp: return TP - FEE
        return (cl[i+hbars]/entry-1)*100 - FEE
    else:
        tp, sl = entry*(1-TP/100), entry*(1+SL/100)
        for j in range(i+1, i+hbars+1):
            if hi[j] >= sl: return -SL - FEE
            if lo[j] <= tp: return TP - FEE
        return (entry/cl[i+hbars]-1)*100 - FEE


def _stats(rets):
    arr = np.array([r for r in rets if r is not None])
    n = len(arr)
    if n < 5:
        return None
    w = arr[arr > 0]; l = -arr[arr < 0]
    pf = (w.sum()/l.sum()) if l.sum() > 0 else 999.0
    t = (arr.mean()/(arr.std(ddof=1)/np.sqrt(n))) if n > 1 and arr.std() > 0 else 0.0
    return {"n": n, "wr": round((arr > 0).mean()*100, 1), "mean": round(arr.mean(), 4),
            "pf": round(pf, 2), "t": round(t, 2), "sum": round(arr.sum(), 1)}


def main() -> int:
    btc1m = _load_1m(BTC_1M)
    md = ["# Alt decorrelation-divergence — backtest (live detector logic)", ""]
    md.append(f"Divergence engine run ON the alt; bull→LONG, bear→SHORT; stop {SL}% "
              f"tp {TP}% fees {FEE}% RT. Gate = alt↔BTC 30-bar corr < {CORR_GATE}. "
              "Shows WITH vs WITHOUT the decorrelation gate, plus OOS halves.")
    md.append("")
    md.append("| alt | TF | gate | seg | n | WR% | mean% | PF | t | sum% |")
    md.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|")

    for alt, path in (("ETHUSDT", ETH_1M), ("XRPUSDT", XRP_1M)):
        alt1m = _load_1m(path)
        for rule, hbars in (("25min", 19), ("1h", 8)):
            a = _res(alt1m, rule)
            b = _res(btc1m, rule)
            j = pd.merge(a, b[["ts", "close"]].rename(columns={"close": "bclose"}),
                         on="ts", how="inner")
            if len(j) < 200:
                continue
            cl = j["close"].to_numpy(float); hi = j["high"].to_numpy(float)
            lo = j["low"].to_numpy(float); bc = j["bclose"].to_numpy(float)
            ts = j["ts"].to_numpy()
            adf = j[["open", "high", "low", "close", "volume"]].copy()
            bulls = set(_detect_bullish_div_bars(adf))
            bears = set(_detect_bearish_div_bars(adf))
            corr = _roll_corr(cl, bc, 30)
            events = []  # (bar, side, corr, ts)
            for i in sorted(bulls | bears):
                if i in bulls and i not in bears:
                    side = "LONG"
                elif i in bears and i not in bulls:
                    side = "SHORT"
                else:
                    continue
                events.append((i, side, corr[i], ts[i]))
            for gate_lbl, gated in (("no-gate", False), (f"corr<{CORR_GATE}", True)):
                sel = [(i, s, c, t) for (i, s, c, t) in events
                       if (not gated) or (not np.isnan(c) and c < CORR_GATE)]
                if not sel:
                    continue
                rets = [_sim((cl, hi, lo), i, s, hbars) for (i, s, c, t) in sel]
                tss = [t for (i, s, c, t) in sel]
                pairs = [(t, r) for t, r in zip(tss, rets) if r is not None]
                if len(pairs) < 5:
                    continue
                pairs.sort()
                arr_t = np.array([p[0] for p in pairs])
                arr_r = np.array([p[1] for p in pairs])
                half = len(arr_r)//2
                for seg, m in (("FULL", np.ones(len(arr_r), bool)),
                               ("y1", np.arange(len(arr_r)) < half),
                               ("y2", np.arange(len(arr_r)) >= half)):
                    st = _stats(arr_r[m])
                    if st:
                        md.append(f"| {alt} | {rule} | {gate_lbl} | {seg} | {st['n']} | "
                                  f"{st['wr']} | {st['mean']:+.3f} | {st['pf']} | "
                                  f"{st['t']} | {st['sum']:+.1f} |")
        md.append("|  |  |  |  |  |  |  |  |  |  |")

    md.append("")
    md.append("Edge = the `corr<gate` rows beating the `no-gate` rows AND positive in "
              "both y1 & y2. If the gate doesn't lift the divergence edge, decorrelation "
              "adds nothing and we run plain alt-divergence instead.")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
