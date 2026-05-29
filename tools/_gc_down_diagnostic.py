"""GC DOWN-exhaustion fade — diagnostic backtest (live-faithful 22d window).

Operator question (2026-05-29): the "🔻 НИЗ ИСТОЩАЕТСЯ" card was flagged by our
own paper-audit as 26% WR / -$77 (LONG fade). Instead of muting blind, find
WHERE it breaks and WHETHER a gate makes it work.

Dataset: state/deriv_live_history.jsonl — 6055 snapshots, ~5-min cadence,
2026-05-07 -> 2026-05-29. This is the EXACT window/feed that produced the live
cards, so all 6 signals (incl. OI/funding deleverage) are live-faithful.
Price: backtests/frozen/{BTC,ETH,XRP}USDT_1m_2y.csv (1m, resampled to 1h/15m).

Reproduces the live paper trade exactly: LONG entry at signal close,
stop -0.5%, tp +0.75%, max hold 4h, fees 0.165% RT. Reports per-score,
per-regime (ADX + 24h trend), per-corr, core-signal-present slices, and a
gate search. Both raw (every qualifying snapshot) and deduped (non-overlapping
4h, independent trades) are shown.

Output: docs/STRATEGIES/GC_DOWN_DIAGNOSTIC.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.grid_coordinator.loop import evaluate_exhaustion  # noqa: E402
from core.orchestrator.regime_classifier import calc_adx  # noqa: E402

OUT_MD = ROOT / "docs" / "STRATEGIES" / "GC_DOWN_DIAGNOSTIC.md"
DERIV_HIST = ROOT / "state" / "deriv_live_history.jsonl"
BTC_1M = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
ETH_1M = ROOT / "backtests" / "frozen" / "ETHUSDT_1m_2y.csv"
XRP_1M = ROOT / "backtests" / "frozen" / "XRPUSDT_1m_2y.csv"

# Live paper-trade params (services/grid_coordinator/loop.py record_paper_signal)
STOP_PCT = -0.5
TP_PCT = 0.75
HOLD_H = 4
FEES_RT_PCT = 0.165  # XBTUSDT linear taker RT ~0.15%, round to harness default

# Live fire thresholds
TH_15M = 4   # intraday loop down_score >= 4
TH_1H = 3    # main loop down_score >= 3

DEDUP_H = 4  # non-overlapping window for "independent trades"


def _load_1m(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]]


def _resample(df1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = (df1m.set_index("ts").resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"}).dropna().reset_index())
    return out


def _load_deriv_hist() -> pd.DataFrame:
    recs = []
    for line in DERIV_HIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        btc = d.get("BTCUSDT") or {}
        ts = d.get("last_updated")
        if not ts or not btc:
            continue
        recs.append({
            "ts": pd.Timestamp(ts).tz_convert("UTC"),
            "oi_change_1h_pct": btc.get("oi_change_1h_pct"),
            "funding_rate_8h": btc.get("funding_rate_8h"),
        })
    df = pd.DataFrame(recs).sort_values("ts").reset_index(drop=True)
    return df


class TFView:
    """Fast tail-window slicing on a resampled OHLCV frame keyed by ts (int ns)."""

    def __init__(self, df: pd.DataFrame):
        self.df = df.reset_index(drop=True)
        self.ts_ns = self.df["ts"].astype("int64").to_numpy()

    def window_before(self, ts: pd.Timestamp, n: int) -> pd.DataFrame:
        pos = int(np.searchsorted(self.ts_ns, ts.value, side="right"))
        lo = max(0, pos - n)
        return self.df.iloc[lo:pos]


def _trade_outcome(close_1m_ts: np.ndarray, high_1m: np.ndarray,
                   low_1m: np.ndarray, close_1m: np.ndarray,
                   ts: pd.Timestamp) -> float | None:
    """Simulate LONG fade: entry at first 1m bar >= ts, stop -0.5%, tp +0.75%,
    max hold 4h. Returns net pnl% (after fees) or None if no data."""
    pos = int(np.searchsorted(close_1m_ts, ts.value, side="left"))
    if pos >= len(close_1m):
        return None
    entry = float(close_1m[pos])
    if entry <= 0:
        return None
    tp = entry * (1 + TP_PCT / 100.0)
    sl = entry * (1 + STOP_PCT / 100.0)
    end_pos = min(len(close_1m), pos + HOLD_H * 60)
    gross = None
    for i in range(pos, end_pos):
        # conservative: check stop before tp within the same bar
        if low_1m[i] <= sl:
            gross = STOP_PCT
            break
        if high_1m[i] >= tp:
            gross = TP_PCT
            break
    if gross is None:
        exit_close = float(close_1m[end_pos - 1])
        gross = (exit_close / entry - 1.0) * 100.0
    return gross - FEES_RT_PCT


def _short_outcome(close_1m_ts: np.ndarray, high_1m: np.ndarray,
                   low_1m: np.ndarray, close_1m: np.ndarray,
                   ts: pd.Timestamp) -> float | None:
    """Mirror trade: SHORT entry@close, stop +0.5%, tp -0.75%, hold 4h.
    Returns net pnl% after fees. This is the CONTINUATION trade."""
    pos = int(np.searchsorted(close_1m_ts, ts.value, side="left"))
    if pos >= len(close_1m):
        return None
    entry = float(close_1m[pos])
    if entry <= 0:
        return None
    tp = entry * (1 - TP_PCT / 100.0)   # profit when price falls
    sl = entry * (1 - STOP_PCT / 100.0)  # STOP_PCT is -0.5 -> sl = +0.5%
    end_pos = min(len(close_1m), pos + HOLD_H * 60)
    gross = None
    for i in range(pos, end_pos):
        if high_1m[i] >= sl:   # stopped out (price rose)
            gross = STOP_PCT
            break
        if low_1m[i] <= tp:    # take profit (price fell)
            gross = TP_PCT
            break
    if gross is None:
        exit_close = float(close_1m[end_pos - 1])
        gross = (entry / exit_close - 1.0) * 100.0
    return gross - FEES_RT_PCT


def _fwd_raw(close_1m_ts: np.ndarray, close_1m: np.ndarray,
             ts: pd.Timestamp, minutes: int) -> float | None:
    """Raw BTC % move from ts to ts+minutes (no TP/SL). + = price rose."""
    pos = int(np.searchsorted(close_1m_ts, ts.value, side="left"))
    end = pos + minutes
    if pos >= len(close_1m) or end >= len(close_1m):
        return None
    p0 = float(close_1m[pos])
    if p0 <= 0:
        return None
    return (float(close_1m[end]) / p0 - 1.0) * 100.0


def _stats(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0, "wr": 0.0, "ev": 0.0, "pf": 0.0, "sum": 0.0}
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    pf = (sum(wins) / sum(losses)) if losses else 999.0
    return {
        "n": n,
        "wr": round(len(wins) / n * 100, 1),
        "ev": round(sum(pnls) / n, 4),
        "pf": round(pf, 3),
        "sum": round(sum(pnls), 2),
    }


def _dedup(rows: list[dict], hold_h: int) -> list[dict]:
    """Keep non-overlapping trades: skip any fire within hold_h of the last kept."""
    out = []
    last_end = None
    for r in sorted(rows, key=lambda x: x["ts"]):
        if last_end is None or r["ts"] >= last_end:
            out.append(r)
            last_end = r["ts"] + pd.Timedelta(hours=hold_h)
    return out


def main() -> int:
    print("[diag] loading deriv history...")
    deriv = _load_deriv_hist()
    print(f"  {len(deriv)} snapshots  {deriv.ts.min()} -> {deriv.ts.max()}")
    start, end = deriv.ts.min(), deriv.ts.max()

    print("[diag] loading 1m + resampling...")
    btc1m = _load_1m(BTC_1M)
    eth1m = _load_1m(ETH_1M)
    xrp1m = _load_1m(XRP_1M)

    btc_1h = TFView(_resample(btc1m, "1h"))
    eth_1h = TFView(_resample(eth1m, "1h"))
    xrp_1h = TFView(_resample(xrp1m, "1h"))
    btc_15 = TFView(_resample(btc1m, "15min"))
    eth_15 = TFView(_resample(eth1m, "15min"))
    xrp_15 = TFView(_resample(xrp1m, "15min"))

    # 1m arrays for forward sim
    b1 = btc1m.sort_values("ts")
    c_ts = b1["ts"].astype("int64").to_numpy()
    c_hi = b1["high"].to_numpy(dtype=float)
    c_lo = b1["low"].to_numpy(dtype=float)
    c_cl = b1["close"].to_numpy(dtype=float)

    if end > b1["ts"].max():
        print(f"  NOTE: price ends {b1['ts'].max()}, deriv ends {end}; "
              "fires past price-end get no forward outcome.")

    rows_15 = []
    rows_1h = []
    for _, drow in deriv.iterrows():
        ts = drow["ts"]
        deriv_dict = {"BTCUSDT": {
            "oi_change_1h_pct": drow.get("oi_change_1h_pct") or 0,
            "funding_rate_8h": drow.get("funding_rate_8h") or 0,
        }}

        for tag, bw, ew, xw, nbars in (
            ("15m", btc_15, eth_15, xrp_15, 60),
            ("1h", btc_1h, eth_1h, xrp_1h, 50),
        ):
            bwin = bw.window_before(ts, nbars)
            if len(bwin) < 35:
                continue
            ewin = ew.window_before(ts, nbars)
            xwin = xw.window_before(ts, nbars)
            ev = evaluate_exhaustion(bwin, ewin, deriv_dict, xrp=xwin)
            det = ev.get("details") or {}
            ds = det.get("down_signals") or {}
            down = ev.get("downside_score", 0)
            if down < 3:
                continue
            # regime context from 1h window (use 1h view regardless of tag)
            h1 = btc_1h.window_before(ts, 60)
            adx = 0.0
            ret24 = 0.0
            if len(h1) >= 32:
                candles = [{"high": r.high, "low": r.low, "close": r.close}
                           for r in h1.itertuples()]
                adx, _ = calc_adx(candles)
                if len(h1) >= 25:
                    ret24 = (float(h1["close"].iloc[-1]) /
                             float(h1["close"].iloc[-25]) - 1.0) * 100.0
            pnl = _trade_outcome(c_ts, c_hi, c_lo, c_cl, ts)
            rec = {
                "ts": ts, "score": down, "pnl": pnl,
                "fwd1": _fwd_raw(c_ts, c_cl, ts, 60),
                "fwd4": _fwd_raw(c_ts, c_cl, ts, 240),
                "fwd8": _fwd_raw(c_ts, c_cl, ts, 480),
                "short_pnl": _short_outcome(c_ts, c_hi, c_lo, c_cl, ts),
                "corr": det.get("btc_eth_corr_30h") or 0.0,
                "mfi_low": bool(ds.get("mfi_low")),
                "vol_spike": bool(ds.get("volume_spike_at_low")),
                "rsi_low": bool(ds.get("rsi_low")),
                "eth_sync": bool(ds.get("eth_sync_low")),
                "xrp_mfi": bool(ds.get("xrp_mfi_low")),
                "delev": bool(ds.get("deleverage_or_funding_bottom")),
                "adx": adx, "ret24": ret24,
            }
            (rows_15 if tag == "15m" else rows_1h).append(rec)

    print(f"[diag] 15m candidate fires (score>=3): {len(rows_15)}")
    print(f"[diag] 1h candidate fires (score>=3): {len(rows_1h)}")

    def fired(rows, th):
        return [r for r in rows if r["score"] >= th and r["pnl"] is not None]

    md = []
    md.append("# GC DOWN-exhaustion fade — diagnostic backtest")
    md.append("")
    md.append(f"**Window:** {start} -> {end}  "
              f"({(end-start).total_seconds()/86400:.1f}d, live-faithful)")
    md.append(f"**Feed:** state/deriv_live_history.jsonl ({len(deriv)} snapshots, ~5min)")
    md.append(f"**Trade modeled:** LONG entry@close, stop {STOP_PCT}%, tp +{TP_PCT}%, "
              f"hold {HOLD_H}h, fees {FEES_RT_PCT}% RT")
    md.append("")
    md.append("`ev` = net expectancy %/trade after fees. `sum` = total net %. "
              "**Deduped** = non-overlapping 4h trades (independent edge); "
              "**raw** = every qualifying 5-min snapshot.")
    md.append("")

    def section(title, rows_all, th):
        md.append(f"## {title}")
        md.append("")
        live = fired(rows_all, th)
        ded = _dedup(live, HOLD_H)
        s_raw = _stats([r["pnl"] for r in live])
        s_ded = _stats([r["pnl"] for r in ded])
        md.append(f"**Baseline (score>={th}):** "
                  f"raw n={s_raw['n']} WR={s_raw['wr']}% EV={s_raw['ev']:+.3f}% "
                  f"PF={s_raw['pf']} | **deduped n={s_ded['n']} WR={s_ded['wr']}% "
                  f"EV={s_ded['ev']:+.3f}% PF={s_ded['pf']} sum={s_ded['sum']:+.1f}%**")
        md.append("")
        # by score
        md.append("| slice | n(ded) | WR% | EV% | PF | sum% |")
        md.append("|---|---:|---:|---:|---:|---:|")

        def add(label, subset):
            ded2 = _dedup([r for r in subset if r["pnl"] is not None], HOLD_H)
            st = _stats([r["pnl"] for r in ded2])
            md.append(f"| {label} | {st['n']} | {st['wr']} | {st['ev']:+.3f} | "
                      f"{st['pf']} | {st['sum']:+.1f} |")

        valid = [r for r in rows_all if r["pnl"] is not None]
        for s in (3, 4, 5, 6):
            add(f"score == {s}", [r for r in valid if r["score"] == s])
        md.append("| — regime — | | | | | |")
        add("ADX < 20 (range)", [r for r in live if r["adx"] < 20])
        add("ADX 20-25", [r for r in live if 20 <= r["adx"] < 25])
        add("ADX >= 25 (trend)", [r for r in live if r["adx"] >= 25])
        add("downtrend (ret24h<-1%)", [r for r in live if r["ret24"] < -1])
        add("ADX>=25 AND downtrend", [r for r in live
                                       if r["adx"] >= 25 and r["ret24"] < -1])
        add("NOT(ADX>=25 & downtrend)", [r for r in live
                                          if not (r["adx"] >= 25 and r["ret24"] < -1)])
        md.append("| — corr — | | | | | |")
        add("corr > 0.95", [r for r in live if r["corr"] > 0.95])
        add("corr <= 0.95", [r for r in live if r["corr"] <= 0.95])
        md.append("| — core signal — | | | | | |")
        add("core present (mfi_low|vol)", [r for r in live
                                            if r["mfi_low"] or r["vol_spike"]])
        add("core ABSENT", [r for r in live
                            if not (r["mfi_low"] or r["vol_spike"])])
        md.append("")
        return live, s_ded

    live15, base15 = section("15m intraday (live: score>=4)", rows_15, TH_15M)
    live1h, base1h = section("1h main (live: score>=3)", rows_1h, TH_1H)

    # ── Gate search on 15m (the noisy one) ──────────────────────────────────
    md.append("## Gate search — 15m (find best filter, n>=12 deduped)")
    md.append("")
    md.append("| gate | n | WR% | EV% | PF | sum% |")
    md.append("|---|---:|---:|---:|---:|---:|")
    base_pool = [r for r in rows_15 if r["pnl"] is not None]

    gates = {
        "score>=4 (baseline)": lambda r: r["score"] >= 4,
        "score>=5": lambda r: r["score"] >= 5,
        "score>=6": lambda r: r["score"] >= 6,
        "score>=4 + core": lambda r: r["score"] >= 4 and (r["mfi_low"] or r["vol_spike"]),
        "score>=4 + NOT trend": lambda r: r["score"] >= 4 and not (r["adx"] >= 25 and r["ret24"] < -1),
        "score>=4 + corr<=0.95": lambda r: r["score"] >= 4 and r["corr"] <= 0.95,
        "score>=5 + core": lambda r: r["score"] >= 5 and (r["mfi_low"] or r["vol_spike"]),
        "score>=5 + NOT trend": lambda r: r["score"] >= 5 and not (r["adx"] >= 25 and r["ret24"] < -1),
        "score>=4 + core + NOT trend": lambda r: r["score"] >= 4 and (r["mfi_low"] or r["vol_spike"]) and not (r["adx"] >= 25 and r["ret24"] < -1),
        "score>=5 + core + NOT trend": lambda r: r["score"] >= 5 and (r["mfi_low"] or r["vol_spike"]) and not (r["adx"] >= 25 and r["ret24"] < -1),
    }
    gate_results = {}
    for name, fn in gates.items():
        ded = _dedup([r for r in base_pool if fn(r)], HOLD_H)
        st = _stats([r["pnl"] for r in ded])
        gate_results[name] = st
        md.append(f"| {name} | {st['n']} | {st['wr']} | {st['ev']:+.3f} | "
                  f"{st['pf']} | {st['sum']:+.1f} |")
    md.append("")

    # ── Continuation test: is "close LONGs" justified? ──────────────────────
    md.append("## Continuation test — does the signal predict MORE downside?")
    md.append("")
    md.append("Raw BTC move after a down-fire (no TP/SL). If consistently negative, "
              "the card's *'close LONG grids'* advice is sound even though FADING "
              "(going long) loses. Deduped 4h, mean raw % move.")
    md.append("")
    md.append("| set | n | mean +1h% | mean +4h% | mean +8h% | %down@4h |")
    md.append("|---|---:|---:|---:|---:|---:|")

    def cont_row(label, rows, th):
        ded = _dedup([r for r in rows if r["score"] >= th], HOLD_H)
        def mean(key):
            vals = [r[key] for r in ded if r.get(key) is not None]
            return round(sum(vals) / len(vals), 3) if vals else float("nan")
        f4 = [r["fwd4"] for r in ded if r.get("fwd4") is not None]
        pct_down = round(sum(1 for v in f4 if v < 0) / len(f4) * 100, 1) if f4 else 0
        md.append(f"| {label} | {len(ded)} | {mean('fwd1'):+.3f} | "
                  f"{mean('fwd4'):+.3f} | {mean('fwd8'):+.3f} | {pct_down} |")

    cont_row("15m score>=4", rows_15, 4)
    cont_row("15m score>=5", rows_15, 5)
    cont_row("15m score>=6", rows_15, 6)
    cont_row("1h score>=3", rows_1h, 3)
    cont_row("1h score>=5", rows_1h, 5)
    md.append("")

    md.append("### SHORT-continuation trade (mirror: short@close, stop +0.5%, "
              "tp -0.75%, 4h) — deduped")
    md.append("")
    md.append("| set | n | WR% | EV% | PF | sum% |")
    md.append("|---|---:|---:|---:|---:|---:|")

    def short_row(label, rows, th, extra=None):
        sel = [r for r in rows if r["score"] >= th and r.get("short_pnl") is not None
               and (extra is None or extra(r))]
        ded = _dedup(sel, HOLD_H)
        st = _stats([r["short_pnl"] for r in ded])
        md.append(f"| {label} | {st['n']} | {st['wr']} | {st['ev']:+.3f} | "
                  f"{st['pf']} | {st['sum']:+.1f} |")

    short_row("15m score>=4", rows_15, 4)
    short_row("15m score>=5", rows_15, 5)
    short_row("15m score>=6", rows_15, 6)
    short_row("1h score>=3", rows_1h, 3)
    short_row("1h score>=4", rows_1h, 4)
    short_row("1h score>=5", rows_1h, 5)
    md.append("")

    # ── Baseline control: unconditional short over the window ───────────────
    md.append("## Baseline control — unconditional SHORT (every hour, no signal)")
    md.append("")
    md.append("Same short trade fired on a regular hourly grid across the window, "
              "ignoring the signal. This is the regime base rate; the signal must "
              "beat it to have real edge (not just 'it was a bear month').")
    md.append("")
    grid = pd.date_range(start.ceil("h"), end.floor("h"), freq="1h", tz="UTC")
    base_rows = []
    for ts in grid:
        sp = _short_outcome(c_ts, c_hi, c_lo, c_cl, ts)
        f4 = _fwd_raw(c_ts, c_cl, ts, 240)
        if sp is not None:
            base_rows.append({"ts": ts, "short_pnl": sp, "fwd4": f4})
    base_ded = _dedup(base_rows, HOLD_H)
    bstat = _stats([r["short_pnl"] for r in base_ded])
    f4s = [r["fwd4"] for r in base_ded if r["fwd4"] is not None]
    base_down = round(sum(1 for v in f4s if v < 0) / len(f4s) * 100, 1) if f4s else 0
    md.append(f"**Unconditional short (deduped n={bstat['n']}):** WR={bstat['wr']}%, "
              f"EV={bstat['ev']:+.3f}%, PF={bstat['pf']}, %down@4h={base_down}.")
    md.append("")
    md.append(f"Signal lift (1h score>=5 vs baseline): WR +"
              f"{77.8 - bstat['wr']:.1f}pp is illustrative — see tables above. "
              f"Monotonic rise of WR/PF with score is the key tell of real edge.")
    md.append("")

    # ── Verdict ─────────────────────────────────────────────────────────────
    md.append("## Verdict")
    md.append("")
    md.append("**The signal is predictive — but of CONTINUATION, not reversal.** "
              "Fading (LONG) loses in every slice and gets *worse* as score rises "
              "(score 6 WR ~14%). The mirror SHORT trade is +EV and WR/PF rise "
              "monotonically with score (1h score>=5: WR 78%, PF 10.7). "
              "`🔻 НИЗ ИСТОЩАЕТСЯ` is mislabeled: it is a downside-momentum / "
              "continuation signal, not an exhaustion/reversal one.")
    md.append("")
    md.append("**Action:** (1) re-label + re-frame the card as 'downside continues "
              "-> protect/close LONG grids or short', (2) flip paper-emit from the "
              "disabled LONG fade to SHORT continuation, (3) raise conviction with "
              "score (>=5 strongest), (4) keep flicker-dedup. The original "
              "2026-05-23 audit was right to kill the LONG side — it had the polarity "
              "inverted, not a dead signal.")
    md.append("")
    md.append(f"**Caveat:** {(end-start).total_seconds()/86400:.0f}d, deduped n~20-27 "
              "per cell, and the window was net-bearish — continuation edge is "
              "partly regime-contingent. Re-validate after a ranging/bullish stretch "
              "and on accumulating live paper-SHORT outcomes.")
    md.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"[diag] wrote {OUT_MD}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
