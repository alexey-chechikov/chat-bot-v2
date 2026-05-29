"""Alt↔BTC decorrelation v2 — beta-NEUTRAL pairs + extreme tail + low-corr.

v1 (_alt_decorrelation_research.py) showed the naive "trade the alt outright
after a tercile divergence" has no edge (raw alt return is dominated by BTC beta).
v2 tests the FAITHFUL decorrelation trade:

  residual_t = altRet_t − beta·btcRet_t           (beta = rolling cov/var, cw bars)
  cum_resid_K = Σ residual over last K bars         (how far the alt decoupled)
  event = cum_resid_K in an EXTREME tail (top/bottom 10% and 5%)
  forward = beta-neutral pairs PnL over next M bars:
            (alt logret M) − beta·(btc logret M)    -- long alt / short beta·BTC
  REV = bet the residual reverts (decoupled-up → short the spread); CONT = persist.

Fees: 2 legs → 0.30% RT. Also split by rolling corr (<0.5 = genuine decouple).

Output: docs/STRATEGIES/ALT_DECORRELATION_V2.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools._gc_down_diagnostic import _load_1m, BTC_1M, ETH_1M, XRP_1M  # noqa: E402

OUT_MD = ROOT / "docs" / "STRATEGIES" / "ALT_DECORRELATION_V2.md"
FEES_RT_PAIRS = 0.30  # two legs

CONFIGS = [("25min", 12, 8, 24), ("1h", 12, 6, 30), ("1h", 24, 8, 40)]
ALTS = {"ETHUSDT": ETH_1M, "XRPUSDT": XRP_1M}


def _resample(df1m, rule):
    return (df1m.set_index("ts").resample(rule)
            .agg({"close": "last"}).dropna())


def _stats(rets):
    arr = np.array([r for r in rets if r is not None and not np.isnan(r)])
    n = len(arr)
    if not n:
        return None
    wins = arr[arr > 0]; losses = -arr[arr < 0]
    pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else 999.0
    t = (arr.mean() / (arr.std(ddof=1) / np.sqrt(n))) if n > 1 and arr.std() > 0 else 0.0
    return {"n": n, "wr": round((arr > 0).mean()*100, 1), "mean": round(arr.mean(), 4),
            "pf": round(pf, 2), "t": round(t, 2)}


def main() -> int:
    btc1m = _load_1m(BTC_1M)
    md = ["# Alt↔BTC decorrelation v2 — beta-neutral pairs", ""]
    md.append(f"Beta-neutral pairs PnL (long alt / short beta·BTC), fees "
              f"{FEES_RT_PAIRS}% RT (2 legs). Event = cum residual in EXTREME tail. "
              "REV = bet spread reverts; CONT = persists. **t**=t-stat (|t|>2 sig).")
    md.append("")
    for alt, altpath in ALTS.items():
        alt1m = _load_1m(altpath)
        md.append(f"## {alt}")
        md.append("")
        md.append("| TF | K/M | tail | corr filt | n | REV WR% | REV mean% | REV PF | REV t | "
                  "CONT mean% | CONT t |")
        md.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
        for rule, K, M, cw in CONFIGS:
            j = pd.DataFrame({"b": _resample(btc1m, rule)["close"],
                              "a": _resample(alt1m, rule)["close"]}).dropna()
            if len(j) < cw + K + M + 100:
                continue
            bc = j["b"].to_numpy(float); ac = j["a"].to_numpy(float)
            br = np.diff(np.log(bc)); ar = np.diff(np.log(ac))
            n = len(br)
            beta = np.full(n, np.nan); resid = np.full(n, np.nan)
            cumK = np.full(n, np.nan); fwd = np.full(n, np.nan); corr = np.full(n, np.nan)
            for i in range(cw, n - M):
                bseg = br[i-cw:i]; aseg = ar[i-cw:i]
                var = bseg.var()
                bta = (np.cov(aseg, bseg)[0, 1] / var) if var > 0 else 1.0
                beta[i] = bta
                if bseg.std() > 0 and aseg.std() > 0:
                    corr[i] = np.corrcoef(aseg, bseg)[0, 1]
                if i >= cw + K:
                    # cumulative residual over last K (beta held at current bta)
                    cumK[i] = (np.sum(ar[i-K:i]) - bta*np.sum(br[i-K:i])) * 100.0
                # forward beta-neutral pairs return over M
                fwd[i] = (np.sum(ar[i:i+M]) - bta*np.sum(br[i:i+M])) * 100.0
            valid = ~np.isnan(cumK) & ~np.isnan(fwd)
            ck = cumK[valid]; fw = fwd[valid]; cr = corr[valid]
            if len(ck) < 200:
                continue
            for tail_lbl, qlo, qhi in [("10%", 10, 90), ("5%", 5, 95)]:
                hi = np.nanpercentile(ck, qhi); lo = np.nanpercentile(ck, qlo)
                for corr_lbl, cmask in [("all", np.ones(len(ck), bool)),
                                        ("corr<0.5", cr < 0.5)]:
                    up = (ck >= hi) & cmask   # alt decoupled UP
                    dn = (ck <= lo) & cmask   # alt decoupled DOWN
                    # REV: up-decouple → short spread (−fwd); dn → long spread (+fwd)
                    rev = ([-r - FEES_RT_PAIRS for r in fw[up]] +
                           [r - FEES_RT_PAIRS for r in fw[dn]])
                    cont = ([r - FEES_RT_PAIRS for r in fw[up]] +
                            [-r - FEES_RT_PAIRS for r in fw[dn]])
                    sr = _stats(rev); sc = _stats(cont)
                    if not sr:
                        continue
                    md.append(f"| {rule} | {K}/{M} | {tail_lbl} | {corr_lbl} | {sr['n']} | "
                              f"{sr['wr']} | {sr['mean']:+.3f} | {sr['pf']} | {sr['t']} | "
                              f"{sc['mean']:+.3f} | {sc['t']} |")
        md.append("")

    md.append("## Verdict guide")
    md.append("")
    md.append("Edge exists only if REV (or CONT) mean% > 0 with **|t|>2** and PF>1.2 "
              "AFTER the 0.30% pairs fee — especially in the `corr<0.5` rows (genuine "
              "decoupling). If everything stays ≤0 / |t|<2, the decorrelation pairs "
              "trade has no exploitable edge at these horizons and we should NOT build it.")
    md.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
