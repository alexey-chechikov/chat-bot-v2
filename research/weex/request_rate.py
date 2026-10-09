"""Сколько запросов к бирже шлёт сетка WEEX: прогон движка на минутных ценах BTC за N суток
(6 проходов в минуту, как при poll 10с) с живым конфигом, счётчик каждого вызова биржи."""
import json
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_grid import engine as eg  # noqa: E402

DAYS = 3


def klines(days: int) -> list[list]:
    end = int(time.time() * 1000)
    start = end - days * 86400_000
    out = []
    while start < end:
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1000&startTime={start}"
        chunk = json.loads(urllib.request.urlopen(url, timeout=20).read())
        if not chunk:
            break
        out.extend(chunk)
        start = chunk[-1][0] + 60_000
    return out


def path6(k) -> list[float]:
    o, h, l, c = (float(x) for x in k[1:5])
    a, b = (l, h) if c >= o else (h, l)          # сначала противоположный экстремум
    return [o, (o + a) / 2, a, b, (b + c) / 2, c]


class Px:
    mid = 0.0

    def __call__(self):
        return self.mid - 0.05, self.mid + 0.05


class Counted:
    def __init__(self, ex, cnt):
        self.ex, self.cnt = ex, cnt

    def __getattr__(self, name):
        f = getattr(self.ex, name)
        if not callable(f):
            return f

        def wrap(*a, **k):
            self.cnt[name] += 1
            return f(*a, **k)
        return wrap


def main():
    ks = klines(DAYS)
    cfg = {**eg.load_config(), "enabled": True, "dry_run": True}
    px = Px()
    px.mid = float(ks[0][1])
    cnt = Counter()
    ex = eg.DryExchange(px)
    clock = {"t": ks[0][0] / 1000}
    tmp = Path(tempfile.mkdtemp())

    def now():
        return clock["t"]

    g = eg.Grid(Counted(ex, cnt), cfg, state_path=tmp / "st.json", journal_path=tmp / "j.jsonl", now_fn=now)
    per_min = []
    for k in ks:
        before = sum(cnt.values())
        for p in path6(k):
            px.mid = p
            clock["t"] += 10
            g.tick()
        per_min.append(sum(cnt.values()) - before)
    total = sum(cnt.values())
    mins = len(ks)
    per_min.sort()
    print(f"цены {mins} мин ({mins / 1440:.1f} сут), BTC {float(ks[0][1]):,.0f} → {float(ks[-1][4]):,.0f}")
    print(f"запросов всего {total}: в среднем {total / mins:.1f}/мин = {total / mins / 6:.2f} за проход (10с)")
    print(f"минута: медиана {per_min[mins // 2]}, 99% {per_min[int(mins * 0.99)]}, максимум {per_min[-1]}")
    print("по типам:", dict(cnt.most_common()))
    s = g.st
    print("лотов LONG", len(s["LONG"]["lots"]), "SHORT", len(s["SHORT"]["lots"]),
          "входов", s["LONG"]["n_entries"] + s["SHORT"]["n_entries"], "тейков", s["LONG"]["n_tps"] + s["SHORT"]["n_tps"])


main()
