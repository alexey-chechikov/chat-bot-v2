"""Empirical conf-vs-actual-WR curve for setup_detector setups.

Reads state/setup_outcomes.jsonl (status transitions of detected setups)
and pairs each detect with its eventual outcome. Buckets by setup type
and by confidence_pct; reports the actual win-rate per bucket so the
operator can SEE whether confidence_pct is a calibrated probability
(e.g. 80% conf -> 80% WR) or a vanity number.

Win definition: outcome status 'tp1_hit' or 'tp2_hit' = win;
'stop_hit' = loss; 'expired' with hypothetical_pnl > 0 = soft win,
< 0 = soft loss; else excluded.

Run:
    .venv/bin/python3 scripts/pump_research/_setup_conf_calibration.py
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
SETUPS = ROOT / "state" / "setups.jsonl"
OUTCOMES = ROOT / "state" / "setup_outcomes.jsonl"


def _load_setups() -> dict:
    """setup_id -> {setup_type, confidence_pct, strength}."""
    out = {}
    if not SETUPS.exists():
        return out
    with SETUPS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                sid = r.get("setup_id")
                if not sid:
                    continue
                out[sid] = {
                    "setup_type": r.get("setup_type"),
                    "confidence_pct": float(r.get("confidence_pct") or 0),
                    "strength": int(r.get("strength") or 0),
                }
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    return out


def _load_outcomes() -> list:
    """List of dicts with setup_id + new_status + hypothetical_pnl_usd."""
    out = []
    if not OUTCOMES.exists():
        return out
    with OUTCOMES.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _classify(status: str, pnl) -> str:
    """Win / Loss / Skip."""
    if status in ("tp1_hit", "tp2_hit"):
        return "W"
    if status == "stop_hit":
        return "L"
    if status == "expired":
        if pnl is None:
            return "skip"
        try:
            return "W" if float(pnl) > 0 else "L"
        except (TypeError, ValueError):
            return "skip"
    return "skip"


def main():
    setups = _load_setups()
    outcomes = _load_outcomes()
    print(f"setups detected: {len(setups)}    outcome events: {len(outcomes)}")
    # take FINAL outcome per setup_id (latest status transition)
    by_sid: dict = {}
    for r in outcomes:
        sid = r.get("setup_id")
        if not sid:
            continue
        by_sid[sid] = r  # last wins (jsonl chronological)
    paired = 0
    by_type = defaultdict(list)  # type -> [(conf, W/L)]
    by_bucket_all = defaultdict(list)  # conf-bucket -> [W/L]
    for sid, meta in setups.items():
        oc = by_sid.get(sid)
        if not oc:
            continue
        cls = _classify(oc.get("new_status", ""), oc.get("hypothetical_pnl_usd"))
        if cls == "skip":
            continue
        paired += 1
        by_type[meta["setup_type"]].append((meta["confidence_pct"], cls))
        # bucket
        c = meta["confidence_pct"]
        if c < 60:
            b = "<60"
        elif c < 70:
            b = "60-70"
        elif c < 75:
            b = "70-75"
        elif c < 80:
            b = "75-80"
        elif c < 85:
            b = "80-85"
        elif c < 90:
            b = "85-90"
        else:
            b = "90+"
        by_bucket_all[b].append(cls)

    print(f"paired with non-skip outcome: {paired}\n")

    print("=== ALL setups — confidence bucket vs actual WR ===")
    print(f"{'bucket':>7} {'n':>5} {'wins':>5} {'WR':>7}")
    order = ["<60", "60-70", "70-75", "75-80", "80-85", "85-90", "90+"]
    for b in order:
        cls_list = by_bucket_all.get(b, [])
        if not cls_list:
            continue
        n = len(cls_list)
        w = sum(1 for c in cls_list if c == "W")
        wr = 100 * w / n
        print(f"{b:>7} {n:>5} {w:>5} {wr:>6.1f}%")

    print("\n=== per setup_type — n, mean conf, WR ===")
    print(f"{'type':<35} {'n':>4} {'mean_conf':>10} {'WR':>7}")
    rows = []
    for t, lst in by_type.items():
        n = len(lst)
        if n < 5:
            continue
        mean_c = sum(c for c, _ in lst) / n
        wins = sum(1 for _, cls in lst if cls == "W")
        wr = 100 * wins / n
        rows.append((t, n, mean_c, wr))
    for t, n, mc, wr in sorted(rows, key=lambda x: -x[1]):
        print(f"{t:<35} {n:>4} {mc:>9.1f}% {wr:>6.1f}%")


if __name__ == "__main__":
    main()
