"""Range Hunter status — read journal and print metrics.

Looks for state/range_hunter_signals.jsonl in:
  1. $BOT7_PATH/state/range_hunter_signals.jsonl (env var)
  2. /Users/<user>/code/bot7/state/range_hunter_signals.jsonl (mac default)
  3. C:/bot7/state/range_hunter_signals.jsonl (win default)
  4. ./state/range_hunter_signals.jsonl (cwd)

Output: human-readable summary + JSON dump for parsing.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_journal() -> Path | None:
    candidates = []
    env_path = os.environ.get("BOT7_PATH")
    if env_path:
        candidates.append(Path(env_path) / "state" / "range_hunter_signals.jsonl")
    candidates.extend([
        Path.home() / "code" / "bot7" / "state" / "range_hunter_signals.jsonl",
        Path("C:/bot7/state/range_hunter_signals.jsonl"),
        Path.cwd() / "state" / "range_hunter_signals.jsonl",
    ])
    for p in candidates:
        if p.exists():
            return p
    return None


def read_jsonl(path: Path) -> list[dict]:
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


def compute_stats(rows: list[dict]) -> dict:
    if not rows:
        return {"status": "no_data", "total": 0}

    placed = [r for r in rows if r.get("user_action") == "placed"]
    skipped = [r for r in rows if r.get("user_action") == "skipped"]
    pending = [r for r in rows if r.get("user_action") is None]

    closed = [r for r in placed if r.get("exit_reason") is not None]
    pair_win = [r for r in closed if r.get("exit_reason") == "pair_win"]

    pnls = [float(r.get("pnl_usd") or 0) for r in closed]
    total_pnl = sum(pnls)

    by_outcome: dict[str, int] = {}
    for r in closed:
        by_outcome[r.get("exit_reason", "unknown")] = by_outcome.get(r.get("exit_reason", "unknown"), 0) + 1

    legs_2 = sum(1 for r in closed if r.get("legs_filled") == 2)
    legs_1 = sum(1 for r in closed if r.get("legs_filled") == 1)
    legs_0 = sum(1 for r in closed if r.get("legs_filled") == 0)
    total_legs_placed = 2 * len(closed)
    total_legs_filled = 2 * legs_2 + legs_1
    fill_rate = (total_legs_filled / total_legs_placed) if total_legs_placed else None

    latencies = [r["decision_latency_sec"] for r in placed if r.get("decision_latency_sec") is not None]
    avg_latency = (sum(latencies) / len(latencies)) if latencies else None

    last_signal = rows[-1].get("ts_signal") if rows else None

    # Health flags
    health = []
    if fill_rate is not None and fill_rate < 0.65 and len(closed) >= 10:
        health.append("FILL_RATE_LOW: edge may be dying (< 0.65)")
    if closed and len(pair_win) / len(closed) < 0.50 and len(closed) >= 10:
        health.append("PAIR_WIN_LOW: < 50% pair wins")
    if total_pnl < -200 and len(closed) >= 10:
        health.append(f"CUMULATIVE_LOSS: ${total_pnl:.0f} loss")

    return {
        "total": len(rows),
        "placed": len(placed),
        "skipped": len(skipped),
        "pending_decision": len(pending),
        "closed": len(closed),
        "pair_win_count": len(pair_win),
        "pair_win_pct": round(100 * len(pair_win) / len(closed), 1) if closed else None,
        "by_outcome": by_outcome,
        "legs_filled_2": legs_2,
        "legs_filled_1": legs_1,
        "legs_filled_0": legs_0,
        "empirical_fill_rate": round(fill_rate, 3) if fill_rate is not None else None,
        "total_pnl_usd": round(total_pnl, 2),
        "avg_decision_latency_sec": round(avg_latency, 1) if avg_latency is not None else None,
        "last_signal_ts": last_signal,
        "health_warnings": health,
    }


def main():
    path = find_journal()
    if path is None:
        print("ERROR: state/range_hunter_signals.jsonl not found in any standard location.")
        print("Searched: $BOT7_PATH, ~/code/bot7, C:/bot7, ./state")
        sys.exit(1)

    rows = read_jsonl(path)
    stats = compute_stats(rows)

    # Human-readable
    print(f"=== Range Hunter status ===")
    print(f"Journal: {path}")
    print(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print()
    if stats.get("status") == "no_data" or stats.get("total", 0) == 0:
        print("No signals yet - journal is empty.")
        print("Check that signal_loop is running (logs/app.log -> range_hunter.signal_loop.start)")
        print()
        print("--- JSON ---")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return
    else:
        print(f"Signals total:    {stats['total']}")
        print(f"  Placed:         {stats['placed']}")
        print(f"  Skipped:        {stats['skipped']}")
        print(f"  Pending decision: {stats['pending_decision']}")
        print(f"  Closed:         {stats['closed']}")
        print()
        if stats["closed"]:
            print(f"Pair-win:         {stats['pair_win_count']}/{stats['closed']} = {stats['pair_win_pct']}% (target: 68.5%)")
            print(f"Empirical fill rate: {stats['empirical_fill_rate']} (target: >= 0.65)")
            print(f"Total PnL:        ${stats['total_pnl_usd']}")
            if stats["avg_decision_latency_sec"] is not None:
                print(f"Avg decision latency: {stats['avg_decision_latency_sec']}s")
            print(f"By outcome: {stats['by_outcome']}")
        if stats["last_signal_ts"]:
            print(f"Last signal: {stats['last_signal_ts']}")
        if stats["health_warnings"]:
            print()
            print("[!] HEALTH WARNINGS:")
            for w in stats["health_warnings"]:
                print(f"  - {w}")

    # JSON dump for parsing
    print()
    print("--- JSON ---")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
