"""GC UP-exhaustion — diagnostic backtest (live-faithful 22d window).

Follow-up to GC_DOWN_DIAGNOSTIC (2026-05-29): the DOWN side turned out to be a
continuation signal, not a reversal. This checks whether UP is the same, with
the SAME slicing the down tool used (score / regime / corr / core-signal) plus a
gate search, the unconditional baseline control, and a data-driven verdict.

UP-exhaustion currently advises closing SHORT grids and paper-emits a SHORT
(fade the top). If UP is actually a CONTINUATION signal, the +EV trade is a
LONG and the card should be re-framed «🔝 ВЕРХ — ИМПУЛЬС ВВЕРХ».

Reuses the down harness primitives. For the UP side:
  fade trade (current live emit) = SHORT: stop +0.5%, tp -0.75%, 4h (_short_outcome)
  continuation trade (proposed)  = LONG : stop -0.5%, tp +0.75%, 4h (_trade_outcome)

UP fires only on the 1h main loop (threshold score>=3); there is no 15m up loop
(the intraday loop is downside-only), so this tool is 1h-only.

REGIME CAVEAT: the 22d window was net-BEARISH. An up-continuation edge has to
swim against the prevailing drift, so it is expected to look weaker / more
regime-contingent than the down-continuation edge did, and the unconditional
LONG base rate is poor by construction. The verdict is computed from the data
and flags WEAK / INCONCLUSIVE honestly.

Output: docs/STRATEGIES/GC_UP_DIAGNOSTIC.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.grid_coordinator.loop import evaluate_exhaustion  # noqa: E402
from core.orchestrator.regime_classifier import calc_adx  # noqa: E402
# reuse the down-diagnostic primitives (data load, trade sims, stats)
from tools._gc_down_diagnostic import (  # noqa: E402
    _load_1m, _resample, _load_deriv_hist, TFView,
    _trade_outcome, _short_outcome, _fwd_raw, _stats, _dedup,
    HOLD_H, FEES_RT_PCT, STOP_PCT, TP_PCT, BTC_1M, ETH_1M, XRP_1M,
)

OUT_MD = ROOT / "docs" / "STRATEGIES" / "GC_UP_DIAGNOSTIC.md"
TH_1H = 3  # up fires on 1h main loop at score>=3


def main() -> int:
    print("[up] loading deriv history...")
    deriv = _load_deriv_hist()
    start, end = deriv.ts.min(), deriv.ts.max()
    print(f"  {len(deriv)} snapshots  {start} -> {end}")

    print("[up] loading 1m + resampling 1h...")
    btc1m = _load_1m(BTC_1M)
    eth1m = _load_1m(ETH_1M)
    xrp1m = _load_1m(XRP_1M)
    btc_1h = TFView(_resample(btc1m, "1h"))
    eth_1h = TFView(_resample(eth1m, "1h"))
    xrp_1h = TFView(_resample(xrp1m, "1h"))

    b1 = btc1m.sort_values("ts")
    c_ts = b1["ts"].astype("int64").to_numpy()
    c_hi = b1["high"].to_numpy(dtype=float)
    c_lo = b1["low"].to_numpy(dtype=float)
    c_cl = b1["close"].to_numpy(dtype=float)

    # window-level net BTC drift (regime context)
    p_lo = int(np.searchsorted(c_ts, start.value, side="left"))
    p_hi = min(int(np.searchsorted(c_ts, min(end, b1["ts"].max()).value,
                                   side="left")), len(c_cl) - 1)
    net_drift = ((c_cl[p_hi] / c_cl[p_lo] - 1.0) * 100.0) if p_hi > p_lo else 0.0

    if end > b1["ts"].max():
        print(f"  NOTE: price ends {b1['ts'].max()}, deriv ends {end}; "
              "fires past price-end get no forward outcome.")

    rows = []
    for _, drow in deriv.iterrows():
        ts = drow["ts"]
        deriv_dict = {"BTCUSDT": {
            "oi_change_1h_pct": drow.get("oi_change_1h_pct") or 0,
            "funding_rate_8h": drow.get("funding_rate_8h") or 0,
        }}
        bwin = btc_1h.window_before(ts, 50)
        if len(bwin) < 35:
            continue
        ev = evaluate_exhaustion(bwin, eth_1h.window_before(ts, 50),
                                 deriv_dict, xrp=xrp_1h.window_before(ts, 50))
        det = ev.get("details") or {}
        us = det.get("up_signals") or {}
        up = ev.get("upside_score", 0)
        if up < 3:
            continue
        h1 = btc_1h.window_before(ts, 60)
        adx = ret24 = 0.0
        if len(h1) >= 32:
            candles = [{"high": r.high, "low": r.low, "close": r.close}
                       for r in h1.itertuples()]
            adx, _ = calc_adx(candles)
            ret24 = (float(h1["close"].iloc[-1]) /
                     float(h1["close"].iloc[-25]) - 1.0) * 100.0
        rows.append({
            "ts": ts, "score": up,
            "fade_pnl": _short_outcome(c_ts, c_hi, c_lo, c_cl, ts),   # SHORT (current)
            "cont_pnl": _trade_outcome(c_ts, c_hi, c_lo, c_cl, ts),   # LONG (mirror)
            "fwd1": _fwd_raw(c_ts, c_cl, ts, 60),
            "fwd4": _fwd_raw(c_ts, c_cl, ts, 240),
            "fwd8": _fwd_raw(c_ts, c_cl, ts, 480),
            "corr": det.get("btc_eth_corr_30h") or 0.0,
            "mfi_high": bool(us.get("mfi_high")),
            "vol_spike": bool(us.get("volume_spike_at_high")),
            "rsi_high": bool(us.get("rsi_high")),
            "eth_sync": bool(us.get("eth_sync_high")),
            "xrp_mfi": bool(us.get("xrp_mfi_high")),
            "delev": bool(us.get("deleverage_or_funding_top")),
            "adx": adx, "ret24": ret24,
        })

    valid = [r for r in rows if r["fade_pnl"] is not None and r["cont_pnl"] is not None]
    print(f"[up] candidate fires (score>=3): {len(rows)}  (with outcome: {len(valid)})")

    md = []
    md.append("# GC UP-exhaustion — diagnostic backtest")
    md.append("")
    md.append(f"**Window:** {start} -> {end}  "
              f"({(end-start).total_seconds()/86400:.1f}d, live-faithful)")
    md.append(f"**Feed:** state/deriv_live_history.jsonl ({len(deriv)} snapshots, ~5min)")
    md.append(f"**Window net BTC drift:** {net_drift:+.1f}%  "
              "(regime context — see caveat)")
    md.append(f"**FADE trade (current live emit):** SHORT entry@close, "
              f"stop +{-STOP_PCT}%, tp -{TP_PCT}%, hold {HOLD_H}h, fees {FEES_RT_PCT}% RT")
    md.append(f"**CONTINUATION trade (proposed mirror):** LONG entry@close, "
              f"stop {STOP_PCT}%, tp +{TP_PCT}%, hold {HOLD_H}h, fees {FEES_RT_PCT}% RT")
    md.append("")
    md.append("`ev` = net expectancy %/trade after fees. `sum` = total net %. "
              "**Deduped** = non-overlapping 4h trades (independent edge). UP fires "
              "on the **1h main loop only** (score>=3); the 15m intraday loop is "
              "downside-only, so there is no 15m UP path. Mirror of "
              "`GC_DOWN_DIAGNOSTIC.md`.")
    md.append("")

    # ── 1. Fade vs Continuation by score ────────────────────────────────────
    md.append("## Fade (current SHORT) vs Continuation (LONG) — by score, deduped")
    md.append("")
    md.append("| score | n | FADE WR% | FADE EV% | FADE PF | CONT WR% | CONT EV% | CONT PF |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    cont_by_score = {}
    for s in (3, 4, 5, 6):
        sub = _dedup([r for r in valid if r["score"] >= s], HOLD_H)
        if not sub:
            continue
        f = _stats([r["fade_pnl"] for r in sub])
        c = _stats([r["cont_pnl"] for r in sub])
        cont_by_score[s] = c
        md.append(f"| >={s} | {f['n']} | {f['wr']} | {f['ev']:+.3f} | {f['pf']} | "
                  f"{c['wr']} | {c['ev']:+.3f} | {c['pf']} |")
    md.append("")

    # ── 2. Slices (regime / corr / core) — both fade and continuation ───────
    md.append("## Slices (score>=3, deduped) — regime / corr / core signal")
    md.append("")
    md.append("Same slicing the DOWN diagnostic used. FADE = current SHORT emit; "
              "CONT = LONG mirror. A continuation edge shows CONT beating FADE "
              "(and ideally the baseline) within each favorable slice.")
    md.append("")
    md.append("| slice | n | FADE WR% | FADE EV% | CONT WR% | CONT EV% | CONT PF |")
    md.append("|---|---:|---:|---:|---:|---:|---:|")
    live = [r for r in valid if r["score"] >= TH_1H]

    def slice_row(label, subset):
        ded = _dedup(subset, HOLD_H)
        if not ded:
            md.append(f"| {label} | 0 | — | — | — | — | — |")
            return
        f = _stats([r["fade_pnl"] for r in ded])
        c = _stats([r["cont_pnl"] for r in ded])
        md.append(f"| {label} | {f['n']} | {f['wr']} | {f['ev']:+.3f} | "
                  f"{c['wr']} | {c['ev']:+.3f} | {c['pf']} |")

    slice_row("ADX < 20 (range)", [r for r in live if r["adx"] < 20])
    slice_row("ADX 20-25", [r for r in live if 20 <= r["adx"] < 25])
    slice_row("ADX >= 25 (trend)", [r for r in live if r["adx"] >= 25])
    slice_row("uptrend (ret24h>+1%)", [r for r in live if r["ret24"] > 1])
    slice_row("ADX>=25 AND uptrend", [r for r in live
                                      if r["adx"] >= 25 and r["ret24"] > 1])
    slice_row("NOT(ADX>=25 & uptrend)", [r for r in live
                                         if not (r["adx"] >= 25 and r["ret24"] > 1)])
    slice_row("corr > 0.95", [r for r in live if r["corr"] > 0.95])
    slice_row("corr <= 0.95", [r for r in live if r["corr"] <= 0.95])
    slice_row("core present (mfi_high|vol)", [r for r in live
                                              if r["mfi_high"] or r["vol_spike"]])
    slice_row("core ABSENT", [r for r in live
                              if not (r["mfi_high"] or r["vol_spike"])])
    md.append("")

    # ── 3. Gate search on the FADE: can the current SHORT be salvaged? ──────
    md.append("## Gate search — can the FADE (SHORT) be salvaged? (deduped)")
    md.append("")
    md.append("| gate | n | WR% | EV% | PF | sum% |")
    md.append("|---|---:|---:|---:|---:|---:|")
    gates = {
        "score>=3 (baseline)": lambda r: r["score"] >= 3,
        "score>=4": lambda r: r["score"] >= 4,
        "score>=5": lambda r: r["score"] >= 5,
        "score>=3 + core": lambda r: r["score"] >= 3 and (r["mfi_high"] or r["vol_spike"]),
        "score>=3 + uptrend": lambda r: r["score"] >= 3 and r["ret24"] > 1,
        "score>=3 + corr<=0.95": lambda r: r["score"] >= 3 and r["corr"] <= 0.95,
        "score>=4 + core": lambda r: r["score"] >= 4 and (r["mfi_high"] or r["vol_spike"]),
    }
    for name, fn in gates.items():
        ded = _dedup([r for r in valid if fn(r)], HOLD_H)
        st = _stats([r["fade_pnl"] for r in ded])
        md.append(f"| {name} | {st['n']} | {st['wr']} | {st['ev']:+.3f} | "
                  f"{st['pf']} | {st['sum']:+.1f} |")
    md.append("")

    # ── 4. Continuation test — raw forward move ─────────────────────────────
    md.append("## Continuation test — raw BTC move after up-fire (deduped 4h)")
    md.append("")
    md.append("If consistently POSITIVE, the signal is continuation (LONG correct); "
              "if negative, the fade (SHORT) advice is sound. `%UP@4h` = share of "
              "fires higher 4h later.")
    md.append("")
    md.append("| score | n | mean +1h% | mean +4h% | mean +8h% | %UP@4h |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for s in (3, 4, 5, 6):
        ded = _dedup([r for r in rows if r["score"] >= s], HOLD_H)
        if not ded:
            continue

        def mean(key):
            vals = [r[key] for r in ded if r.get(key) is not None]
            return round(sum(vals) / len(vals), 3) if vals else float("nan")
        f4 = [r["fwd4"] for r in ded if r.get("fwd4") is not None]
        pct_up = round(sum(1 for v in f4 if v > 0) / len(f4) * 100, 1) if f4 else 0
        md.append(f"| >={s} | {len(ded)} | {mean('fwd1'):+.3f} | {mean('fwd4'):+.3f} | "
                  f"{mean('fwd8'):+.3f} | {pct_up} |")
    md.append("")

    # ── 5. Baseline control — unconditional LONG ────────────────────────────
    md.append("## Baseline control — unconditional LONG (every hour, no signal)")
    md.append("")
    md.append("Same LONG trade fired on a regular hourly grid, ignoring the signal "
              "— the regime base rate. The continuation LONG must BEAT it to have "
              "real edge. NB: the net-bearish window makes this base rate poor by "
              "construction, so beating it is a high bar.")
    md.append("")
    grid = pd.date_range(start.ceil("h"), end.floor("h"), freq="1h", tz="UTC")
    base = []
    for ts in grid:
        cp = _trade_outcome(c_ts, c_hi, c_lo, c_cl, ts)
        f4 = _fwd_raw(c_ts, c_cl, ts, 240)
        if cp is not None:
            base.append({"ts": ts, "cont_pnl": cp, "fwd4": f4})
    bded = _dedup(base, HOLD_H)
    bs = _stats([r["cont_pnl"] for r in bded])
    f4s = [r["fwd4"] for r in bded if r["fwd4"] is not None]
    bup = round(sum(1 for v in f4s if v > 0) / len(f4s) * 100, 1) if f4s else 0
    md.append(f"**Unconditional LONG (deduped n={bs['n']}):** WR={bs['wr']}%, "
              f"EV={bs['ev']:+.3f}%, PF={bs['pf']}, %UP@4h={bup}.")
    md.append("")

    # ── 6. Data-driven verdict ──────────────────────────────────────────────
    md.append("## Verdict")
    md.append("")
    # FADE base stats (score>=3 deduped)
    fade_ded = _dedup([r for r in valid if r["score"] >= 3], HOLD_H)
    fade_stat = _stats([r["fade_pnl"] for r in fade_ded])

    # Continuation discriminators. At tiny n (up-fires are rare), TP/SL trade-EV
    # is noisy; the robust tell — as in the DOWN diagnostic — is the raw forward
    # drift after a fire and whether %UP rises with score. We weight that over a
    # single noisy trade-EV cell.
    cont3 = cont_by_score.get(3, {"ev": 0.0, "wr": 0.0, "pf": 0.0, "n": 0})
    cont_cells = [cont_by_score[s] for s in (3, 4, 5)
                  if s in cont_by_score and cont_by_score[s]["n"] >= 4]
    top = cont_cells[-1] if cont_cells else cont3

    def _fwd4_mean(th):
        ded = _dedup([r for r in rows if r["score"] >= th], HOLD_H)
        vals = [r["fwd4"] for r in ded if r.get("fwd4") is not None]
        return (sum(vals) / len(vals)) if vals else 0.0

    def _pct_up(th):
        ded = _dedup([r for r in rows if r["score"] >= th], HOLD_H)
        vals = [r["fwd4"] for r in ded if r.get("fwd4") is not None]
        return (sum(1 for v in vals if v > 0) / len(vals) * 100) if vals else 0.0

    drift3, drift5 = _fwd4_mean(3), _fwd4_mean(5)
    pu3, pu4, pu5 = _pct_up(3), _pct_up(4), _pct_up(5)
    # continuation-shaped drift: positive at score>=3 AND %UP rises with score
    drift_continuation = drift3 > 0 and pu5 >= pu4 >= pu3 and pu5 > 50
    cont3_beats_base = cont3["ev"] > bs["ev"] and cont3["wr"] > bs["wr"]
    fade_loses = fade_stat["ev"] < 0

    # trade-EV monotone-positive over cells with usable n (the "clean" case)
    ev_positive = bool(cont_cells) and all(c["ev"] > 0 for c in cont_cells) and len(cont_cells) >= 2
    monotone = len(cont_cells) >= 2 and cont_cells[-1]["ev"] >= cont_cells[0]["ev"]

    strong = fade_loses and ev_positive and monotone and cont3_beats_base and drift_continuation
    weak = (not strong) and fade_loses and drift_continuation and cont3_beats_base

    if strong:
        md.append("**UP is also a CONTINUATION signal — confirmed.** The current "
                  f"SHORT fade is -EV (score>=3 deduped EV={fade_stat['ev']:+.3f}%, "
                  f"WR={fade_stat['wr']}%) while the LONG mirror is +EV, rises with "
                  f"score, and beats the unconditional-LONG base rate "
                  f"(top cell WR={top['wr']}%, EV={top['ev']:+.3f}%, PF={top['pf']} "
                  f"vs base WR={bs['wr']}%, EV={bs['ev']:+.3f}%). `🔝 ВЕРХ "
                  "ИСТОЩАЕТСЯ` is mislabeled exactly like the DOWN side was — it is "
                  "an upside-momentum / continuation signal, not reversal.")
        md.append("")
        md.append("**Action:** (1) re-label «🔝 ВЕРХ — ИМПУЛЬС ВВЕРХ», (2) flip "
                  "paper-emit SHORT->LONG, (3) re-frame advice: upside continues -> "
                  "let LONG grids run / SHORT grids at risk, potential LONG setup at "
                  "high score, (4) keep flicker-dedup.")
    elif weak:
        md.append("**UP looks like continuation too, but the edge is WEAK / "
                  "regime-contingent.** The LONG mirror is +EV and beats the "
                  "(bearish-window) base rate, and the SHORT fade is no better, but "
                  "the margin is thin and/or non-monotone "
                  f"(top cell WR={top['wr']}%, EV={top['ev']:+.3f}%, PF={top['pf']}, "
                  f"n={top['n']}; FADE base EV={fade_stat['ev']:+.3f}%; "
                  f"unconditional-LONG base EV={bs['ev']:+.3f}%, WR={bs['wr']}%). "
                  f"Given the net-bearish window ({net_drift:+.1f}%), up-continuation "
                  "is the hard direction and is likely understated here. Lean "
                  "LONG-continuation but treat as provisional.")
        md.append("")
        md.append("**Action (provisional):** re-label «🔝 ВЕРХ — ИМПУЛЬС ВВЕРХ» and "
                  "flip paper-emit to LONG to start collecting live-faithful "
                  "continuation outcomes, flagging low conviction until a "
                  "ranging/bullish window confirms.")
    else:
        md.append("**INCONCLUSIVE on the UP side.** Neither the SHORT fade nor the "
                  "LONG continuation shows a clean, monotone, base-beating edge on "
                  f"this window (FADE score>=3 EV={fade_stat['ev']:+.3f}%, "
                  f"WR={fade_stat['wr']}%; LONG-cont top cell WR={top['wr']}%, "
                  f"EV={top['ev']:+.3f}%, PF={top['pf']}, n={top['n']}; "
                  f"unconditional-LONG base WR={bs['wr']}%, EV={bs['ev']:+.3f}%). "
                  f"The net-bearish window ({net_drift:+.1f}%) starves the "
                  "up-continuation thesis of favorable regime and up-fires are rare, "
                  "so cell counts are small. Do NOT flip live behavior on this "
                  "evidence — keep the UP paper-emit as-is and re-validate on a "
                  "ranging/bullish stretch.")
    md.append("")
    md.append(f"**Caveat (regime):** {(end-start).total_seconds()/86400:.0f}d, "
              f"deduped n small per cell, window net BTC drift {net_drift:+.1f}% "
              "(net-bearish). An up-continuation edge must swim against that drift, "
              "so it reads weaker / more regime-contingent than the down side. "
              "Re-validate after a ranging/bullish stretch and on accumulating live "
              "paper outcomes before trusting it.")
    md.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"[up] wrote {OUT_MD}\n")
    print("\n".join(md))

    decision = "STRONG" if strong else ("WEAK" if weak else "INCONCLUSIVE")
    print(f"\n[up] DECISION={decision} net_drift={net_drift:+.1f}% "
          f"fade_ev={fade_stat['ev']:+.3f} fade_wr={fade_stat['wr']} "
          f"cont_top_ev={top['ev']:+.3f} cont_top_wr={top['wr']} cont_top_n={top['n']} "
          f"base_ev={bs['ev']:+.3f} base_wr={bs['wr']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
