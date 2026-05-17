"""Pre-cascade feature search — find co-triggers that boost liq_cluster precision.

Audit 2026-05-17 baseline: liq_cluster fires with precision 43.8% / recall 65.3%
within 30 min. Hypothesis: filtering fires by additional features (OI delta,
funding direction, taker imbalance, LS ratio) raises precision to 55-60%.

Method:
  1. Load all liq_cluster fires (state/liq_pre_cascade_fires.jsonl).
  2. For each fire, find the deriv_live state at fire time (closest row in
     state/deriv_live_history.jsonl by timestamp).
  3. Label fire as HIT or MISS based on whether a same-side cascade fired
     within 30 min (using state/cascade_accuracy.jsonl).
  4. For each candidate feature, compute precision conditional on feature
     threshold; rank by precision lift vs baseline.

Features tested:
  - oi_change_1h_pct (rising/falling)
  - funding_rate_8h (sign + magnitude)
  - taker_buy_pct (continuation: short-side cluster + low taker = strong)
  - global_ls_ratio (crowding)
  - top_trader_long_pct - global_long_pct (smart-money divergence)
  - premium_pct (futures-spot basis)
  - oi_change_1h × side alignment (OI rising on short-side cluster = more bearish setup)

Usage:
    python scripts/pre_cascade_feature_search.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
LIQ_FIRES = ROOT / "state" / "liq_pre_cascade_fires.jsonl"
DERIV_HISTORY = ROOT / "state" / "deriv_live_history.jsonl"
CASCADES = ROOT / "state" / "cascade_accuracy.jsonl"

WINDOW_MIN = 30


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _find_deriv_near(deriv: list[dict], target_ts: datetime,
                     max_gap_sec: int = 600) -> Optional[dict]:
    """Find deriv_live snapshot closest to target_ts (within max_gap_sec)."""
    best = None
    best_gap = float("inf")
    for d in deriv:
        ts_iso = d.get("last_updated")
        if not ts_iso:
            continue
        try:
            ts = _parse_ts(ts_iso)
        except ValueError:
            continue
        gap = abs((ts - target_ts).total_seconds())
        if gap < best_gap and gap <= max_gap_sec:
            best_gap = gap
            best = d
    return best


def _extract_features(deriv_row: dict) -> dict:
    """Pull BTC-symbol features (cascade detection is BTC-centric)."""
    btc = deriv_row.get("BTCUSDT", {}) or {}
    eth = deriv_row.get("ETHUSDT", {}) or {}
    xrp = deriv_row.get("XRPUSDT", {}) or {}

    def _f(d, k):
        v = d.get(k)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    tt_long = _f(btc, "top_trader_long_pct")
    gl_long = _f(btc, "global_long_account_pct")
    smart_div = (tt_long - gl_long) if (tt_long is not None and gl_long is not None) else None

    return {
        "btc_oi_1h_pct": _f(btc, "oi_change_1h_pct"),
        "btc_funding": _f(btc, "funding_rate_8h"),
        "btc_taker_buy": _f(btc, "taker_buy_pct"),
        "btc_ls": _f(btc, "global_ls_ratio"),
        "btc_premium": _f(btc, "premium_pct"),
        "smart_div": smart_div,
        "eth_taker_buy": _f(eth, "taker_buy_pct"),
        "xrp_taker_buy": _f(xrp, "taker_buy_pct"),
    }


def _label_fire(fire: dict, cascades: list[dict]) -> bool:
    """True if matching-direction cascade fired within WINDOW_MIN after fire."""
    try:
        f_ts = _parse_ts(fire["ts"])
    except (ValueError, KeyError):
        return False
    f_side = fire.get("side")
    window_end = f_ts + timedelta(minutes=WINDOW_MIN)
    for c in cascades:
        try:
            c_ts = _parse_ts(c["ts"])
        except (ValueError, KeyError):
            continue
        if f_ts <= c_ts <= window_end and c.get("direction") == f_side:
            return True
    return False


def build_dataset() -> list[dict]:
    fires = _read_jsonl(LIQ_FIRES)
    deriv = _read_jsonl(DERIV_HISTORY)
    cascades = _read_jsonl(CASCADES)

    rows = []
    for f in fires:
        try:
            f_ts = _parse_ts(f["ts"])
        except (ValueError, KeyError):
            continue
        d = _find_deriv_near(deriv, f_ts)
        if d is None:
            continue
        feats = _extract_features(d)
        hit = _label_fire(f, cascades)
        rows.append({
            "ts": f["ts"], "side": f.get("side"), "qty_btc": f.get("qty_btc"),
            "hit": hit, **feats,
        })
    return rows


def evaluate_split(rows: list[dict], feature: str, side: str,
                   *, op: str, threshold: float) -> dict:
    """Evaluate precision when we apply (feature OP threshold) as filter for side."""
    sub = [r for r in rows if r["side"] == side and r.get(feature) is not None]
    if op == ">":
        kept = [r for r in sub if r[feature] > threshold]
    elif op == "<":
        kept = [r for r in sub if r[feature] < threshold]
    elif op == ">=":
        kept = [r for r in sub if r[feature] >= threshold]
    else:
        kept = [r for r in sub if r[feature] <= threshold]
    if not kept:
        return {"n": 0, "precision": None}
    tp = sum(1 for r in kept if r["hit"])
    return {"n": len(kept), "tp": tp, "precision": round(tp / len(kept), 3),
            "skipped": len(sub) - len(kept)}


def main():
    rows = build_dataset()
    if not rows:
        print("no data")
        return

    print(f"=== Pre-cascade feature search ===")
    print(f"Total fires with matched deriv state: {len(rows)}")
    long_rows = [r for r in rows if r["side"] == "long"]
    short_rows = [r for r in rows if r["side"] == "short"]
    print(f"  long-side: {len(long_rows)}  hits={sum(1 for r in long_rows if r['hit'])}  baseline precision={sum(1 for r in long_rows if r['hit'])/max(len(long_rows),1):.3f}")
    print(f"  short-side: {len(short_rows)}  hits={sum(1 for r in short_rows if r['hit'])}  baseline precision={sum(1 for r in short_rows if r['hit'])/max(len(short_rows),1):.3f}")

    # Candidate filters per side
    # short-side cluster expects SHORT cascade (continuation, price up):
    #   - OI rising signals more positions piling in (bearish setup → cascade up)
    #   - Taker_buy LOW signals selling pressure (matches short-cluster)
    #   - LS_ratio > 1.3 = longs crowded = squeeze candidate
    short_filters = [
        ("btc_oi_1h_pct", ">", 0.3),
        ("btc_oi_1h_pct", ">", 0.5),
        ("btc_oi_1h_pct", ">", 0.8),
        ("btc_taker_buy", "<", 45),
        ("btc_taker_buy", "<", 42),
        ("btc_taker_buy", "<", 38),
        ("btc_ls", ">", 1.5),
        ("btc_ls", ">", 1.8),
        ("btc_funding", ">", 0.00003),
        ("btc_premium", "<", 0),
    ]
    long_filters = [
        ("btc_oi_1h_pct", "<", -0.3),
        ("btc_oi_1h_pct", "<", -0.5),
        ("btc_taker_buy", ">", 55),
        ("btc_taker_buy", ">", 58),
        ("btc_taker_buy", ">", 62),
        ("btc_ls", "<", 0.7),
        ("btc_ls", "<", 0.55),
        ("btc_funding", "<", -0.00003),
        ("btc_premium", ">", 0),
    ]

    for side, filters, baseline in [("short", short_filters,
                                     sum(1 for r in short_rows if r['hit']) / max(len(short_rows), 1)),
                                     ("long", long_filters,
                                      sum(1 for r in long_rows if r['hit']) / max(len(long_rows), 1))]:
        print(f"\n--- {side}-side filters (baseline precision {baseline:.3f}) ---")
        results = []
        for feat, op, thr in filters:
            r = evaluate_split(rows, feat, side, op=op, threshold=thr)
            if r["n"] >= 5:  # min sample
                lift = r["precision"] - baseline if r["precision"] is not None else 0
                results.append((feat, op, thr, r, lift))
        results.sort(key=lambda x: -(x[4] or 0))
        for feat, op, thr, r, lift in results:
            print(f"  {feat:18}  {op}  {thr:>7}   n={r['n']:>3}  tp={r.get('tp', 0):>2}  "
                  f"precision={r['precision']}   lift={lift:+.3f}")


if __name__ == "__main__":
    main()
