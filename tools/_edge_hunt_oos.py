"""Edge hunt with out-of-sample rigour — 3 families.

Operator: "bring me a clear, reliable, CONSTANT edge." So every candidate is
split year1 / year2 / last-120d. An edge counts ONLY if it stays positive with
|t|>2 across both halves AND hasn't died recently. Fees 0.15% RT directional.

A) SESSION  — hour-of-day directional bias in BTC (1h bars).
B) LEAD-LAG — does XRP/ETH lead BTC? big alt move at t -> BTC move t+1..M.
C) FUNDING  — funding-rate extremes -> forward BTC move (fade vs follow).

Output: docs/STRATEGIES/EDGE_HUNT_OOS.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools._gc_down_diagnostic import _load_1m, BTC_1M, ETH_1M, XRP_1M  # noqa: E402

OUT_MD = ROOT / "docs" / "STRATEGIES" / "EDGE_HUNT_OOS.md"
FEE = 0.15
COMBINED = ROOT / "data" / "historical" / "binance_combined_BTCUSDT.parquet"


def _res(df1m, rule):
    return df1m.set_index("ts").resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def _st(arr):
    arr = np.asarray([x for x in arr if x is not None and not np.isnan(x)])
    n = len(arr)
    if n < 5:
        return None
    t = (arr.mean()/(arr.std(ddof=1)/np.sqrt(n))) if arr.std() > 0 else 0.0
    w = arr[arr > 0]; l = -arr[arr < 0]
    pf = (w.sum()/l.sum()) if l.sum() > 0 else 999.0
    return {"n": n, "wr": round((arr > 0).mean()*100, 1), "mean": round(arr.mean(), 4),
            "pf": round(pf, 2), "t": round(t, 2)}


def _oos_rows(ts, rets, label):
    """Return md rows for FULL / 1st half / 2nd half / last120d of (ts, rets)."""
    ts = np.asarray(ts); rets = np.asarray(rets)
    order = np.argsort(ts); ts = ts[order]; rets = rets[order]
    half = len(ts)//2
    cut = ts[-1] - np.timedelta64(120, "D")
    segs = {"FULL": np.ones(len(ts), bool),
            "y1": np.arange(len(ts)) < half,
            "y2": np.arange(len(ts)) >= half,
            "last120d": ts >= cut}
    out = []
    for seg, m in segs.items():
        s = _st(rets[m])
        if s:
            out.append(f"| {label} | {seg} | {s['n']} | {s['wr']} | {s['mean']:+.3f} | "
                       f"{s['pf']} | {s['t']} |")
    return out


def main() -> int:
    btc1m = _load_1m(BTC_1M)
    md = ["# Edge hunt — out-of-sample (3 families)", ""]
    md.append(f"Fees {FEE}% RT. Edge = positive mean with |t|>2 in BOTH y1 & y2 and "
              "not dead in last120d. **t**=t-stat of mean net return.")
    md.append("")

    # ───────────────────────── A) SESSION ──────────────────────────────────
    md.append("## A) Session / hour-of-day (BTC 1h, forward 4h, LONG bias)")
    md.append("")
    md.append("Per UTC entry-hour: go LONG, hold 4h. Looking for hours with a "
              "persistent directional bias across both halves.")
    md.append("")
    b1h = _res(btc1m, "1h")
    cl = b1h["close"].to_numpy(float)
    idx = b1h.index.to_numpy()
    hours = b1h.index.hour.to_numpy()
    M = 4
    fwd = np.full(len(cl), np.nan)
    for i in range(len(cl)-M):
        fwd[i] = (cl[i+M]/cl[i]-1.0)*100.0 - FEE
    md.append("| hour | seg | n | WR% | mean% | PF | t |")
    md.append("|---|---|---:|---:|---:|---:|---:|")
    # rank hours by FULL |t|, show top 4
    hour_t = []
    for h in range(24):
        m = (hours == h) & ~np.isnan(fwd)
        s = _st(fwd[m])
        if s:
            hour_t.append((abs(s["t"]), h, s["t"]))
    hour_t.sort(reverse=True)
    for _, h, _tt in hour_t[:4]:
        m = (hours == h) & ~np.isnan(fwd)
        for row in _oos_rows(idx[m], fwd[m], f"{h:02d}h UTC"):
            md.append(row)
    md.append("")

    # ───────────────────────── B) LEAD-LAG ─────────────────────────────────
    md.append("## B) Lead-lag — does the alt lead BTC? (1h)")
    md.append("")
    md.append("At each bar, if the ALT had a big move over last 3h (top/bottom decile), "
              "trade BTC in the SAME direction for next M=3h. Edge => alt leads BTC.")
    md.append("")
    md.append("| pair | seg | n | WR% | mean% | PF | t |")
    md.append("|---|---|---:|---:|---:|---:|---:|")
    for alt, altpath in (("XRP", XRP_1M), ("ETH", ETH_1M)):
        a1h = _res(_load_1m(altpath), "1h")
        j = pd.DataFrame({"b": b1h["close"], "a": a1h["close"]}).dropna()
        ts = j.index.to_numpy()
        bc = j["b"].to_numpy(float); ac = j["a"].to_numpy(float)
        K = 3; Mp = 3
        amove = np.full(len(ac), np.nan); bfwd = np.full(len(ac), np.nan)
        for i in range(K, len(ac)-Mp):
            amove[i] = (ac[i]/ac[i-K]-1.0)*100.0
            bfwd[i] = (bc[i+Mp]/bc[i]-1.0)*100.0
        valid = ~np.isnan(amove) & ~np.isnan(bfwd)
        am = amove[valid]; bf = bfwd[valid]; tsv = ts[valid]
        hi = np.nanpercentile(am, 90); lo = np.nanpercentile(am, 10)
        # CONT direction: alt up-decile -> long BTC (+bf-fee); alt dn-decile -> short (-bf-fee)
        sel = (am >= hi) | (am <= lo)
        sgn = np.where(am[sel] >= hi, 1.0, -1.0)
        pnl = sgn*bf[sel] - FEE
        for row in _oos_rows(tsv[sel], pnl, f"{alt}→BTC"):
            md.append(row)
    md.append("")

    # ───────────────────────── C) FUNDING ──────────────────────────────────
    md.append("## C) Funding-rate extremes → forward BTC (fade & follow)")
    md.append("")
    try:
        cdf = pd.read_parquet(COMBINED)
        cdf["ts"] = pd.to_datetime(cdf["ts_ms"], unit="ms", utc=True)
        cdf = cdf.dropna(subset=["funding_rate_8h"]).sort_values("ts")
        # map price at each funding ts and forward over next 24h (3 periods)
        bidx = btc1m.set_index("ts")["close"].sort_index()
        f_ts = cdf["ts"].to_numpy()
        f_val = cdf["funding_rate_8h"].to_numpy(float)
        px_ts = bidx.index.to_numpy()
        px = bidx.to_numpy(float)
        fwdh = 24
        rows_ts = []; rows_fade = []; rows_follow = []
        funhi = np.nanpercentile(f_val, 90); funlo = np.nanpercentile(f_val, 10)
        for k in range(len(f_ts)):
            fv = f_val[k]
            if not (fv >= funhi or fv <= funlo):
                continue
            p0i = np.searchsorted(px_ts, f_ts[k], side="left")
            tgt = f_ts[k] + np.timedelta64(fwdh, "h")
            p1i = np.searchsorted(px_ts, tgt, side="left")
            if p0i >= len(px) or p1i >= len(px):
                continue
            ret = (px[p1i]/px[p0i]-1.0)*100.0
            # high funding = longs crowded -> FADE = short (-ret); FOLLOW = +ret
            sgn_fade = -1.0 if fv >= funhi else 1.0
            rows_ts.append(f_ts[k])
            rows_fade.append(sgn_fade*ret - FEE)
            rows_follow.append(-sgn_fade*ret - FEE)
        md.append(f"Funding extremes (top/bottom decile), forward {fwdh}h. "
                  "FADE = trade against the crowded side; FOLLOW = with it.")
        md.append("")
        md.append("| variant | seg | n | WR% | mean% | PF | t |")
        md.append("|---|---|---:|---:|---:|---:|---:|")
        for row in _oos_rows(rows_ts, rows_fade, "FADE"):
            md.append(row)
        for row in _oos_rows(rows_ts, rows_follow, "FOLLOW"):
            md.append(row)
    except Exception as e:
        md.append(f"_funding analysis failed: {e}_")
    md.append("")

    md.append("## Verdict")
    md.append("")
    md.append("Scan the y1 AND y2 rows of each block. A keeper has the SAME sign, "
              "mean>0, |t|>2 in both halves, and last120d not negative. Anything "
              "positive only in FULL or one half is a regime artifact — do not build.")
    md.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
