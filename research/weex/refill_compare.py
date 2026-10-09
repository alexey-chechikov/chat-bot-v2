"""Сетка WEEX: от чего считать следующий вход. Прогон движка на минутных ценах BTC (6 проходов/мин).
A (как сейчас): от последнего ИСПОЛНЕННОГО входа — после тейков сторона ждёт, пока цена дойдёт до
    уровня ниже самого нижнего входа, даже если те лоты уже закрыты.
B (дозаполнение): от последнего ОТКРЫТОГО лота — после тейка уровень снова доступен.
Учёт полный: закрыто − комиссии + мешок. Разрез по неделям."""
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_grid import engine as eg  # noqa: E402

DAYS = 28


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
    a, b = (l, h) if c >= o else (h, l)
    return [o, (o + a) / 2, a, b, (b + c) / 2, c]


class Px:
    mid = 0.0

    def __call__(self):
        return self.mid - 0.05, self.mid + 0.05


class Refill(eg.Grid):
    def _side(self, side, bid, ask, mid, open_ids, enabled):
        s = self.st[side]
        if s["lots"]:
            s["ref"] = max(s["lots"], key=lambda l: l["t"])["entry"]
        return super()._side(side, bid, ask, mid, open_ids, enabled)


def run(cls, ks, cfg):
    px = Px()
    px.mid = float(ks[0][1])
    ex = eg.DryExchange(px)
    clock = {"t": ks[0][0] / 1000}
    tmp = Path(tempfile.mkdtemp())
    g = cls(ex, cfg, state_path=tmp / "st.json", journal_path=tmp / "j.jsonl", now_fn=lambda: clock["t"])
    g.save = lambda: None                       # без записи файла на каждом шаге
    weeks, worst, idle, last_n, idle_run = [], 0.0, 0, 0, 0
    longest_idle = 0
    for i, k in enumerate(ks):
        for p in path6(k):
            px.mid = p
            clock["t"] += 10
            g.tick()
        mid = float(k[4])
        eq = g.bot_pnl(mid)
        worst = min(worst, g.unrealized(mid))
        n = sum(g.st[s]["n_entries"] + g.st[s]["n_tps"] for s in ("LONG", "SHORT"))
        idle_run = idle_run + 1 if n == last_n else 0
        longest_idle = max(longest_idle, idle_run)
        last_n = n
        if (i + 1) % (7 * 1440) == 0 or i == len(ks) - 1:
            weeks.append(eq)
    st = g.st
    closed = sum(st[s]["realized"] for s in ("LONG", "SHORT"))
    fees = sum(st[s]["fees"] for s in ("LONG", "SHORT"))
    turn = sum(st[s]["turnover"] for s in ("LONG", "SHORT"))
    tps = sum(st[s]["n_tps"] for s in ("LONG", "SHORT"))
    mid = float(ks[-1][4])
    return {"тейков": tps, "оборот": turn, "закрыто": closed, "комиссии": fees, "мешок": g.unrealized(mid),
            "итог": g.bot_pnl(mid), "худший мешок": worst, "простой ч": longest_idle / 60,
            "по неделям": [round(b - a, 2) for a, b in zip([0.0] + weeks[:-1], weeks)]}


def main():
    ks = klines(DAYS)
    cfg = {**eg.load_config(), "enabled": True, "dry_run": True}
    print(f"BTC {float(ks[0][1]):,.0f} → {float(ks[-1][4]):,.0f}, {len(ks) / 1440:.1f} сут; шаг {cfg['step_pct']}% "
          f"цель {cfg['target_pct']}% ордер {cfg['order_qty']} потолок ${cfg['max_notional_usd']:,.0f}/сторону")
    for name, cls in (("A как сейчас", eg.Grid), ("B дозаполнение", Refill)):
        r = run(cls, ks, cfg)
        print(f"{name}: тейков {r['тейков']}, оборот ${r['оборот']:,.0f}, закрыто ${r['закрыто']:+.2f}, "
              f"комиссии ${r['комиссии']:.2f}, мешок ${r['мешок']:+.2f}, ИТОГ ${r['итог']:+.2f}, "
              f"худший мешок ${r['худший мешок']:+.2f}, самый долгий простой {r['простой ч']:.1f} ч")
        print(f"   по неделям: {r['по неделям']}")


if __name__ == "__main__":
    main()
