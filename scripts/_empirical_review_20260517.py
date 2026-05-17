#!/usr/bin/env python3
"""
Empirical review 2026-05-07 → 2026-05-17 (~10 days live).
Reads bot7 state files and computes metrics for the EMPIRICAL_2026-05-17.md report.
"""
import json
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path

STATE = Path("/Users/alexeychechikov/code/bot7/state")
MARKET = Path("/Users/alexeychechikov/code/bot7/market_live")

PERIOD_START = datetime(2026, 5, 7, 0, 0, 0, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 5, 17, 23, 59, 59, tzinfo=timezone.utc)


def parse_ts(s):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def in_period(ts):
    return ts is not None and PERIOD_START <= ts <= PERIOD_END


def read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def section_range_hunter():
    print("\n===== §1 RANGE HUNTER =====")
    files = {
        "BTCUSDT": STATE / "range_hunter_signals.jsonl",
        "ETHUSDT": STATE / "range_hunter_signals_ETHUSDT.jsonl",
        "XRPUSDT": STATE / "range_hunter_signals_XRPUSDT.jsonl",
    }
    all_rows = []
    for sym, p in files.items():
        for r in read_jsonl(p):
            r["_symbol"] = r.get("symbol") or sym
            r["_ts"] = parse_ts(r.get("ts_signal"))
            all_rows.append(r)

    in_range = [r for r in all_rows if in_period(r["_ts"])]
    print(f"Total signals raw: {len(all_rows)}; in period 5-07..5-17: {len(in_range)}")

    by_sym = defaultdict(list)
    for r in in_range:
        by_sym[r["_symbol"]].append(r)

    print("\nPer symbol:")
    for sym, lst in sorted(by_sym.items()):
        var_count = Counter(r.get("variant", "?") for r in lst)
        placed = sum(1 for r in lst if r.get("user_action") == "placed")
        with_pnl = [r for r in lst if r.get("pnl_usd") is not None]
        total_pnl = sum(r.get("pnl_usd") or 0 for r in with_pnl)
        first_ts = min((r["_ts"] for r in lst), default=None)
        last_ts = max((r["_ts"] for r in lst), default=None)
        print(f"  {sym}: emits={len(lst)} variants={dict(var_count)} placed={placed} closed_with_pnl={len(with_pnl)} total_pnl=${total_pnl:.2f}")
        print(f"    first={first_ts}  last={last_ts}")

    if in_range:
        sample = in_range[0]
        print(f"\nSchema fields in sample: {list(sample.keys())[:20]}")
    has_event = any("event" in r for r in in_range)
    has_bar = any("bar_minutes" in r for r in in_range)
    has_ls = any("levels_source" in r for r in in_range)
    print(f"event field present? {has_event}; bar_minutes? {has_bar}; levels_source? {has_ls}")
    print("NOTE: live schema is single-line per signal (no event=signal/outcome split).")
    print("All pnl_usd/exit_reason are NULL -> signals are emitted but never closed in this log.")


def section_short_bots():
    print("\n===== §2 SHORT_BOTS_GUARD =====")
    audit = read_jsonl(STATE / "short_bots_audit.jsonl")
    print(f"Audit rows total: {len(audit)}")
    in_p = [r for r in audit if in_period(parse_ts(r.get("ts")))]
    print(f"In period: {len(in_p)}")
    for r in in_p:
        print(f"  {r.get('ts')} bot={r.get('bot_id')} action={r.get('action')} reason={r.get('reason')} trigger={r.get('trigger')}")
    try:
        with open(STATE / "short_bots_auto_pause.json") as f:
            cur = json.load(f)
        print(f"Current auto_pause state: {cur}")
    except Exception:
        pass
    try:
        with open(STATE / "cascade_alert_dedup.json") as f:
            dd = json.load(f)
        print(f"Cascade dedup snapshot (latest seen): {dd}")
    except Exception:
        pass


