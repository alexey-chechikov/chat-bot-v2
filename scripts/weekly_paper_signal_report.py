"""Weekly Paper Signal P&L Report.

Reads state/paper_signals.jsonl, aggregates closed signals over last N days
per source, per side, per context. Prints summary + writes
state/weekly_paper_signal_report.txt for TG/email forwarding.

Usage:
    python scripts/weekly_paper_signal_report.py            # last 7d
    python scripts/weekly_paper_signal_report.py --days 14  # last 14d
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.paper_signal_tracker.journal import JOURNAL_PATH, read_all


def _fmt_money(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}${x:,.2f}"


def aggregate(rows: list[dict], since: datetime) -> dict:
    by_source: dict = defaultdict(lambda: {
        "total": 0, "wins": 0, "losses": 0, "timeouts": 0, "pending": 0,
        "pnl_usd": 0.0, "by_side": defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0}),
        "by_context": defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0}),
    })
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts_signal"])
        except (KeyError, ValueError):
            continue
        if ts < since:
            continue
        src = r.get("source", "unknown")
        agg = by_source[src]
        agg["total"] += 1
        outcome = r.get("outcome")
        if outcome is None:
            agg["pending"] += 1
            continue
        pnl = float(r.get("pnl_usd") or 0)
        agg["pnl_usd"] += pnl
        side = r.get("side", "?")
        agg["by_side"][side]["n"] += 1
        agg["by_side"][side]["pnl"] += pnl
        ctx = r.get("context", "")
        agg["by_context"][ctx]["n"] += 1
        agg["by_context"][ctx]["pnl"] += pnl
        if outcome == "tp_hit":
            agg["wins"] += 1
            agg["by_side"][side]["wins"] += 1
            agg["by_context"][ctx]["wins"] += 1
        elif outcome == "sl_hit":
            agg["losses"] += 1
        else:
            agg["timeouts"] += 1
    return by_source


def format_report(agg: dict, since: datetime, until: datetime) -> str:
    days = (until - since).total_seconds() / 86400
    lines = [
        f"WEEKLY PAPER SIGNAL P&L REPORT",
        f"{since.strftime('%Y-%m-%d')} → {until.strftime('%Y-%m-%d')} ({days:.1f}d)",
        f"(paper @ $1k size, 0.5% SL, 0.75% TP, 2-4h hold, BitMEX taker fees)",
        "",
    ]
    if not agg:
        lines.append("No signals в окне.")
        return "\n".join(lines)

    sorted_sources = sorted(agg.items(), key=lambda kv: -kv[1]["pnl_usd"])
    for src, a in sorted_sources:
        closed = a["wins"] + a["losses"] + a["timeouts"]
        wr = (100.0 * a["wins"] / closed) if closed else 0.0
        lines.append(f"━━━ {src} ━━━")
        lines.append(f"  total: {a['total']} (closed: {closed}, pending: {a['pending']})")
        lines.append(f"  Wins: {a['wins']} ({wr:.0f}%) | SL: {a['losses']} | Timeout: {a['timeouts']}")
        lines.append(f"  PnL @ $1k: {_fmt_money(a['pnl_usd'])}")
        if a["by_side"]:
            sides = []
            for side, s in a["by_side"].items():
                s_wr = (100.0 * s["wins"] / s["n"]) if s["n"] else 0.0
                sides.append(f"{side}: {s['n']} sig {s_wr:.0f}%WR {_fmt_money(s['pnl'])}")
            lines.append(f"  by side: {' | '.join(sides)}")
        if a["by_context"] and len(a["by_context"]) <= 8:
            ctx_sorted = sorted(a["by_context"].items(), key=lambda kv: -kv[1]["pnl"])
            for ctx, c in ctx_sorted[:5]:
                c_wr = (100.0 * c["wins"] / c["n"]) if c["n"] else 0.0
                lines.append(f"    {ctx[:40]:40} n={c['n']:>3} WR={c_wr:>3.0f}% {_fmt_money(c['pnl'])}")
        lines.append("")

    total_pnl = sum(a["pnl_usd"] for a in agg.values())
    total_n = sum(a["total"] for a in agg.values())
    lines.append(f"━━━ TOTAL: {total_n} signals, PnL {_fmt_money(total_pnl)} ━━━")
    lines.append("")
    lines.append("Verdict hints:")
    lines.append("  win_rate >= 55% AND PnL > $50/wk → consider automation")
    lines.append("  win_rate 40-55% AND PnL ≈ 0       → tune filter (drop bad contexts)")
    lines.append("  win_rate < 40% OR PnL < -$50/wk   → kill source entirely")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    until = datetime.now(timezone.utc)
    since = until - timedelta(days=args.days)
    rows = read_all(path=JOURNAL_PATH)
    agg = aggregate(rows, since)
    report = format_report(agg, since, until)
    print(report)

    out_path = ROOT / "state" / "weekly_paper_signal_report.txt"
    try:
        out_path.write_text(report, encoding="utf-8")
        print(f"\nReport saved to {out_path.relative_to(ROOT)}")
    except OSError:
        pass


if __name__ == "__main__":
    main()
