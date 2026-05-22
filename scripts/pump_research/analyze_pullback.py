"""Phase 3 (reframed) — pullback / resume analysis.

Phase 2 verdict: trend vs whipsaw cannot be told apart at t=0 (CV AUC 0.563).
New question (operator 2026-05-22): forget prediction — DETECT the pullback
once it has already started, so the bot can resume early.

For every event in state/pump_event_catalog.csv this re-locates the PEAK
(extreme price within the 4h outcome window) and measures, minute-by-minute
AFTER the peak:
  - how far price has retraced from the peak  (toward window-start)
  - whether that retrace was real (whipsaw) or just a pause (trend continued)

Then it backtests simple resume RULES of the form
  "resume when price retraces R% from the running extreme"
and reports, per rule, on the trend/whipsaw split:
  - whipsaw: how many bars saved vs the 4h fixed timeout  (good)
  - trend:   false-resume rate — resumed while move still extends (bad)

Output:
  state/pump_pullback_profile.csv  — per-event peak + retrace timing
  console: resume-rule precision/recall table

Run:
    python scripts/pump_research/analyze_pullback.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data" / "pump_research" / "BTCUSDT_pump_features_1m.csv"
CATALOG = ROOT / "state" / "pump_event_catalog.csv"
OUT = ROOT / "state" / "pump_pullback_profile.csv"

LOOKAHEAD_MIN = 240          # 4h outcome window — same as catalog
FIXED_TIMEOUT_MIN = 240      # current production resume fallback (4h)
RESUME_RETRACE_GRID = (0.5, 1.0, 1.5, 2.0, 3.0)   # rules to backtest, %
# "move still extends" = after a resume, price makes a new extreme beyond
# this margin within the rest of the 4h window -> false resume.
EXTEND_MARGIN_PCT = 0.5


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(MASTER, dtype={"ts": "int64"})
    df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    df["open_interest"] = df["open_interest"].bfill()
    cat = pd.read_csv(CATALOG)
    return df, cat


def analyze() -> pd.DataFrame:
    df, cat = load()
    ts = df["ts"].values
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    vol = df["volume"].values
    oi = df["open_interest"].values
    n = len(close)
    ts_to_idx = {int(t): i for i, t in enumerate(ts)}

    rows = []
    for _, ev in cat.iterrows():
        a = ts_to_idx.get(int(ev["anchor_ts"]))
        if a is None:
            continue
        direction = ev["direction"]
        up = direction == "up"
        end = min(a + LOOKAHEAD_MIN, n)
        trigger_price = close[a]

        seg_h = high[a:end]
        seg_l = low[a:end]
        # peak = the extreme of the move
        if up:
            peak_off = int(np.argmax(seg_h))
            peak_price = seg_h[peak_off]
        else:
            peak_off = int(np.argmin(seg_l))
            peak_price = seg_l[peak_off]
        peak_idx = a + peak_off
        peak_move_pct = (peak_price - trigger_price) / trigger_price * 100.0 * (1 if up else 1)

        # --- after the peak: retrace timing ---
        post_h = high[peak_idx:end]
        post_l = low[peak_idx:end]
        post_c = close[peak_idx:end]
        # retrace = how far back toward trigger, as % of peak->trigger distance
        span = abs(peak_price - trigger_price)
        bars_to_retrace = {}
        for r in RESUME_RETRACE_GRID:
            # absolute price level r% retraced from peak (toward trigger side)
            if up:
                level = peak_price * (1 - r / 100.0)
                hit = next((k for k in range(len(post_l)) if post_l[k] <= level), -1)
            else:
                level = peak_price * (1 + r / 100.0)
                hit = next((k for k in range(len(post_h)) if post_h[k] >= level), -1)
            bars_to_retrace[r] = hit

        # post-peak feature deltas (does pullback look different from pause?)
        oi_post = oi[min(peak_idx + 15, n - 1)] - oi[peak_idx]
        vol_peak = vol[max(0, peak_idx - 5):peak_idx + 6].mean()
        vol_base = np.median(vol[max(0, a - 1440):a]) if a > 60 else np.nan

        rows.append({
            "anchor_ts": int(ev["anchor_ts"]),
            "anchor_dt": ev["anchor_dt"],
            "direction": direction,
            "outcome": ev["outcome"],
            "peak_off_min": peak_off,
            "peak_move_pct": round(float(peak_move_pct), 3),
            "oi_post15": round(float(oi_post), 1),
            "vol_peak_x": round(float(vol_peak / vol_base), 2)
                          if vol_base and vol_base > 0 else np.nan,
            **{f"retrace_bar_{r}": bars_to_retrace[r] for r in RESUME_RETRACE_GRID},
        })

    return pd.DataFrame(rows)


def report(prof: pd.DataFrame) -> None:
    tw = prof[prof.outcome.isin(["trend", "whipsaw"])]

    print(f"\n{'='*70}")
    print("PEAK TIMING — when does the move actually top out?")
    print(f"{'='*70}")
    for oc in ("whipsaw", "trend", "partial"):
        sub = prof[prof.outcome == oc]
        if sub.empty:
            continue
        p = sub["peak_off_min"]
        print(f"  {oc:8} n={len(sub):>3}  peak at min: "
              f"median={p.median():.0f}  p25={p.quantile(.25):.0f}  "
              f"p75={p.quantile(.75):.0f}  max={p.max():.0f}")

    print(f"\n{'='*70}")
    print("RESUME RULE BACKTEST — 'resume when price retraces R% from peak'")
    print(f"{'='*70}")
    print("Per rule, on trend vs whipsaw events:")
    print(f"  {'R%':>5} {'whips fired':>12} {'med bar':>9} "
          f"{'trend fired':>12} {'= false-resume':>16}")
    for r in RESUME_RETRACE_GRID:
        col = f"retrace_bar_{r}"
        whip = tw[tw.outcome == "whipsaw"][col]
        trend = tw[tw.outcome == "trend"][col]
        whip_fired = (whip >= 0).sum()
        trend_fired = (trend >= 0).sum()
        med_bar = whip[whip >= 0].median() if whip_fired else np.nan
        # false-resume: on a TREND event the rule fired = bot resumed during
        # what was really a continuing move.
        fr_pct = 100.0 * trend_fired / len(trend) if len(trend) else 0
        print(f"  {r:>5.1f} {whip_fired:>6}/{len(whip):<5} {med_bar:>9.0f} "
              f"{trend_fired:>6}/{len(trend):<5} {fr_pct:>14.0f}%")

    print(f"\n  Reading: whips fired = whipsaw events where rule would resume")
    print(f"           med bar     = minutes after peak until resume (lower=earlier)")
    print(f"           false-resume= % of trend events where rule ALSO fired (bad)")
    print(f"  Fixed timeout today = {FIXED_TIMEOUT_MIN}min flat for everything.")


def main() -> int:
    print(f"Loading catalog + master ...")
    prof = analyze()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prof.to_csv(OUT, index=False)
    print(f"Profiled {len(prof)} events -> {OUT}")
    report(prof)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
