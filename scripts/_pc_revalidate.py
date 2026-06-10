"""Ре-валидация pre-cascade inverted-SHORT эджа на фаерах ПОСЛЕ 2026-05-19.

Повторяет майскую методику (карточка: n=63, @24h 64% DOWN, mean −0.468%,
inverted SHORT net ~+0.32%): берём фаеры liq_pre_cascade_fires.jsonl, дедуп
по таймстампу события (long/short пара = один фаер), форвард-доходность
через 24ч по market_live/market_1h.csv, SHORT net = −fwd − fees (0.15% RT taker).
"""
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("/Users/alexeychechikov/code/bot7")
FEES_RT = 0.15  # % round-trip taker XBTUSDT linear

# 1h closes
bars: list[tuple[datetime, float]] = []
with (ROOT / "market_live" / "market_1h.csv").open() as fh:
    for row in csv.DictReader(fh):
        bars.append((datetime.fromisoformat(row["ts_utc"]), float(row["close"])))
bars.sort()


def close_at(ts: datetime) -> float | None:
    for bts, c in bars:
        if bts >= ts:
            return c
    return None


fires: dict[str, dict] = {}
with (ROOT / "state" / "liq_pre_cascade_fires.jsonl").open() as fh:
    for line in fh:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        sig = d.get("signal_id")
        # старые строки без signal_id — ключ по ts (long/short пара = один фаер)
        key = sig.rsplit("_", 1)[0] if sig else str(d.get("ts", ""))[:19]
        if not key or not d.get("ts"):
            continue
        fires.setdefault(key, d)

cut_lo = datetime.fromisoformat("2026-05-19T00:00:00+00:00")
now = datetime.now(tz=cut_lo.tzinfo)
cut_hi = now - timedelta(hours=24)

rets = []
for key, d in sorted(fires.items()):
    ts = datetime.fromisoformat(d["ts"])
    if not (cut_lo <= ts <= cut_hi):
        continue
    entry = float(d.get("entry") or 0)
    if not entry:
        continue
    c24 = close_at(ts + timedelta(hours=24))
    if c24 is None:
        continue
    rets.append((ts, (c24 / entry - 1) * 100.0))

# бейзлайн: безусловная 24ч-доходность каждого часа того же окна (regime-confound check)
base = []
for i, (bts, c) in enumerate(bars):
    if not (cut_lo <= bts <= cut_hi):
        continue
    c24 = close_at(bts + timedelta(hours=24))
    if c24 is not None:
        base.append((c24 / c - 1) * 100.0)

# кулдаун-дедуп: фаеры кластеризуются (десятки в день) — берём 1 фаер / 6ч
cooled = []
last_t = None
for ts, v in rets:
    if last_t is None or (ts - last_t) >= timedelta(hours=6):
        cooled.append((ts, v))
        last_t = ts

print(f"фаеров (дедуп, 19.05 → −24ч): {len(rets)}")
if rets:
    vals = [r for _, r in rets]
    down = sum(1 for v in vals if v < 0) / len(vals) * 100
    short_net = -mean(vals) - FEES_RT
    print(f"@24h DOWN: {down:.0f}%  ·  mean {mean(vals):+.3f}%  ·  median {median(vals):+.3f}%")
    print(f"inverted SHORT 24h-hold net (после {FEES_RT}% fees): {short_net:+.3f}%/trade")
    # последние 2 недели отдельно — куда едет эдж
    half = now - timedelta(days=14)
    recent = [v for t, v in rets if t >= half]
    old = [v for t, v in rets if t < half]
    for label, xs in (("19.05–27.05 (старые)", old), ("последние 14д", recent)):
        if xs:
            d_ = sum(1 for v in xs if v < 0) / len(xs) * 100
            print(f"  {label}: n={len(xs)} DOWN {d_:.0f}% mean {mean(xs):+.3f}% "
                  f"short_net {-mean(xs) - FEES_RT:+.3f}%")

if base:
    bd = sum(1 for v in base if v < 0) / len(base) * 100
    print(f"\nБЕЙЗЛАЙН (любой час того же окна, n={len(base)}): DOWN {bd:.0f}% "
          f"mean {mean(base):+.3f}% → «short всегда» net {-mean(base) - FEES_RT:+.3f}%")
if cooled:
    cv = [v for _, v in cooled]
    cd = sum(1 for v in cv if v < 0) / len(cv) * 100
    print(f"С КУЛДАУНОМ 6ч (реально исполнимо, n={len(cv)}): DOWN {cd:.0f}% "
          f"mean {mean(cv):+.3f}% → short net {-mean(cv) - FEES_RT:+.3f}%/trade")