def section_grid_coord():
    print("\n===== §2b GRID_COORDINATOR FIRES =====")
    rows = read_jsonl(STATE / "grid_coordinator_fires.jsonl")
    in_p = [r for r in rows if in_period(parse_ts(r.get("ts")))]
    print(f"fires in period: {len(in_p)}")
    if not in_p and rows:
        print(f"all fires sample first: {rows[0]}")
    keys_used = Counter()
    for r in in_p:
        for k in r.keys():
            keys_used[k] += 1
    print(f"keys frequency: {keys_used.most_common(15)}")
    # try aggregate by 'action'/'kind'/'reason'/'label'/'event'/'trigger'
    for field in ("action", "kind", "reason", "label", "event", "trigger", "side", "dir", "direction"):
        c = Counter(r.get(field) for r in in_p if r.get(field) is not None)
        if c:
            print(f"  {field}: {dict(c)}")
    if in_p:
        sample = in_p[0]
        print(f"sample: {json.dumps(sample, indent=2)[:800]}")


def section_confluence():
    print("\n===== §3 CONFLUENCE =====")
    rows = read_jsonl(STATE / "confluence_fires.jsonl")
    in_p = [r for r in rows if in_period(parse_ts(r.get("ts")))]
    print(f"Total fires: {len(rows)}; in period: {len(in_p)}")
    for r in in_p:
        srcs = [s.get("label") for s in r.get("sources", [])]
        print(f"  {r.get('ts')} dir={r.get('direction')} count={r.get('count')} sources={srcs} price={r.get('last_price')}")


def section_play_journal():
    print("\n===== §3b PLAY_JOURNAL =====")
    rows = read_jsonl(STATE / "play_journal.jsonl")
    in_p = [r for r in rows if in_period(parse_ts(r.get("ts_fire")))]
    print(f"play_journal fires in period: {len(in_p)}")
    by_label = defaultdict(lambda: {"n": 0, "tp1": 0, "tp2": 0, "stop": 0, "pending": 0, "resolved": 0})
    for r in in_p:
        lbl = r.get("label") or "?"
        d = by_label[lbl]
        d["n"] += 1
        if r.get("outcome_status") == "pending":
            d["pending"] += 1
        else:
            d["resolved"] += 1
        if r.get("hit_tp1"):
            d["tp1"] += 1
        if r.get("hit_tp2"):
            d["tp2"] += 1
        if r.get("hit_stop"):
            d["stop"] += 1
    for lbl, d in sorted(by_label.items(), key=lambda x: -x[1]["n"]):
        tot_resolved = d["resolved"]
        wr = (d["tp1"] / tot_resolved * 100) if tot_resolved else None
        if wr is not None:
            print(f"  {lbl}: n={d['n']} resolved={tot_resolved} TP1={d['tp1']} TP2={d['tp2']} STOP={d['stop']} pending={d['pending']} WR(TP1)={wr:.1f}%")
        else:
            print(f"  {lbl}: n={d['n']} resolved=0 pending={d['pending']}")


