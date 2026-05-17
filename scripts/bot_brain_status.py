"""Bot Brain status report — aggregates proposals + actions journals.

Reads:
  state/bot_brain_proposals.jsonl   — every rule-emitted proposal
  state/bot_brain_actions.jsonl     — actions.dispatch audit (live + dry-run)
  state/bot_brain_state.jsonl       — latest perception snapshot (for context)

Outputs structured text report:
  - Per rule: fires last 24h, breakdown by action × mode × tier
  - Per bot:  proposals received, actions applied
  - Recent live actions (last 24h)
  - Current snapshot summary

Usage:
    python scripts/bot_brain_status.py
    python scripts/bot_brain_status.py --hours 6
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "state" / "bot_brain_proposals.jsonl"
ACTIONS = ROOT / "state" / "bot_brain_actions.jsonl"
SNAPSHOT = ROOT / "state" / "bot_brain_state.jsonl"


def _read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _within(ts_iso: str, since: datetime) -> bool:
    try:
        ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts >= since
    except (ValueError, TypeError):
        return False


def report(hours: int = 24) -> str:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    lines: list[str] = []
    lines.append(f"=== Bot Brain status, last {hours}h ===")
    lines.append(f"  cutoff: {since.isoformat(timespec='seconds')}")
    lines.append("")

    # Proposals
    props = [p for p in _read_jsonl(PROPOSALS) if _within(p.get("ts", ""), since)]
    lines.append(f"PROPOSALS ({len(props)} in window)")
    if not props:
        lines.append("  — no proposals yet —")
    else:
        by_rule: Counter = Counter()
        by_rule_action_mode: dict = defaultdict(Counter)
        by_bot: dict = defaultdict(Counter)
        for p in props:
            rid = p.get("rule_id", "?")
            tier = p.get("tier", "?")
            mode = p.get("mode", "?")
            action = p.get("action", "?")
            by_rule[rid] += 1
            by_rule_action_mode[rid][(action, mode, tier)] += 1
            by_bot[tier][action] += 1
        for rid, cnt in by_rule.most_common():
            lines.append(f"  {rid:30}  total={cnt}")
            for (act, mode, tier), c in by_rule_action_mode[rid].most_common():
                lines.append(f"      → {act:15} {mode:8} tier={tier:8} ×{c}")
        lines.append("")
        lines.append(f"  Per bot:")
        for tier, actions in by_bot.items():
            actions_str = ", ".join(f"{a}×{c}" for a, c in actions.most_common())
            lines.append(f"    {tier:10}  {actions_str}")

    lines.append("")

    # Actions audit (live vs dry_run)
    acts = [a for a in _read_jsonl(ACTIONS) if _within(a.get("ts", ""), since)]
    lines.append(f"ACTIONS DISPATCHED ({len(acts)} in window)")
    if not acts:
        lines.append("  — no actions dispatched —")
    else:
        live = [a for a in acts if a.get("mode") == "live"]
        dry = [a for a in acts if a.get("mode") == "dry_run"]
        lines.append(f"  live={len(live)}  dry_run={len(dry)}")
        # Status breakdown for live actions
        by_status: Counter = Counter()
        for a in live:
            by_status[a.get("status", "?")] += 1
        for s, c in by_status.most_common():
            lines.append(f"    live status: {s:15} ×{c}")
        # Recent live actions (last 5)
        recent_live = sorted(live, key=lambda x: x.get("ts", ""))[-5:]
        if recent_live:
            lines.append("")
            lines.append("  Recent LIVE actions:")
            for a in recent_live:
                lines.append(f"    {a.get('ts', '?')[:19]}  "
                              f"{a.get('action', '?'):12} "
                              f"bot={a.get('bot_id', '?')} "
                              f"rule={a.get('rule_id', '?')} "
                              f"status={a.get('status', '?')}")

    lines.append("")

    # Current snapshot — latest line of state file
    snap_lines = list(_read_jsonl(SNAPSHOT))
    if snap_lines:
        snap = snap_lines[-1]
        lines.append("CURRENT SNAPSHOT")
        acct = snap.get("account", {})
        lines.append(f"  margin: ${acct.get('margin_balance_usd', '?')}  "
                      f"dist_to_liq: {acct.get('distance_to_liquidation_pct', '?')}%")
        for sym, mkt in snap.get("market", {}).items():
            lines.append(f"  {sym}: regime={mkt.get('regime_primary')} "
                          f"vol={mkt.get('vol_regime')} "
                          f"taker={mkt.get('taker_buy_pct')}% "
                          f"cascades_6h={len(mkt.get('cascades_recent', []))}")
        lines.append("  Bots:")
        for b in snap.get("bots", []):
            paused = " [PAUSED]" if b.get("paused_by_guard") else ""
            tb = " [TB]" if b.get("testbed") else ""
            lines.append(f"    {b.get('tier'):10}{tb}{paused}  "
                          f"pos={b.get('position_btc')}  "
                          f"profit=${b.get('current_profit_usd')}  "
                          f"dist_liq={b.get('dist_to_liq_pct')}%")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24,
                    help="window size in hours (default 24)")
    args = ap.parse_args()
    print(report(args.hours))


if __name__ == "__main__":
    main()
