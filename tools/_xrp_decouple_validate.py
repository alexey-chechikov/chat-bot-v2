"""XRP decoupling-continuation edge — robustness validation.

v2 found: when XRP genuinely decouples from BTC (1h rolling corr<0.5) and cum
residual is in the extreme tail, the divergence CONTINUES (beta-neutral CONT
+0.3..0.4%/trade, t~2-3). Before recommending a build, check it's not a
single-period / single-form artifact:

  1. Out-of-sample: split history in halves, report each.
  2. Recent: last ~120 days only (is it still alive?).
  3. Directional XRP-only variant (no BTC short leg, fees 0.15%) — easier to
     execute than a pairs trade. Trade XRP in the direction of its residual
     divergence when corr<0.5 & extreme tail.

Signal: TF=1h, beta over cw=30, cum residual over K=12, event = |cum_resid| top/
bottom 10%, corr<0.5, hold M=6. CONT = follow the divergence sign.

Output: docs/STRATEGIES/XRP_DECOUPLE_VALIDATION.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools._gc_down_diagnostic import _load_1m, BTC_1M, XRP_1M  # noqa: E402

OUT_MD = ROOT / "docs" / "STRATEGIES" / "XRP_DECOUPLE_VALIDATION.md"
CW, K, M = 30, 12, 6
CORR_MAX = 0.5
TAIL_Q = 10  # top/bottom 10%


def _resample(df1m, rule):
    return df1m.set_index("ts").resample(rule).agg({"close": "last"}).dropna()


def _stats(rets):
    arr = np.array([r for r in rets if r is not None and not np.isnan(r)])
    n = len(arr)
    if not n:
        return None
    wins = arr[arr > 0]; losses = -arr[arr < 0]
    pf = (wins.sum()/losses.sum()) if losses.sum() > 0 else 999.0
    t = (arr.mean()/(arr.std(ddof=1)/np.sqrt(n))) if n > 1 and arr.std() > 0 else 0.0
    return {"n": n, "wr": round((arr > 0).mean()*100, 1), "mean": round(arr.mean(), 4),
            "pf": round(pf, 2), "t": round(t, 2), "sum": round(arr.sum(), 1)}


def main() -> int:
    btc = _resample(_load_1m(BTC_1M), "1h")
    xrp = _resample(_load_1m(XRP_1M), "1h")
    j = pd.DataFrame({"b": btc["close"], "a": xrp["close"]}).dropna()
    ts = j.index.to_numpy()
    bc = j["b"].to_numpy(float); ac = j["a"].to_numpy(float)
    br = np.diff(np.log(bc)); ar = np.diff(np.log(ac))
    tsr = ts[1:]
    n = len(br)

    cumK = np.full(n, np.nan); fwd_pair = np.full(n, np.nan)
    fwd_dir = np.full(n, np.nan); corr = np.full(n, np.nan); sgn = np.full(n, np.nan)
    for i in range(CW + K, n - M):
        bseg = br[i-CW:i]; aseg = ar[i-CW:i]
        var = bseg.var()
        bta = (np.cov(aseg, bseg)[0, 1]/var) if var > 0 else 1.0
        if bseg.std() > 0 and aseg.std() > 0:
            corr[i] = np.corrcoef(aseg, bseg)[0, 1]
        cr = (np.sum(ar[i-K:i]) - bta*np.sum(br[i-K:i]))
        cumK[i] = cr
        sgn[i] = np.sign(cr)
        fwd_pair[i] = (np.sum(ar[i:i+M]) - bta*np.sum(br[i:i+M])) * 100.0  # beta-neutral
        fwd_dir[i] = (np.sum(ar[i:i+M])) * 100.0                            # XRP-only

    valid = ~np.isnan(cumK) & ~np.isnan(fwd_pair) & ~np.isnan(corr)
    idx = np.where(valid)[0]
    ck = cumK[idx]
    hi = np.nanpercentile(ck, 100-TAIL_Q); lo = np.nanpercentile(ck, TAIL_Q)

    def cont_rets(sel_idx, kind):
        """CONT pnl on a subset of indices. kind: 'pair' (0.30 fee) | 'dir' (0.15)."""
        out = []
        for i in sel_idx:
            if corr[i] >= CORR_MAX:
                continue
            if cumK[i] >= hi:
                d = 1.0
            elif cumK[i] <= lo:
                d = -1.0
            else:
                continue
            if kind == "pair":
                out.append(d*fwd_pair[i] - 0.30)
            else:
                out.append(d*fwd_dir[i] - 0.15)
        return out

    # time splits
    half = idx[len(idx)//2]
    recent_cut = None
    cutter = tsr[idx[-1]] - np.timedelta64(120, "D")
    for i in idx:
        if tsr[i] >= cutter:
            recent_cut = i
            break

    segments = {
        "FULL": idx,
        "1st half (OOS-A)": idx[idx < half],
        "2nd half (OOS-B)": idx[idx >= half],
        "last ~120d": idx[idx >= (recent_cut if recent_cut else idx[-1])],
    }

    md = ["# XRP decoupling-continuation — robustness validation", ""]
    md.append(f"Signal: 1h, beta cw={CW}, cum residual K={K}, hold M={M}, event = "
              f"|cum_resid| top/bottom {TAIL_Q}% AND rolling corr<{CORR_MAX}, "
              "CONT = follow divergence sign. pair=beta-neutral (0.30% fee), "
              "dir=XRP-only (0.15% fee).")
    md.append(f"\nWindow: {pd.Timestamp(tsr[idx[0]])} → {pd.Timestamp(tsr[idx[-1]])}\n")
    md.append("| segment | variant | n | WR% | mean% | PF | t | sum% |")
    md.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for seg, sel in segments.items():
        for kind in ("pair", "dir"):
            st = _stats(cont_rets(sel, kind))
            if st:
                md.append(f"| {seg} | {kind} | {st['n']} | {st['wr']} | {st['mean']:+.3f} | "
                          f"{st['pf']} | {st['t']} | {st['sum']:+.1f} |")
    md.append("")
    md.append("## Verdict guide")
    md.append("")
    md.append("Robust if BOTH halves show positive mean with t>~1.5 and the recent "
              "120d hasn't gone negative. If the edge lives in only one half or has "
              "died recently, it's a regime artifact — do NOT build a live signal; "
              "at most paper-track. If the `dir` (XRP-only) variant also holds, the "
              "edge is executable without a short-BTC leg.")
    md.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