def section_paper():
    print("\n===== §4 PAPER TRADES =====")
    paper = read_jsonl(STATE / "paper_trades.jsonl")
    in_p = [r for r in paper if in_period(parse_ts(r.get("ts")))]
    print(f"paper_trades total={len(paper)} in period={len(in_p)}")
    setup_types = Counter(r.get("setup_type", "?") for r in in_p)
    actions = Counter(r.get("action", "?") for r in in_p)
    print(f"Setup types: {dict(setup_types)}")
    print(f"Actions: {dict(actions)}")
    lmd = [r for r in in_p if "multi_div" in (r.get("setup_type") or "")]
    print(f"any *multi_div* rows: {len(lmd)}")

    trades = defaultdict(list)
    for r in in_p:
        tid = r.get("trade_id")
        if tid:
            trades[tid].append(r)

    closed_by_setup = defaultdict(lambda: {"opens": 0, "tp1": 0, "tp2": 0, "sl": 0, "time_stop": 0, "expire": 0, "other_close": 0, "pnl": 0.0})
    for tid, evs in trades.items():
        evs.sort(key=lambda r: r.get("ts", ""))
        opens = [e for e in evs if e.get("action") == "OPEN"]
        if not opens:
            continue
        st = opens[0].get("setup_type", "?")
        closed_by_setup[st]["opens"] += 1
        for c in evs:
            a = c.get("action")
            pnl = c.get("realized_pnl_usd") or 0
            if a == "TP1":
                closed_by_setup[st]["tp1"] += 1
                closed_by_setup[st]["pnl"] += pnl
            elif a == "TP2":
                closed_by_setup[st]["tp2"] += 1
                closed_by_setup[st]["pnl"] += pnl
            elif a == "SL":
                closed_by_setup[st]["sl"] += 1
                closed_by_setup[st]["pnl"] += pnl
            elif a == "TIME_STOP":
                closed_by_setup[st]["time_stop"] += 1
                closed_by_setup[st]["pnl"] += pnl
            elif a == "EXPIRE":
                closed_by_setup[st]["expire"] += 1
                closed_by_setup[st]["pnl"] += pnl
            elif a in ("CLOSE", "EXIT"):
                closed_by_setup[st]["other_close"] += 1
                closed_by_setup[st]["pnl"] += pnl

    print("\nPer setup_type:")
    for st, d in sorted(closed_by_setup.items(), key=lambda x: -x[1]["pnl"]):
        wins = d["tp1"] + d["tp2"]
        losses = d["sl"] + d["time_stop"] + d["expire"]
        tot = wins + losses
        wr = (wins / tot * 100) if tot else None
        wr_s = f"{wr:.1f}%" if wr is not None else "n/a"
        print(f"  {st}: opens={d['opens']} TP1={d['tp1']} TP2={d['tp2']} SL={d['sl']} TIME={d['time_stop']} EXP={d['expire']} OTHER={d['other_close']} WR={wr_s} pnl=${d['pnl']:.2f}")

    p15 = read_jsonl(STATE / "p15_paper_trades.jsonl")
    in_p15 = [r for r in p15 if in_period(parse_ts(r.get("ts")))]
    print(f"\np15_paper_trades in period: {len(in_p15)}")
    actions_p15 = Counter(r.get("action") for r in in_p15)
    print(f"p15 actions: {dict(actions_p15)}")
    p15_pnl_total = sum(r.get("realized_pnl_usd", 0) or 0 for r in in_p15)
    p15_pnl_close = sum(r.get("realized_pnl_usd", 0) or 0 for r in in_p15 if r.get("action") == "CLOSE")
    p15_pnl_harv = sum(r.get("realized_pnl_usd", 0) or 0 for r in in_p15 if r.get("action") == "HARVEST")
    print(f"p15 pnl total ${p15_pnl_total:.2f} (CLOSE=${p15_pnl_close:.2f}, HARVEST=${p15_pnl_harv:.2f})")
    # by side
    p15_by_side = defaultdict(lambda: {"opens": 0, "close": 0, "harvest": 0, "pnl": 0.0})
    for r in in_p15:
        side = r.get("side", "?")
        a = r.get("action")
        if a == "OPEN":
            p15_by_side[side]["opens"] += 1
        elif a == "CLOSE":
            p15_by_side[side]["close"] += 1
            p15_by_side[side]["pnl"] += r.get("realized_pnl_usd", 0) or 0
        elif a == "HARVEST":
            p15_by_side[side]["harvest"] += 1
            p15_by_side[side]["pnl"] += r.get("realized_pnl_usd", 0) or 0
    for side, d in p15_by_side.items():
        print(f"  p15 {side}: opens={d['opens']} close={d['close']} harvest={d['harvest']} pnl=${d['pnl']:.2f}")


