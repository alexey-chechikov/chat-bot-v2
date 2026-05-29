"""Alt↔BTC decorrelation edge research (25m & 1h).

Operator ask (2026-05-29): trade alts when they DEcorrelate from BTC, on 25m/1h.
Before wiring any signal/TV alert, prove whether decorrelation predicts anything.

Definition: relative-strength spread over a lookback K bars:
    spread_K = (alt %chg over K) − (btc %chg over K)
A large |spread_K| = the alt has decoupled from BTC (out/under-performing). We
also track rolling return-correlation to confirm it's a genuine decorrelation
regime, not just both moving together.

Question tested two ways on the ALT's own forward return over M bars:
  • CONTINUATION: trade in the direction of the divergence (alt strong → long alt)
  • REVERSION:    trade against it (alt strong → short alt, expecting catch-down)
Plus a beta-neutral leg (alt vs BTC) so the edge isn't just "alt beta in a
trending tape". Net of fees (linear taker 0.15% RT).

2 years of 1m for BTC/ETH/XRP → resampled to 25m and 1h. Large n.

Output: docs/STRATEGIES/ALT_DECORRELATION_RESEARCH.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools._gc_down_diagnostic import _load_1m, BTC_1M, ETH_1M, XRP_1M  # noqa: E402

OUT_MD = ROOT / "docs" / "STRATEGIES" / "ALT_DECORRELATION_RESEARCH.md"
FEES_RT = 0.15

# (timeframe rule, K lookback bars, M forward bars, corr window bars)
CONFIGS = [
    ("25min", 6, 4, 24),   # 25m: 2.5h divergence window, ~1.7h forward
    ("25min", 12, 8, 24),
    ("1h", 6, 4, 30),      # 1h: 6h divergence, 4h forward
    ("1h", 12, 6, 30),
]
ALTS = {"ETHUSDT": ETH_1M, "XRPUSDT": XRP_1M}


def _resample(df1m, rule):
    return (df1m.set_index("ts").resample(rule)
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"}).dropna())


def _stats(rets):
    rets = [r for r in rets if r is not None and not np.isnan(r)]
    n = len(rets)
    if not n:
        return None
    arr = np.array(rets)
    wins = arr[arr > 0]
    losses = -arr[arr < 0]
    pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else 999.0
    # t-stat of mean (edge significance)
    t = (arr.mean() / (arr.std(ddof=1) / np.sqrt(n))) if n > 1 and arr.std() > 0 else 0.0
    return {"n": n, "wr": round((arr > 0).mean() * 100, 1),
            "mean": round(arr.mean(), 4), "pf": round(pf, 2),
            "sum": round(arr.sum(), 1), "t": round(t, 2)}


def main() -> int:
    btc1m = _load_1m(BTC_1M)
    md = ["# Alt↔BTC decorrelation edge research", ""]
    md.append(f"2y 1m → resampled. spread_K = altΔ% − btcΔ% over K bars. Event = "
              f"|spread_K| in top/bottom tercile. Forward = ALT raw return over M "
              f"bars, fees {FEES_RT}% RT. **t** = t-stat of mean net return "
              "(|t|>2 ≈ significant). CONT = trade with divergence; REV = against.")
    md.append("")

    for alt, altpath in ALTS.items():
        alt1m = _load_1m(altpath)
        md.append(f"## {alt}")
        md.append("")
        md.append("| TF | K/M | event | n | CONT WR% | CONT mean% | CONT PF | CONT t | "
                  "REV mean% | REV t | corr@event |")
        md.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for rule, K, M, cw in CONFIGS:
            b = _resample(btc1m, rule)
            a = _resample(alt1m, rule)
            j = pd.DataFrame({"b": b["close"], "a": a["close"]}).dropna()
            if len(j) < cw + K + M + 50:
                continue
            bc = j["b"].to_numpy(float)
            ac = j["a"].to_numpy(float)
            br = np.diff(np.log(bc))
            ar = np.diff(np.log(ac))
            # align: index i in returns corresponds to bar i+1
            n = len(br)
            # rolling corr of returns over cw
            spread = np.full(n, np.nan)
            fwd = np.full(n, np.nan)
            corr = np.full(n, np.nan)
            for i in range(K, n - M):
                spK = (ac[i] / ac[i - K] - 1.0) - (bc[i] / bc[i - K] - 1.0)
                spread[i] = spK * 100.0
                fwd[i] = (ac[i + M] / ac[i] - 1.0) * 100.0
                if i >= cw:
                    cseg_a = ar[i - cw:i]
                    cseg_b = br[i - cw:i]
                    if cseg_a.std() > 0 and cseg_b.std() > 0:
                        corr[i] = np.corrcoef(cseg_a, cseg_b)[0, 1]
            valid = ~np.isnan(spread) & ~np.isnan(fwd)
            sp = spread[valid]
            fw = fwd[valid]
            cr = corr[valid]
            if len(sp) < 100:
                continue
            hi_th = np.nanpercentile(sp, 66)
            lo_th = np.nanpercentile(sp, 34)
            # decorrelation UP event: alt outperformed (spread high)
            for evlabel, mask in [
                ("alt≫btc (up div)", sp >= hi_th),
                ("alt≪btc (dn div)", sp <= lo_th),
            ]:
                fwe = fw[mask]
                cre = cr[mask]
                # CONT: up-div → long alt (fwd as-is); dn-div → short alt (−fwd)
                sign = 1.0 if "up" in evlabel else -1.0
                cont = [sign * r - FEES_RT for r in fwe]
                rev = [-sign * r - FEES_RT for r in fwe]
                sc = _stats(cont)
                sr = _stats(rev)
                if not sc:
                    continue
                cavg = round(np.nanmean(cre), 2) if len(cre) else float("nan")
                md.append(f"| {rule} | {K}/{M} | {evlabel} | {sc['n']} | {sc['wr']} | "
                          f"{sc['mean']:+.3f} | {sc['pf']} | {sc['t']} | "
                          f"{sr['mean']:+.3f} | {sr['t']} | {cavg} |")
        md.append("")

    md.append("## How to read")
    md.append("")
    md.append("- A real edge = CONT or REV mean% clearly >0 with **|t|>2** and PF>1.2 "
              "on large n. If both CONT and REV hover near 0 with |t|<2, decorrelation "
              "carries no directional edge at that horizon.")
    md.append("- Low corr@event confirms the signal fired in genuine decoupling.")
    md.append("- Next step depends on the verdict: if CONT wins → momentum-follow the "
              "diverging alt; if REV wins → fade the divergence (pairs/mean-revert to BTC).")
    md.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
