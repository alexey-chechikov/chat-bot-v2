"""Усиление из внешних исследований — проверка на нашей истории BTC (оператор 12.11: «иди в мир, принеси усиление»).

1) Ансамбль по сдвигу свечи 4ч («rebalance timing luck», Newfound Research): та же стратегия четырьмя частями по 1/4
   базы, свечи 4ч от 00/01/02/03 UTC. Правила не меняются — меняется только, какие часы попадают в свечу.
2) Ансамбль окон Дончиана для 432 («Catching Crypto Trends», Zarattini–Pagani–Barbon, SFI 2025): окна 20/30/45/60
   свечей по 1/4 базы (остальные правила 432 те же).
Мерило — не только итог: просадка, итог без лучшей сделки, годы в плюсе, и чувствительность к источнику цен
(Binance spot против перпа Bybit) — ансамбль должен снижать удачу одной сделки. База $1000, издержки 0.068%/сторону.
Запуск: ensemble_check.py  (часы Binance spot и Bybit перп — публичный API, ~1 мин)"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.btc_signals import engine as en  # noqa: E402

_sp = importlib.util.spec_from_file_location("sx_lines", str(Path(__file__).resolve().parents[2] / "services" / "sigexec" / "lines.py"))
L = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(L)

H = 3600
BASE = 1000.0


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7-research/1.0"}), timeout=20).read())


def hours(src: str, start: int, end: int) -> dict:
    out, cur = {}, start * 1000
    while cur < end * 1000:
        if src == "spot":
            rows = get(f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&startTime={cur}&limit=1000")
            rows = [(int(r[0]), *map(float, r[1:5])) for r in rows]
        else:
            rows = get(f"https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=60&start={cur}&limit=1000")["result"]["list"]
            rows = [(int(r[0]), *map(float, r[1:5])) for r in rows]
        if not rows:
            break
        for r in rows:
            tc = r[0] // 1000 + H
            if tc <= end:
                out[tc] = r[1:]
        nxt = max(r[0] for r in rows) + H * 1000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.1)
    return out


def run_one(t, o, h, l, c, shift_h=0, ch=None):
    """Правила движка на свечах 4ч, сдвинутых на shift_h часов. → (сделки системы, сделки 432) с временами в настоящих часах."""
    ts = t - shift_h * H
    a, lay = L.build(ts, o, h, l, c, i0_t=int(ts[0]))
    old = en.CH432
    if ch:
        en.CH432 = ch
    try:
        ev, _ = en.simulate(a, lay)
        ev4, _, _ = en.simulate432(a)
    finally:
        en.CH432 = old
    f = lambda E: [(int(e["pos"]["entry_t"]) + shift_h * H, int(e["t"]) + shift_h * H, e["res"] * BASE / 100) for e in E if e["kind"] == "выход"]  # noqa: E731
    return f(ev), f(ev4)


def stats(trades, t0, t1, w=1.0):
    z = sorted([(a, b, r * w) for a, b, r in trades if t0 <= a < t1], key=lambda x: x[1])
    if not z:
        return None
    r = np.array([x[2] for x in z])
    c = np.cumsum(r)
    dd = float((c - np.maximum.accumulate(np.r_[0, c])[1:]).min())
    years = {}
    for a, _, x in z:
        y = datetime.fromtimestamp(a, timezone.utc).year
        years[y] = years.get(y, 0) + x
    srt = np.sort(r)[::-1]
    return {"n": len(z), "sum": float(c[-1]), "dd": dd, "no_best": float(c[-1] - srt[0]), "no_best3": float(c[-1] - srt[:3].sum()),
            "years_pos": f"{sum(v > 0 for v in years.values())}/{len(years)}"}


def fmt(s):
    return "нет сделок" if not s else (f"n {s['n']:3d}  итог {s['sum']:+6.0f}$  просадка {s['dd']:+5.0f}$  без лучшей {s['no_best']:+6.0f}$  "
                                        f"без 3 лучших {s['no_best3']:+6.0f}$  годы в плюсе {s['years_pos']}")


def main():
    now = int(time.time())
    end = now // H * H
    start = end - 30000 * H                       # 30 000 часов: 20 000 прогрева + ≈1.1 года… расширяем ниже
    start = end - 47000 * H                       # ≈5.4 года: окна 3 года и 2 года с прогревом ≥20 000 часов
    data = {}
    for src in ("spot", "perp"):
        d = hours(src, start, end)
        ks = sorted(d)
        data[src] = (np.array(ks, np.int64), *(np.array([d[k][i] for k in ks]) for i in range(4)))
        print(f"{src}: часов {len(ks)} с {datetime.fromtimestamp(ks[0], timezone.utc):%d.%m.%Y}, разрывов {int(np.sum(np.diff(ks) != H))}", flush=True)
    t_end = end
    wins = (("2 года", t_end - int(2 * 365.25 * 86400)), ("3 года", t_end - int(3 * 365.25 * 86400)))
    for src in ("spot", "perp"):
        t, o, h, l, c = data[src]
        single = run_one(t, o, h, l, c)
        shifts = [run_one(t, o, h, l, c, shift_h=k) for k in range(4)]
        chans = [run_one(t, o, h, l, c, ch=ch) for ch in (20, 30, 45, 60)]
        for lab, t0 in wins:
            print(f"\n=== {src}, {lab} ===")
            print(f"система, одна (00 UTC)           : {fmt(stats(single[0], t0, t_end))}")
            print(f"система, ансамбль 4 сдвигов ×1/4 : {fmt(stats([x for s in shifts for x in s[0]], t0, t_end, 0.25))}")
            for k in range(1, 4):
                print(f"   система, сдвиг {k} ч отдельно     : {fmt(stats(shifts[k][0], t0, t_end))}")
            print(f"432, одна (00 UTC, окно 30)      : {fmt(stats(single[1], t0, t_end))}")
            print(f"432, ансамбль 4 сдвигов ×1/4     : {fmt(stats([x for s in shifts for x in s[1]], t0, t_end, 0.25))}")
            for k in range(1, 4):
                print(f"   432, сдвиг {k} ч отдельно         : {fmt(stats(shifts[k][1], t0, t_end))}")
            print(f"432, ансамбль окон 20/30/45/60   : {fmt(stats([x for s in chans for x in s[1]], t0, t_end, 0.25))}")
            for ch, s in zip((20, 45, 60), (chans[0], chans[2], chans[3])):
                print(f"   432, окно {ch} отдельно           : {fmt(stats(s[1], t0, t_end))}")
            both = [x for s in shifts for x in s[1]] + [x for s in chans for x in s[1]]
            print(f"432, сдвиги + окна (8 частей)    : {fmt(stats(both, t0, t_end, 0.125))}")


if __name__ == "__main__":
    main()