def section_margin():
    print("\n===== §5 MARGIN TRAJECTORY =====")
    rows = read_jsonl(STATE / "margin_automated.jsonl")
    in_p = []
    artifacts = 0
    for r in rows:
        t = parse_ts(r.get("ts"))
        if not in_period(t):
            continue
        # filter API hiccups: zero/very-low samples that contradict surrounding data
        if (r.get("btc_mark_price") or 0) < 1000 or (r.get("margin_balance_usd") or 0) < 10000:
            artifacts += 1
            continue
        r["_ts"] = t
        in_p.append(r)
    print(f"Filtered {artifacts} API-hiccup samples (mark=0 or balance<$10k)")
    print(f"Total margin samples: {len(rows)}; in period: {len(in_p)}")
    if not in_p:
        return
    eq_start = in_p[0]["margin_balance_usd"]
    eq_end = in_p[-1]["margin_balance_usd"]
    eq_min = min(r["margin_balance_usd"] for r in in_p)
    eq_max = max(r["margin_balance_usd"] for r in in_p)
    wallet_start = in_p[0]["wallet_balance_usd"]
    wallet_end = in_p[-1]["wallet_balance_usd"]
    coef_min = min(r.get("coefficient", 1) or 1 for r in in_p)
    coef_max = max(r.get("coefficient", 1) or 1 for r in in_p)
    dist_min = min(r.get("distance_to_liquidation_pct", 100) or 100 for r in in_p)
    dist_max = max(r.get("distance_to_liquidation_pct", 0) or 0 for r in in_p)
    btc_start = in_p[0].get("btc_mark_price")
    btc_end = in_p[-1].get("btc_mark_price")
    peak = -1e18
    max_dd = 0
    for r in in_p:
        e = r["margin_balance_usd"]
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd
    # daily summary
    by_day = defaultdict(list)
    for r in in_p:
        d = r["_ts"].strftime("%Y-%m-%d")
        by_day[d].append(r["margin_balance_usd"])
    print(f"Period: {in_p[0]['ts']} → {in_p[-1]['ts']}")
    print(f"Margin balance: ${eq_start:.2f} → ${eq_end:.2f} delta=${eq_end-eq_start:+.2f} ({(eq_end-eq_start)/eq_start*100:+.2f}%)")
    print(f"Wallet balance: ${wallet_start:.2f} → ${wallet_end:.2f} delta=${wallet_end-wallet_start:+.2f}")
    print(f"Margin min=${eq_min:.2f} max=${eq_max:.2f} max_dd_from_peak={max_dd:.2f}%")
    print(f"Coefficient: {coef_min:.4f} - {coef_max:.4f}")
    print(f"Distance to liquidation: {dist_min:.2f}% - {dist_max:.2f}%")
    print(f"BTC mark: {btc_start} → {btc_end} ({(btc_end-btc_start)/btc_start*100:+.2f}%)")
    print("\nDaily margin (last sample of day):")
    last_per_day = {}
    for r in in_p:
        d = r["_ts"].strftime("%Y-%m-%d")
        last_per_day[d] = r["margin_balance_usd"]
    prev = None
    for d in sorted(last_per_day):
        v = last_per_day[d]
        delta = (v - prev) if prev is not None else 0
        print(f"  {d}: ${v:.2f}  Δ${delta:+.2f}")
        prev = v


def section_regime():
    print("\n===== §6 REGIME =====")
    rows = read_jsonl(STATE / "regime_shadow.jsonl")
    in_p = [r for r in rows if in_period(parse_ts(r.get("ts")))]
    print(f"regime_shadow in period: {len(in_p)}")
    label_count = Counter(r.get("verdict_a_label") for r in in_p)
    verdict_b = Counter(r.get("verdict_b") for r in in_p)
    agree = Counter(r.get("agree") for r in in_p)
    modifiers = Counter()
    for r in in_p:
        for m in (r.get("verdict_a_modifiers") or []):
            modifiers[m] += 1
    print(f"verdict_a labels: {dict(label_count)}")
    print(f"verdict_b labels: {dict(verdict_b)}")
    print(f"agree: {dict(agree)}")
    print(f"top modifiers: {modifiers.most_common(8)}")


def main():
    print(f"Period: {PERIOD_START.isoformat()} → {PERIOD_END.isoformat()}")
    section_range_hunter()
    section_short_bots()
    section_grid_coord()
    section_confluence()
    section_play_journal()
    section_paper()
    section_margin()
    section_regime()


if __name__ == "__main__":
    main()
