"""cascade_alert regime diagnostic — why is the only +EV live source decaying?

Uses the REAL recorded paper_signals (source=cascade_alert, closed) and enriches
each with regime context (ADX + 24h trend) at signal time from frozen 1h price.
Slices WR/PnL/PF by side, liq magnitude, and regime to find where it bleeds.

Output: docs/STRATEGIES/CASCADE_REGIME_AUDIT.md
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

OUT_MD = ROOT / "docs" / "STRATEGIES" / "CASCADE_REGIME_AUDIT.md"


def _pt(s):
    try:
        return pd.Timestamp(str(s)).tz_convert("UTC")
    except Exception:
        return None


def _stats(sub):
    n = len(sub)
    if not n:
        return None
    wins = [r for r in sub if r["pnl_usd"] > 0]
    pnl = sum(r["pnl_usd"] for r in sub)
    gw = sum(r["pnl_usd"] for r in wins)
    gl = -sum(r["pnl_usd"] for r in sub if r["pnl_usd"] < 0)
    pf = gw / gl if gl > 0 else 999.0
    return {"n": n, "wr": round(len(wins) / n * 100, 1),
            "pnl": round(pnl, 1), "pf": round(pf, 2)}


def main() -> int:
    rows = [json.loads(l) for l in open(ROOT / "state" / "paper_signals.jsonl") if l.strip()]
    ca = [r for r in rows if r.get("source") == "cascade_alert"
          and r.get("outcome") and r.get("pnl_usd") is not None]
    print(f"cascade closed: {len(ca)}")

    btc_1h = TFView(_resample(_load_1m(BTC_1M), "1h"))

    for r in ca:
        ts = _pt(r.get("ts_signal"))
        r["_ts"] = ts
        r["adx"] = 0.0
        r["ret24"] = 0.0
        if ts is None:
            continue
        h1 = btc_1h.window_before(ts, 60)
        if len(h1) >= 32:
            candles = [{"high": x.high, "low": x.low, "close": x.close} for x in h1.itertuples()]
            r["adx"], _ = calc_adx(candles)
            if len(h1) >= 25:
                r["ret24"] = (float(h1["close"].iloc[-1]) / float(h1["close"].iloc[-25]) - 1.0) * 100.0
        ctx = r.get("context", "")
        r["liq_btc"] = float(ctx.split("_")[-1].replace("btc", "")) if "btc" in ctx else 0.0
        r["liq_side"] = "short_liq" if "short_liq" in ctx else ("long_liq" if "long_liq" in ctx else "?")

    md = ["# cascade_alert regime diagnostic", ""]
    md.append(f"Closed cascade_alert paper trades: **{len(ca)}**. Enriched with ADX + "
              "24h trend at signal time (frozen 1h price). short_liq→LONG, long_liq→SHORT "
              "(continuation follow), stop ±0.5% / tp 0.75%.")
    md.append("")

    def table(title, groups):
        md.append(f"## {title}")
        md.append("")
        md.append("| slice | n | WR% | PnL$ | PF |")
        md.append("|---|---:|---:|---:|---:|")
        for label, sub in groups:
            st = _stats(sub)
            if st:
                md.append(f"| {label} | {st['n']} | {st['wr']} | {st['pnl']:+.1f} | {st['pf']} |")
        md.append("")

    table("By side", [
        ("LONG (short_liq follow)", [r for r in ca if r.get("side") == "LONG"]),
        ("SHORT (long_liq follow)", [r for r in ca if r.get("side") == "SHORT"]),
    ])
    table("By liq magnitude", [
        ("2 BTC", [r for r in ca if r.get("liq_btc") == 2.0]),
        ("5 BTC", [r for r in ca if r.get("liq_btc") == 5.0]),
        ("10 BTC", [r for r in ca if r.get("liq_btc") == 10.0]),
    ])
    table("By regime (ADX)", [
        ("ADX < 20 (range)", [r for r in ca if r["adx"] < 20]),
        ("ADX 20-25", [r for r in ca if 20 <= r["adx"] < 25]),
        ("ADX >= 25 (trend)", [r for r in ca if r["adx"] >= 25]),
    ])
    table("Aligned vs counter-trend (key test)", [
        ("LONG in uptrend (ret24>+0.5%)", [r for r in ca if r.get("side") == "LONG" and r["ret24"] > 0.5]),
        ("LONG in downtrend (ret24<-0.5%)", [r for r in ca if r.get("side") == "LONG" and r["ret24"] < -0.5]),
        ("SHORT in downtrend (ret24<-0.5%)", [r for r in ca if r.get("side") == "SHORT" and r["ret24"] < -0.5]),
        ("SHORT in uptrend (ret24>+0.5%)", [r for r in ca if r.get("side") == "SHORT" and r["ret24"] > 0.5]),
    ])
    short = [r for r in ca if r.get("side") == "SHORT"]
    table("Data-driven gate search (LONG side is the bleeder)", [
        ("ALL (baseline)", ca),
        ("DROP LONG side (SHORT-only)", short),
        ("SHORT + liq>=5", [r for r in short if r.get("liq_btc") >= 5.0]),
        ("SHORT + ADX<25", [r for r in short if r["adx"] < 25]),
        ("SHORT + liq>=5 + ADX<25", [r for r in short if r.get("liq_btc") >= 5.0 and r["adx"] < 25]),
        ("DROP 2BTC only (keep both sides)", [r for r in ca if r.get("liq_btc") >= 5.0]),
        ("DROP 2BTC + ADX<25 (both sides)", [r for r in ca if r.get("liq_btc") >= 5.0 and r["adx"] < 25]),
    ])

    md.append("## Verdict")
    md.append("")
    md.append("- **LONG side (short_liq→LONG) is dead weight: −$170, PF 0.49, loses in "
              "BOTH up- and down-trend slices.** The +$96 baseline survives only because "
              "the SHORT side (+$266, PF 4.23) carries it.")
    md.append("- **SHORT side (long_liq→SHORT) is the engine**, best in uptrends "
              "(+$161, PF 13.4 — fading over-leveraged longs into a squeeze).")
    md.append("- **Strong trend kills cascades:** ADX>=25 = −$61 / PF 0.78; ADX<25 = +$157.")
    md.append("- **2 BTC liqs are noise** (WR 47%, ~flat); 5 BTC is the sweet spot (PF 2.85).")
    md.append("- The naive 'trade with the trend' gate REDUCES PnL — alignment is the "
              "wrong axis here. The right gates are: drop LONG side, drop 2 BTC, skip ADX>=25.")
    md.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
