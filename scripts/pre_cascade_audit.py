"""Pre-cascade signal audit — precision/recall vs actual cascade fires.

For each pre-cascade fire (from `pre_cascade_fires.jsonl` — OI+funding+LS
detector — and `liq_pre_cascade_fires.jsonl` — liq-clustering detector),
check whether a real cascade in the same direction fired within
WINDOW_MIN minutes after the pre-cascade signal.

Outputs:
  - Per-signal precision   = (fires followed by matching cascade) / total fires
  - Per-signal recall      = (cascades preceded by matching pre-fire) / total cascades
  - F1 score
  - Random baseline        = expected hit-rate if pre-cascade signal had no info

Inputs:
  state/pre_cascade_fires.jsonl       — direction = expected_cascade_direction
  state/liq_pre_cascade_fires.jsonl   — direction = side
  state/cascade_accuracy.jsonl        — direction + ts of real cascades

Usage:
    python scripts/pre_cascade_audit.py
    python scripts/pre_cascade_audit.py --window-min 60
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE_OI_FIRES = ROOT / "state" / "pre_cascade_fires.jsonl"
PRE_LIQ_FIRES = ROOT / "state" / "liq_pre_cascade_fires.jsonl"
CASCADES = ROOT / "state" / "cascade_accuracy.jsonl"


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _normalize_pre(records: list[dict], source: str) -> list[dict]:
    out = []
    for r in records:
        ts_iso = r.get("ts")
        if not ts_iso:
            continue
        try:
            ts = _parse_ts(ts_iso)
        except ValueError:
            continue
        if source == "oi":
            direction = r.get("expected_cascade_direction")
        else:  # liq clustering: side IS expected continuation
            direction = r.get("side")
        if not direction:
            continue
        out.append({"ts": ts, "direction": direction, "source": source})
    return sorted(out, key=lambda x: x["ts"])


def _normalize_cascades(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        ts_iso = r.get("ts")
        if not ts_iso:
            continue
        try:
            ts = _parse_ts(ts_iso)
        except ValueError:
            continue
        out.append({"ts": ts, "direction": r.get("direction"),
                    "qty_btc": r.get("qty_btc"),
                    "threshold_btc": r.get("threshold_btc")})
    return sorted(out, key=lambda x: x["ts"])


def analyze(pre: list[dict], casc: list[dict], window_min: int) -> dict:
    """For each pre-fire, find cascades within [ts, ts+window_min].
    For each cascade, find pre-fires within [ts-window_min, ts]."""
    window = timedelta(minutes=window_min)
    tp = 0  # true positives — pre-fire followed by matching cascade
    fp = 0  # false positives — pre-fire not followed by matching cascade
    for pf in pre:
        matched = any(
            pf["ts"] <= c["ts"] <= pf["ts"] + window
            and c["direction"] == pf["direction"]
            for c in casc
        )
        if matched:
            tp += 1
        else:
            fp += 1

    fn = 0  # false negatives — cascade not preceded by matching pre-fire
    matched_casc = 0
    for c in casc:
        matched = any(
            c["ts"] - window <= pf["ts"] <= c["ts"]
            and c["direction"] == pf["direction"]
            for pf in pre
        )
        if matched:
            matched_casc += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = matched_casc / (matched_casc + fn) if (matched_casc + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    # Random baseline: if pre-fire timestamps were random, what's the chance a
    # 30-min forward window contains a same-direction cascade?
    if pre and casc:
        period_start = min(pre[0]["ts"], casc[0]["ts"])
        period_end = max(pre[-1]["ts"], casc[-1]["ts"])
        total_minutes = (period_end - period_start).total_seconds() / 60.0
        n_long = sum(1 for c in casc if c["direction"] == "long")
        n_short = sum(1 for c in casc if c["direction"] == "short")
        # For a specific direction pre-fire, baseline = window_min / total × n_same_dir
        baseline_long = min(1.0, window_min * n_long / total_minutes) if total_minutes else 0
        baseline_short = min(1.0, window_min * n_short / total_minutes) if total_minutes else 0
        # Mix per actual pre-fire distribution
        n_pre_long = sum(1 for p in pre if p["direction"] == "long")
        n_pre_short = sum(1 for p in pre if p["direction"] == "short")
        n_pre_total = max(n_pre_long + n_pre_short, 1)
        baseline = (baseline_long * n_pre_long + baseline_short * n_pre_short) / n_pre_total
    else:
        baseline = 0

    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "baseline_precision_random": round(baseline, 3),
        "edge_over_baseline_pp": round((precision - baseline) * 100, 1),
        "n_pre_fires": len(pre),
        "n_cascades": len(casc),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-min", type=int, default=30,
                    help="forward window (min) within which a cascade must follow pre-fire")
    args = ap.parse_args()

    oi_pre = _normalize_pre(_read(PRE_OI_FIRES), source="oi")
    liq_pre = _normalize_pre(_read(PRE_LIQ_FIRES), source="liq_cluster")
    casc = _normalize_cascades(_read(CASCADES))

    print(f"=== Pre-cascade audit, window={args.window_min}min ===")
    print(f"Data: oi_fires={len(oi_pre)}  liq_cluster_fires={len(liq_pre)}  cascades={len(casc)}")
    if casc:
        print(f"  period: {casc[0]['ts'].isoformat()} → {casc[-1]['ts'].isoformat()}")

    for label, pre in [("OI+funding+LS", oi_pre),
                        ("liq_clustering", liq_pre),
                        ("BOTH combined", sorted(oi_pre + liq_pre, key=lambda x: x["ts"]))]:
        print(f"\n--- {label} ---")
        r = analyze(pre, casc, args.window_min)
        for k, v in r.items():
            print(f"  {k:30}  {v}")


if __name__ == "__main__":
    main()
