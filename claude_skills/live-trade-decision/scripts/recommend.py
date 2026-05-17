"""Live trade decision support — pull recent live history + drift flags.

Usage:
  python recommend.py --signal-type range_hunter
  python recommend.py --signal-type cascade
  python recommend.py --signal-type mega

Outputs:
  - Recent N trades of same type (default 20)
  - WR, avg PnL, fill rate (if applicable)
  - Drift flags from cascade_edge_drift.json
  - Cliff_monitor margin alerts
  - JSON dump for parsing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_state_dir() -> Path | None:
    candidates = []
    env = os.environ.get("BOT7_PATH")
    if env:
        candidates.append(Path(env) / "state")
    candidates.extend([
        Path.home() / "code" / "bot7" / "state",
        Path("C:/bot7/state"),
        Path.cwd() / "state",
    ])
    for p in candidates:
        if p.exists():
            return p
    return None


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def analyze_range_hunter(state: Path, last_n: int = 20) -> dict:
    rows = read_jsonl(state / "range_hunter_signals.jsonl")
    placed = [r for r in rows if r.get("user_action") == "placed"]
    closed = [r for r in placed if r.get("exit_reason") is not None]
    recent = closed[-last_n:] if len(closed) > last_n else closed

    if not recent:
        return {"signal_type": "range_hunter", "n_closed": 0, "verdict": "INSUFFICIENT_DATA"}

    pair_wins = [r for r in recent if r.get("exit_reason") == "pair_win"]
    pnls = [float(r.get("pnl_usd") or 0) for r in recent]
    legs_filled = [int(r.get("legs_filled") or 0) for r in recent]
    fill_rate = sum(legs_filled) / (2 * len(recent))
    wr = len(pair_wins) / len(recent) * 100

    health = []
    if wr < 50 and len(recent) >= 10:
        health.append(f"WR_LOW: {wr:.0f}% over last {len(recent)} closed")
    if fill_rate < 0.65 and len(recent) >= 10:
        health.append(f"FILL_RATE_LOW: {fill_rate:.2f} (need >= 0.65)")
    # Consecutive losses
    last_5 = recent[-5:] if len(recent) >= 5 else recent
    consec_loss = sum(1 for r in last_5 if (r.get("pnl_usd") or 0) <= 0)
    if consec_loss >= 3 and len(last_5) >= 3:
        health.append(f"CONSEC_LOSSES: {consec_loss}/5 recent losses")

    if not health and wr >= 60:
        verdict = "GO"
    elif health:
        verdict = "SKIP"
    else:
        verdict = "CAUTION"

    return {
        "signal_type": "range_hunter",
        "n_closed": len(recent),
        "wr_pct": round(wr, 1),
        "wr_backtest": 68.5,
        "fill_rate": round(fill_rate, 3),
        "fill_rate_backtest": 1.0,
        "fill_rate_threshold": 0.65,
        "avg_pnl_usd": round(sum(pnls) / len(pnls), 2),
        "total_pnl_usd": round(sum(pnls), 2),
        "consec_losses_last5": consec_loss,
        "health_warnings": health,
        "verdict": verdict,
    }


def analyze_cascade(state: Path) -> dict:
    drift = read_json(state / "cascade_edge_drift.json")
    accuracy = read_jsonl(state / "cascade_accuracy.jsonl")

    drifted_buckets = [k for k, v in drift.items() if isinstance(v, dict) and v.get("drifted")]
    health = []
    if drifted_buckets:
        health.append(f"DRIFTED: {drifted_buckets}")

    # Recent accuracy entries
    recent = accuracy[-20:] if len(accuracy) > 20 else accuracy
    n_evaluated = sum(1 for r in recent if r.get("correct_12h") is not None)
    n_correct = sum(1 for r in recent if r.get("correct_12h") is True)
    wr = (n_correct / n_evaluated * 100) if n_evaluated else None

    return {
        "signal_type": "cascade",
        "drifted_buckets": drifted_buckets,
        "recent_evaluated": n_evaluated,
        "recent_wr_12h_pct": round(wr, 1) if wr is not None else None,
        "health_warnings": health,
        "verdict": "SKIP" if drifted_buckets else ("GO" if wr and wr >= 60 else "CAUTION"),
    }


def check_margin_alerts(state: Path) -> list[str]:
    """Check cliff_monitor state for active margin warnings."""
    cliff = read_json(state / "short_t2_cliff_alerts.json")
    alerts = []
    for key, entry in cliff.items():
        if isinstance(entry, dict) and entry.get("severity") in ("warning", "danger"):
            alerts.append(f"{key}: {entry.get('severity')} ${entry.get('unrealized_usd', 0):.0f}")
    return alerts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-type", required=True,
                        choices=["range_hunter", "cascade", "mega"])
    parser.add_argument("--last-n", type=int, default=20)
    args = parser.parse_args()

    state = find_state_dir()
    if state is None:
        print("ERROR: state/ dir not found")
        sys.exit(1)

    margin_alerts = check_margin_alerts(state)

    if args.signal_type == "range_hunter":
        report = analyze_range_hunter(state, args.last_n)
    elif args.signal_type == "cascade":
        report = analyze_cascade(state)
    elif args.signal_type == "mega":
        report = {"signal_type": "mega", "verdict": "MANUAL_CHECK", "note": "Read state/setups.jsonl for last mega-setup outcomes"}
    else:
        print(f"Unknown signal type: {args.signal_type}")
        sys.exit(1)

    if margin_alerts:
        if report.get("verdict") not in ("SKIP",):
            report["verdict"] = "SKIP"
        report.setdefault("health_warnings", []).extend([f"MARGIN_ALERT: {a}" for a in margin_alerts])

    print(f"=== Live trade decision support ===")
    print(f"Signal type: {args.signal_type}")
    print(f"State dir: {state}")
    print(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print()
    for k, v in report.items():
        if isinstance(v, list) and v:
            print(f"{k}:")
            for x in v:
                print(f"  - {x}")
        else:
            print(f"{k}: {v}")
    print()
    print("--- JSON ---")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
