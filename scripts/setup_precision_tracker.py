"""Setup precision tracker.

Closes the loop on each emitted setup: was it TP1/SL/TIMEOUT?
Computes per-detector real win-rate + expectancy and compares to
backtest expectations. Catches drift earlier than edge_tracker.

Reads:
  state/setups.jsonl                     — every emitted setup
  state/setup_outcomes.jsonl             — already-evaluated (skip)
  market_live/market_1m.csv  +  frozen   — price source

Writes:
  state/setup_outcomes.jsonl  — one line per evaluated setup
  stdout                      — per-detector summary

Outcome rules:
  Walk minutes from detected_at to detected_at+window_minutes.
  - LONG: TP1 if high >= tp1; SL if low <= stop; first one wins.
  - SHORT: TP1 if low <= tp1; SL if high >= stop; first one wins.
  - Else: TIMEOUT, pnl = (last_close - entry) * sign.
  Slippage/fees: 0.165% RT round-trip.

Run weekly via cron + on-demand for live monitoring.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PREV_STATUS = ROOT / "state" / "setup_precision_prev_status.json"
SETUPS = ROOT / "state" / "setups.jsonl"
OUTCOMES = ROOT / "state" / "setup_precision_outcomes.jsonl"
DATA_FROZEN = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
DATA_LIVE = ROOT / "market_live" / "market_1m.csv"

FEES_RT_PCT = 0.165


def _load_prices() -> pd.DataFrame:
    frames = []
    if DATA_FROZEN.exists():
        df = pd.read_csv(DATA_FROZEN)
        df["ts_utc"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        frames.append(df[["ts_utc", "high", "low", "close"]])
    if DATA_LIVE.exists():
        df = pd.read_csv(DATA_LIVE)
        df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts_utc"])
        frames.append(df[["ts_utc", "high", "low", "close"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True).drop_duplicates("ts_utc")
    return out.sort_values("ts_utc").set_index("ts_utc")


# 2026-05-30 FIX: per-pair price. The old single-frame loader was BTC-only and
# graded ETH/XRP setups against BTC price → fake instant TP1/SL on alts. Now each
# setup is evaluated against ITS OWN pair's 1m price (frozen CSV + live tail).
_PAIR_CACHE: dict = {}


def _prices_for_pair(pair: str) -> pd.DataFrame:
    if pair in _PAIR_CACHE:
        return _PAIR_CACHE[pair]
    frames = []
    fp = ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv"
    if fp.exists():
        df = pd.read_csv(fp)
        df["ts_utc"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        frames.append(df[["ts_utc", "high", "low", "close"]])
    # live tail beyond the frozen snapshot (so daily runs grade fresh setups)
    try:
        from core.data_loader import load_historical_klines
        import time as _t
        frozen_max = frames[0]["ts_utc"].max() if frames else None
        now_ms = int(_t.time() * 1000)
        start_ms = (int(frozen_max.timestamp() * 1000) if frozen_max is not None
                    else now_ms - 7 * 86400 * 1000)
        if now_ms - start_ms > 120000:
            live = load_historical_klines(symbol=pair, timeframe="1m",
                                          start_ms=start_ms, end_ms=now_ms)
            if live is not None and not live.empty:
                tcol = next((c for c in ("open_time", "ts", "timestamp")
                             if c in live.columns), None)
                if tcol == "ts":
                    live["ts_utc"] = pd.to_datetime(live["ts"], unit="ms", utc=True)
                elif tcol:
                    live["ts_utc"] = pd.to_datetime(live[tcol], utc=True)
                if "ts_utc" in live.columns:
                    frames.append(live[["ts_utc", "high", "low", "close"]])
    except Exception:
        pass
    if not frames:
        out = pd.DataFrame()
    else:
        out = (pd.concat(frames, ignore_index=True).drop_duplicates("ts_utc")
               .sort_values("ts_utc").set_index("ts_utc"))
    _PAIR_CACHE[pair] = out
    return out


_DEFAULT_BACKTEST_EXPECTANCY = {
    "short_pdh_rejection": 0.005,   # PF 1.16 calibrated
    "short_rally_fade": 0.005,      # PF ~1.4 with filter
    "long_pdl_bounce": 0.001,
    "long_dump_reversal": 0.001,
    "long_double_bottom": 0.005,
    "short_double_top": 0.005,
    "long_multi_divergence": 0.0,
    "long_rsi_momentum_ga": 0.0,
    "short_mfi_multi_ga": 0.0,
}

_BACKTEST_EXP_PATH = ROOT / "data" / "config" / "backtest_expectancy.json"


def _load_backtest_expectancy() -> dict[str, float]:
    """Load per-detector expected expectancy from JSON, fall back to defaults."""
    if _BACKTEST_EXP_PATH.exists():
        try:
            data = json.loads(_BACKTEST_EXP_PATH.read_text(encoding="utf-8"))
            return {k: float(v) for k, v in data.items()
                    if isinstance(v, (int, float))}
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return dict(_DEFAULT_BACKTEST_EXPECTANCY)


def _bootstrap_ci(values: list[float], statistic_fn,
                  n_resamples: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    """Percentile bootstrap CI for an arbitrary statistic."""
    if not values or len(values) < 3:
        return (0.0, 0.0)
    import random
    n = len(values)
    samples = []
    for _ in range(n_resamples):
        resample = [values[random.randrange(n)] for _ in range(n)]
        samples.append(statistic_fn(resample))
    samples.sort()
    lo = samples[int(n_resamples * alpha / 2)]
    hi = samples[int(n_resamples * (1 - alpha / 2)) - 1]
    return (lo, hi)


def _status(n: int, ci_lo: float, ci_hi: float, live_exp: float,
            bt_exp: float | None) -> str:
    """Status classification:
      INSUFFICIENT — N<30, can't say anything.
      EVALUATING   — 30<=N<100, stats forming.
      STABLE       — N>=100, CI excludes 0 on positive side.
      DEGRADED     — N>=30, CI excludes 0 on negative side OR live drifted >2σ
                     from backtest expected.
      MARGINAL     — N>=30, CI straddles 0 (inconclusive).
    """
    if n < 30:
        return "INSUFFICIENT"
    if ci_lo > 0:  # entirely positive
        return "STABLE" if n >= 100 else "EVALUATING"
    if ci_hi < 0:  # entirely negative — actively losing
        return "DEGRADED"
    # CI straddles 0 — check drift vs backtest
    if bt_exp is not None and bt_exp > 0:
        # Width of CI as proxy for σ
        approx_sigma = max(1e-6, (ci_hi - ci_lo) / 4.0)
        z = abs(live_exp - bt_exp) / approx_sigma
        if z >= 2.0 and live_exp < bt_exp:
            return "DEGRADED"
    return "MARGINAL"


def _evaluate(setup: dict, prices: pd.DataFrame) -> dict | None:
    try:
        det_at = datetime.fromisoformat(setup["detected_at"].replace("Z", "+00:00"))
        if det_at.tzinfo is None:
            det_at = det_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None
    entry = float(setup.get("entry_price") or 0)
    stop = float(setup.get("stop_price") or 0)
    tp1 = float(setup.get("tp1_price") or 0)
    if entry <= 0 or stop <= 0 or tp1 <= 0:
        return None

    side = "long" if tp1 > entry else "short"
    window_min = int(setup.get("window_minutes") or 120)
    end_at = det_at + timedelta(minutes=window_min)

    if prices.index.max() < end_at:
        return None  # not enough forward data yet

    forward = prices.loc[(prices.index >= det_at) & (prices.index <= end_at)]
    if forward.empty:
        return None

    outcome = "TIMEOUT"
    exit_price = float(forward["close"].iloc[-1])
    for ts, row in forward.iterrows():
        if side == "long":
            if row["high"] >= tp1:
                outcome = "TP1"; exit_price = tp1; break
            if row["low"] <= stop:
                outcome = "SL"; exit_price = stop; break
        else:
            if row["low"] <= tp1:
                outcome = "TP1"; exit_price = tp1; break
            if row["high"] >= stop:
                outcome = "SL"; exit_price = stop; break

    if side == "long":
        pnl_pct = (exit_price - entry) / entry * 100 - FEES_RT_PCT
    else:
        pnl_pct = (entry - exit_price) / entry * 100 - FEES_RT_PCT

    return {
        "setup_id": setup.get("setup_id"),
        "setup_type": setup.get("setup_type"),
        "pair": setup.get("pair"),
        "side": side,
        "detected_at": setup.get("detected_at"),
        "outcome": outcome,
        "entry": entry,
        "exit": round(exit_price, 4),
        "pnl_pct": round(pnl_pct, 4),
        # 2026-05-11: regime + session for cross-dimension analysis
        "regime": setup.get("regime_label"),
        "session": setup.get("session_label"),
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default=None,
                    help="Filter all output to a single pair (e.g. BTCUSDT)")
    ap.add_argument("--detector", default=None,
                    help="Filter all output to a single detector substring")
    args = ap.parse_args()

    if not SETUPS.exists():
        print("[precision] no setups.jsonl"); return 0
    # 2026-05-30: price is now per-pair (see _prices_for_pair). No single frame.
    print("[precision] per-pair pricing (frozen + live tail)")

    seen = set()
    if OUTCOMES.exists():
        with OUTCOMES.open(encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line).get("setup_id"))
                except json.JSONDecodeError:
                    continue

    new_outcomes = []
    skipped = 0
    skipped_non_trade = 0
    with SETUPS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                setup = json.loads(line)
            except json.JSONDecodeError:
                continue
            if setup.get("setup_id") in seen:
                continue
            # Skip non-trade setups (grid management): they emit grid_action
            # and have recommended_size_btc=0.0. Their TP/SL are target levels
            # for grid bots, not entry/exit for a discrete trade.
            if (setup.get("grid_action")
                    or float(setup.get("recommended_size_btc") or 0) <= 0):
                skipped_non_trade += 1
                continue
            # Skip P-15 lifecycle (separate engine)
            stype = setup.get("setup_type") or ""
            if stype.startswith("p15_"):
                skipped_non_trade += 1
                continue
            pair = setup.get("pair") or "BTCUSDT"
            px = _prices_for_pair(pair)
            if px.empty:
                skipped += 1
                continue
            res = _evaluate(setup, px)
            if res is None:
                skipped += 1
                continue
            new_outcomes.append(res)

    if new_outcomes:
        OUTCOMES.parent.mkdir(parents=True, exist_ok=True)
        with OUTCOMES.open("a", encoding="utf-8") as f:
            for r in new_outcomes:
                f.write(json.dumps(r) + "\n")
    print(f"[precision] +{len(new_outcomes)} new outcomes, "
          f"skipped {skipped} (insufficient forward), "
          f"skipped {skipped_non_trade} (non-trade/p15)")

    # Aggregate
    all_outcomes = []
    if OUTCOMES.exists():
        with OUTCOMES.open(encoding="utf-8") as f:
            for line in f:
                try: all_outcomes.append(json.loads(line))
                except json.JSONDecodeError: continue
    if not all_outcomes:
        print("[precision] no outcomes yet"); return 0

    # Apply --pair / --detector filters
    if args.pair:
        all_outcomes = [o for o in all_outcomes if o.get("pair") == args.pair]
        print(f"[precision] filtered to pair={args.pair}: {len(all_outcomes)} outcomes")
    if args.detector:
        all_outcomes = [o for o in all_outcomes
                        if args.detector in str(o.get("setup_type", ""))]
        print(f"[precision] filtered to detector~={args.detector}: {len(all_outcomes)} outcomes")
    if not all_outcomes:
        print("[precision] no outcomes after filter"); return 0

    by_det = defaultdict(lambda: {"n": 0, "tp1": 0, "sl": 0, "timeout": 0,
                                    "pnls": []})
    for o in all_outcomes:
        d = by_det[o["setup_type"]]
        d["n"] += 1
        d[o["outcome"].lower() if o["outcome"] != "TP1" else "tp1"] += 1
        d["pnls"].append(float(o["pnl_pct"]))

    # Backtest expected expectancy per detector. Loaded from
    # config/backtest_expectancy.json if present (refresh by running
    # tools/_backtest_detectors_honest.py and updating the json).
    # Falls back to hardcoded defaults from 2026-05-10 research runs.
    BACKTEST_EXPECTANCY = _load_backtest_expectancy()

    rows = []
    for det, c in by_det.items():
        n = c["n"]
        pnls = c["pnls"]
        wr = c["tp1"] / n * 100 if n else 0
        exp = sum(pnls) / n if n else 0
        ci_lo, ci_hi = _bootstrap_ci(pnls, statistic_fn=lambda x: sum(x)/len(x) if x else 0)
        bt_exp = BACKTEST_EXPECTANCY.get(det)
        status = _status(n, ci_lo, ci_hi, exp, bt_exp)
        rows.append({
            "detector": det,
            "n": n,
            "tp1": c["tp1"],
            "sl": c["sl"],
            "timeout": c["timeout"],
            "wr_%": round(wr, 1),
            "exp_%": round(exp, 4),
            "ci95_lo": round(ci_lo, 4),
            "ci95_hi": round(ci_hi, 4),
            "bt_exp_%": bt_exp,
            "status": status,
        })
    df = pd.DataFrame(rows).sort_values("n", ascending=False)

    # Russian detector names
    DETECTOR_RU = {
        "long_dump_reversal": "LONG разворот после дампа",
        "long_pdl_bounce": "LONG отбой от PDL",
        "long_double_bottom": "LONG двойное дно",
        "long_multi_divergence": "LONG мульти-дивергенция",
        "long_rsi_momentum_ga": "LONG RSI momentum",
        "short_pdh_rejection": "SHORT от PDH",
        "short_rally_fade": "SHORT fade rally",
        "short_mfi_multi_ga": "SHORT MFI multi",
        "short_double_top": "SHORT двойная вершина",
        "short_div_bos_15m": "SHORT div BOS 15m",
        "short_overbought_fade": "SHORT overbought fade",
    }
    STATUS_RU = {
        "DEGRADED": "🚨 ПРОИГРЫВАЕТ",
        "EVALUATING": "🟡 НАКАПЛИВАЕТ",
        "STABLE": "🟢 СТАБИЛЬНО",
        "MARGINAL": "⚪ НЕЯСНО",
        "INSUFFICIENT": "⏳ МАЛО ДАННЫХ",
    }

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    print()
    print("📊 ТОЧНОСТЬ ДЕТЕКТОРОВ (paper trading за всё время)")
    print()

    for _, r in df.iterrows():
        det = r["detector"]
        n = r["n"]
        if n < 5: continue
        ru_name = DETECTOR_RU.get(det, det)
        status_ru = STATUS_RU.get(r["status"], r["status"])
        exp = r["exp_%"]
        exp_emoji = "✅" if exp > 0.01 else ("❌" if exp < -0.01 else "⚪")
        bt = r["bt_exp_%"]
        bt_str = f"+{bt:.3f}%" if bt and bt > 0 else (f"{bt:.3f}%" if bt is not None else "?")

        print(f"  {status_ru}  {ru_name}")
        print(f"     {n} сделок: TP1×{r['tp1']}  SL×{r['sl']}  timeout×{r['timeout']}")
        print(f"     {exp_emoji} в среднем {exp:+.3f}%/сделка  (бэктест: {bt_str})")

        # Plain-language explanation
        if r["status"] == "DEGRADED":
            print(f"     ⚠️  CI95 целиком ниже нуля → 95% уверенность что детектор хуже бэктеста")
            print(f"     💡 рекомендую: /disable {det}")
        elif r["status"] == "EVALUATING":
            print(f"     📈 CI95 целиком выше нуля → детектор работает, но N<100, ждём подтверждения")
        elif r["status"] == "INSUFFICIENT":
            print(f"     ⏳ нужно ≥30 сделок для уверенного вывода")
        elif r["status"] == "MARGINAL":
            print(f"     ⚪ CI95 пересекает 0 → нет однозначной картины")
        print()

    # Per-status summary
    statuses = df["status"].value_counts().to_dict()
    summary = ", ".join(f"{STATUS_RU.get(k,k)}: {v}" for k, v in statuses.items())
    print(f"📋 Итого: {summary}")
    print()

    # Highlight DEGRADED — actionable
    degraded = df[df["status"] == "DEGRADED"]
    if not degraded.empty:
        print("🚨 ДЕЙСТВИЕ НУЖНО:")
        for _, r in degraded.iterrows():
            det = r["detector"]
            ru_name = DETECTOR_RU.get(det, det)
            print(f"   • '{ru_name}' стабильно теряет деньги в paper trading")
            print(f"     → отправь в TG: /disable {det}")
        print()

    # ── Status transition detection (DEGRADED auto-notify) ────────────────
    # Skipped on filtered runs — see args.pair / args.detector handling below.
    current_status_map = dict(zip(df["detector"], df["status"]))
    prev_status_map: dict[str, str] = {}
    if PREV_STATUS.exists() and not (args.pair or args.detector):
        try:
            prev_status_map = json.loads(PREV_STATUS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev_status_map = {}

    transitions = []
    for det, cur_status in current_status_map.items():
        prev = prev_status_map.get(det)
        if prev == cur_status:
            continue
        # Only alert on entering DEGRADED — that's the actionable transition.
        if cur_status == "DEGRADED" and prev not in (None, "INSUFFICIENT"):
            row = df[df["detector"] == det].iloc[0]
            transitions.append(
                f"[DEGRADED] {det}: {prev} -> DEGRADED  "
                f"live exp {row['exp_%']:+.4f}% (CI [{row['ci95_lo']:+.4f}, "
                f"{row['ci95_hi']:+.4f}]) — consider /disable {det}"
            )
        # Also alert on recovery — DEGRADED → not-DEGRADED
        if prev == "DEGRADED" and cur_status != "DEGRADED":
            transitions.append(
                f"[RECOVERED] {det}: DEGRADED -> {cur_status}"
            )

    if transitions:
        print("\n=== STATUS TRANSITIONS (TG notify) ===")
        for t in transitions:
            print(f"  {t}")
        # Send to TG via done.py
        try:
            done_script = ROOT / "scripts" / "done.py"
            if done_script.exists():
                msg = "Precision status changes:\n" + "\n".join(transitions)
                import subprocess
                subprocess.run([sys.executable, str(done_script), msg],
                               cwd=str(ROOT), check=False, timeout=15)
        except Exception as exc:  # noqa: BLE001
            print(f"[precision] TG notify failed: {exc}", file=sys.stderr)

    # Save current status for next run's comparison — but ONLY when running
    # without filters. Filtered run produces an artificial subset and would
    # falsely flag DEGRADED→RECOVERED transitions if persisted.
    if not args.pair and not args.detector:
        try:
            PREV_STATUS.parent.mkdir(parents=True, exist_ok=True)
            PREV_STATUS.write_text(json.dumps(current_status_map, indent=2),
                                    encoding="utf-8")
        except OSError as exc:
            print(f"[precision] status save failed: {exc}", file=sys.stderr)
    else:
        print("[precision] (filtered run — prev_status not saved)")

    # Per (detector, pair) breakdown — surfaces pair-specific drift
    # that aggregate stats hide.
    by_det_pair = defaultdict(lambda: {"n": 0, "tp1": 0, "sl": 0, "timeout": 0,
                                         "pnls": []})
    for o in all_outcomes:
        key = (o["setup_type"], o.get("pair", "?"))
        d = by_det_pair[key]
        d["n"] += 1
        d[o["outcome"].lower() if o["outcome"] != "TP1" else "tp1"] += 1
        d["pnls"].append(float(o["pnl_pct"]))

    pair_rows = []
    for (det, pair), c in by_det_pair.items():
        if c["n"] < 5:
            continue  # too thin to render
        n = c["n"]
        pnls = c["pnls"]
        exp = sum(pnls) / n
        wr = c["tp1"] / n * 100
        pair_rows.append({
            "detector": det,
            "pair": pair,
            "n": n,
            "wr_%": round(wr, 1),
            "exp_%": round(exp, 4),
            "tp1": c["tp1"],
            "sl": c["sl"],
            "timeout": c["timeout"],
        })

    if pair_rows:
        df_pair = pd.DataFrame(pair_rows).sort_values(
            ["detector", "n"], ascending=[True, False],
        )
        print("\n=== Per (detector, pair) breakdown (N>=5) ===")
        print(df_pair.to_string(index=False))

        # Highlight detectors with strong cross-pair divergence:
        # if one pair has positive exp and another has clearly negative,
        # it's a candidate for pair-aware config (DISABLED_DETECTORS by pair).
        divergent = []
        for det in df_pair["detector"].unique():
            sub = df_pair[df_pair["detector"] == det]
            if len(sub) < 2: continue
            min_exp = sub["exp_%"].min()
            max_exp = sub["exp_%"].max()
            if min_exp < -0.05 and max_exp > 0.05:
                divergent.append((det, min_exp, max_exp))
        if divergent:
            print("\n[INSIGHT] detectors with cross-pair divergence:")
            for det, lo, hi in divergent:
                print(f"  {det}: best pair +{hi:.3f}%, worst pair {lo:+.3f}% "
                      f"— consider pair-aware disable")

    # Per (detector, regime) breakdown — surfaces regime-specific perf.
    # Only includes outcomes with regime field (added 2026-05-11; old
    # outcomes pre-this-change have regime=None and are skipped).
    by_det_regime = defaultdict(lambda: {"n": 0, "tp1": 0, "sl": 0, "timeout": 0,
                                           "pnls": []})
    for o in all_outcomes:
        regime = o.get("regime")
        if not regime: continue
        key = (o["setup_type"], regime)
        d = by_det_regime[key]
        d["n"] += 1
        d[o["outcome"].lower() if o["outcome"] != "TP1" else "tp1"] += 1
        d["pnls"].append(float(o["pnl_pct"]))

    regime_rows = []
    for (det, regime), c in by_det_regime.items():
        if c["n"] < 5: continue
        n = c["n"]
        pnls = c["pnls"]
        regime_rows.append({
            "detector": det,
            "regime": regime,
            "n": n,
            "wr_%": round(c["tp1"] / n * 100, 1),
            "exp_%": round(sum(pnls) / n, 4),
            "tp1": c["tp1"],
            "sl": c["sl"],
            "timeout": c["timeout"],
        })

    if regime_rows:
        df_regime = pd.DataFrame(regime_rows).sort_values(
            ["detector", "n"], ascending=[True, False],
        )
        print("\n=== Per (detector, regime) breakdown (N>=5) ===")
        print(df_regime.to_string(index=False))
    else:
        # Inform operator that this dimension is empty (waiting for fresh
        # outcomes after the 2026-05-11 schema update).
        print("\n(Per-regime breakdown empty — outcomes pre-2026-05-11 schema "
              "had no regime field. Will populate as new outcomes accumulate.)")

    # Per (detector, session) breakdown — surfaces session-specific perf.
    by_det_session = defaultdict(lambda: {"n": 0, "tp1": 0, "sl": 0, "timeout": 0,
                                            "pnls": []})
    for o in all_outcomes:
        session = o.get("session")
        if not session: continue
        key = (o["setup_type"], session)
        d = by_det_session[key]
        d["n"] += 1
        d[o["outcome"].lower() if o["outcome"] != "TP1" else "tp1"] += 1
        d["pnls"].append(float(o["pnl_pct"]))

    session_rows = []
    for (det, session), c in by_det_session.items():
        if c["n"] < 5: continue
        n = c["n"]
        pnls = c["pnls"]
        session_rows.append({
            "detector": det,
            "session": session,
            "n": n,
            "wr_%": round(c["tp1"] / n * 100, 1),
            "exp_%": round(sum(pnls) / n, 4),
            "tp1": c["tp1"],
            "sl": c["sl"],
            "timeout": c["timeout"],
        })

    if session_rows:
        df_session = pd.DataFrame(session_rows).sort_values(
            ["detector", "n"], ascending=[True, False],
        )
        print("\n=== Per (detector, session) breakdown (N>=5) ===")
        print(df_session.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
