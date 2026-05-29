"""Range Hunter shadow-validation — prove/disprove edge on recorded signals.

RH produces a range-straddle card (limit-buy @ buy_level, limit-sell @ sell_level)
and asks the operator to place it. Live conversion is ~1/78 — the signals are
unproven, so the operator (rightly) ignores them. This shadow-fills every
recorded RH signal against 1m price to learn the EMPIRICAL pair-win rate and net
PnL, so only a proven edge gets promoted to push later.

Outcome model (mirrors journal exit_reason semantics):
  - both levels touched within hold      -> pair_win   (captured the spread)
  - one leg fills, price runs stop% against it before the other level -> *_stopped
  - one leg fills, hold expires           -> *_timeout  (mark-to-market exit)
  - neither level touched                 -> no_fill    (flat)

Fees: maker rebate on limit fills (XBTUSDT -0.04%), taker on stop-market exit
(0.075%/side). Conservative.

Output: docs/STRATEGIES/RH_SHADOW_VALIDATION.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools._gc_down_diagnostic import _load_1m, BTC_1M, ETH_1M, XRP_1M  # noqa: E402

OUT_MD = ROOT / "docs" / "STRATEGIES" / "RH_SHADOW_VALIDATION.md"
MAKER_FEE = 0.04   # % rebate on limit fill (negative cost)
TAKER_FEE = 0.075  # % per side on stop-market exit

JOURNALS = {
    "BTCUSDT": ("state/range_hunter_signals.jsonl", BTC_1M),
    "ETHUSDT": ("state/range_hunter_signals_ETHUSDT.jsonl", ETH_1M),
    "XRPUSDT": ("state/range_hunter_signals_XRPUSDT.jsonl", XRP_1M),
}


def _pt(s):
    try:
        return pd.Timestamp(str(s)).tz_convert("UTC")
    except Exception:
        return None


def _simulate(sig: dict, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray,
              ts_ns: np.ndarray) -> dict | None:
    ts = _pt(sig.get("ts_signal"))
    buy = sig.get("buy_level")
    sell = sig.get("sell_level")
    if ts is None or not buy or not sell:
        return None
    size_usd = float(sig.get("size_usd") or 0)
    size_btc = float(sig.get("size_btc") or (size_usd / float(sig.get("mid_signal") or buy)))
    stop_pct = float(sig.get("stop_loss_pct") or 0.2)
    hold_h = int(sig.get("hold_h") or 6)
    pos = int(np.searchsorted(ts_ns, ts.value, side="left"))
    end = pos + hold_h * 60
    if pos >= len(cl) or end > len(cl):
        return None  # not enough forward price

    buy_fill = sell_fill = None
    spread = sell - buy
    for i in range(pos, end):
        if buy_fill is None and lo[i] <= buy:
            buy_fill = i
        if sell_fill is None and hi[i] >= sell:
            sell_fill = i
        if buy_fill is not None and sell_fill is not None:
            # pair_win: captured the spread on both legs (limit fills -> maker)
            gross = size_btc * spread
            fee = size_usd * (MAKER_FEE / 100.0) * 2 * -1  # rebate both legs
            return {"reason": "pair_win", "legs": 2, "pnl": gross - fee}
        # single-leg stop check
        if buy_fill is not None and sell_fill is None:
            if lo[i] <= buy * (1 - stop_pct / 100.0):
                loss = size_btc * buy * (stop_pct / 100.0)
                fee = size_usd * ((MAKER_FEE + TAKER_FEE) / 100.0)  # maker in, taker out
                return {"reason": "buy_stopped", "legs": 1, "pnl": -(loss) - fee}
        if sell_fill is not None and buy_fill is None:
            if hi[i] >= sell * (1 + stop_pct / 100.0):
                loss = size_btc * sell * (stop_pct / 100.0)
                fee = size_usd * ((MAKER_FEE + TAKER_FEE) / 100.0)
                return {"reason": "sell_stopped", "legs": 1, "pnl": -(loss) - fee}
    # hold expired
    exit_px = float(cl[end - 1])
    if buy_fill is not None and sell_fill is None:
        gross = size_btc * (exit_px - buy)   # long leg mark-to-market
        fee = size_usd * ((MAKER_FEE + TAKER_FEE) / 100.0)
        return {"reason": "buy_timeout", "legs": 1, "pnl": gross - fee}
    if sell_fill is not None and buy_fill is None:
        gross = size_btc * (sell - exit_px)  # short leg mark-to-market
        fee = size_usd * ((MAKER_FEE + TAKER_FEE) / 100.0)
        return {"reason": "sell_timeout", "legs": 1, "pnl": gross - fee}
    return {"reason": "no_fill", "legs": 0, "pnl": 0.0}


def main() -> int:
    md = ["# Range Hunter shadow-validation", ""]
    md.append("Auto-filled every recorded RH signal against 1m price (the operator "
              "acted on ~1/78). Tests the strategy's assumed **68.5% pair-win** "
              "empirically. pair_win = both straddle legs touched within hold; "
              "single-leg fills can stop out at stop_loss_pct.")
    md.append("")
    md.append("| symbol | signals | simd | pair_win% | stopped% | timeout% | no_fill% | net PnL$ | $/sig |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    grand = []
    for sym, (jpath, pxpath) in JOURNALS.items():
        p = ROOT / jpath
        if not p.exists():
            continue
        sigs = [json.loads(l) for l in open(p) if l.strip()]
        px = _load_1m(pxpath).sort_values("ts")
        ts_ns = px["ts"].astype("int64").to_numpy()
        hi = px["high"].to_numpy(dtype=float)
        lo = px["low"].to_numpy(dtype=float)
        cl = px["close"].to_numpy(dtype=float)
        res = []
        for s in sigs:
            r = _simulate(s, hi, lo, cl, ts_ns)
            if r:
                res.append(r)
                grand.append(r)
        if not res:
            continue
        n = len(res)
        def share(reasons):
            return round(sum(1 for r in res if r["reason"] in reasons) / n * 100, 1)
        pnl = sum(r["pnl"] for r in res)
        md.append(f"| {sym} | {len(sigs)} | {n} | {share(['pair_win'])} | "
                  f"{share(['buy_stopped','sell_stopped'])} | "
                  f"{share(['buy_timeout','sell_timeout'])} | {share(['no_fill'])} | "
                  f"{pnl:+.1f} | {pnl/n:+.2f} |")

    md.append("")
    if grand:
        n = len(grand)
        pw = sum(1 for r in grand if r["reason"] == "pair_win") / n * 100
        pnl = sum(r["pnl"] for r in grand)
        wins = sum(1 for r in grand if r["pnl"] > 0)
        traded = [r for r in grand if r["reason"] != "no_fill"]
        md.append("## Verdict")
        md.append("")
        md.append(f"- **All symbols: n={n}, empirical pair_win={pw:.1f}%** "
                  f"(strategy assumed 68.5%).")
        md.append(f"- Net PnL **{pnl:+.1f}$** over {n} sims, {pnl/n:+.2f}$/signal; "
                  f"win-share {wins/n*100:.1f}%; of {len(traded)} that filled ≥1 leg, "
                  f"net {sum(r['pnl'] for r in traded):+.1f}$.")
        verdict = ("EDGE CONFIRMED — promote top signals to push" if pnl > 0 and pw >= 55
                   else "NO/WEAK EDGE — do not promote; investigate level quality"
                   if pnl <= 0 else "MARGINAL — keep shadow-tracking before promoting")
        md.append(f"- **{verdict}.**")
        md.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
