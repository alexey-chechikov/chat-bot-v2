"""Проверка «AI сигналов о прибыли» TradeGPT (11.10) по минуткам Bybit linear.

Сигнал открытия: монета, сторона, цена входа, плечо. Сигнал о прибыли: «доходность +X%» и текущая цена.
Гипотеза: X = лучший ход цены в нашу сторону от цены входа × плечо (без комиссий, без учёта того, что цена до
этого шла против), а по сделкам, которые не дошли до плюса, сообщений нет. Считаем по каждому сигналу:
лучший ход (MFE) и худший ход ДО него (MAE), ход через 1 и 4 часа и сейчас — всё без плеча, в % цены.
Время в Telegram у оператора — UTC+2 (STX: в TG 00:01:04, вставлен в чат 22:01:56 UTC)."""
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

TG = timezone(timedelta(hours=2))
SIGNALS = [  # монета, сторона (+1 лонг, −1 шорт), вход, плечо, время сигнала
    ("AAVEUSDT", -1, 171.6, 5, datetime(2026, 10, 10, 16, 19, tzinfo=timezone.utc)),   # время вставки в чат
    ("ARPAUSDT", -1, 0.011981, 2, datetime(2026, 10, 10, 16, 46, tzinfo=timezone.utc)),  # время вставки в чат
    ("STXUSDT", -1, 0.3998, 5, datetime(2026, 10, 11, 0, 1, tzinfo=TG)),
    ("LINKUSDT", -1, 13.014, 2, datetime(2026, 10, 11, 1, 1, tzinfo=TG)),
    ("APRUSDT", 1, 0.0747, 4, datetime(2026, 10, 11, 2, 0, tzinfo=TG)),
    ("NILUSDT", 1, 0.08996, 5, datetime(2026, 10, 11, 5, 1, tzinfo=TG)),
    ("STRKUSDT", -1, 0.10867, 3, datetime(2026, 10, 11, 10, 0, tzinfo=TG)),
]
CLAIMS = {"AAVEUSDT": (10.0, 168.16), "ARPAUSDT": (5.5, 0.011652), "APRUSDT": (8.04, 0.0762),
          "NILUSDT": (10.75, 0.09189), "STXUSDT": (10.5, 0.3914)}


def klines(sym, start: datetime):
    out, a = [], int(start.timestamp()) // 60 * 60_000
    end = int(time.time() * 1000)
    while a < end:
        u = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=1&start={a}&limit=1000"
        rows = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "bot7"}),
                                                 timeout=20).read())["result"]["list"]
        if not rows:
            break
        rows = sorted((int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows)
        out += [r for r in rows if not out or r[0] > out[-1][0]]
        if rows[-1][0] <= a:
            break
        a = rows[-1][0] + 60_000
        time.sleep(0.1)
    return out


def main():
    print(f"{'монета':<9} {'стор':>4} {'плечо':>5} | {'лучший ход':>10} {'через':>6} {'хуже до него':>12} | "
          f"{'1ч':>6} {'4ч':>6} {'сейчас':>7} | заявлено")
    for sym, d, entry, lev, ts in SIGNALS:
        k = klines(sym, ts)
        if not k:
            print(sym, "нет данных")
            continue
        fav = [(d * ((r[3] if d > 0 else r[4 - 1]) / entry - 1) * 100) for r in k]   # заглушка, ниже точнее
        best, best_i, worst_before, worst_i = -1e9, 0, 0.0, 0
        run_worst = 0.0
        for i, (_, o, h, l, c) in enumerate(k):
            good = d * ((h if d > 0 else l) / entry - 1) * 100
            bad = d * ((l if d > 0 else h) / entry - 1) * 100
            run_worst = min(run_worst, bad)
            if good > best:
                best, best_i, worst_before = good, i, run_worst
        at = lambda m: d * (k[min(m, len(k) - 1)][4] / entry - 1) * 100 if len(k) > m else float("nan")  # noqa: E731
        now = d * (k[-1][4] / entry - 1) * 100
        cl = CLAIMS.get(sym)
        claim = ""
        if cl:
            implied = d * (cl[1] / entry - 1) * 100
            claim = f"+{cl[0]}% = ход {implied:+.2f}% × плечо {lev} = {implied * lev:+.2f}%"
        del fav
        print(f"{sym:<9} {'L' if d > 0 else 'S':>4} {lev:>5} | {best:>+9.2f}% {best_i / 60:>5.1f}ч {worst_before:>+11.2f}% | "
              f"{at(60):>+5.2f}% {at(240):>+5.2f}% {now:>+6.2f}% | {claim}")
    print("\nход без плеча, от цены входа сигнала, без комиссии (тейкер ~0.11% за круг)")
    # правило «тейк +2% (момент сообщения о прибыли) / стоп −S%»: что из двух цена коснулась раньше
    print("\nТЕЙК +2% / СТОП — без плеча, после комиссии 0.11% за круг; открытые — по цене сейчас")
    data = {sym: (d, entry, klines(sym, ts)) for sym, d, entry, _, ts in SIGNALS}
    for stop in (2.0, 3.0, 5.0):
        res = []
        for sym, (d, entry, k) in data.items():
            out = None
            for _, o, h, l, c in k:
                bad = d * ((l if d > 0 else h) / entry - 1) * 100
                good = d * ((h if d > 0 else l) / entry - 1) * 100
                if bad <= -stop:                       # в одной минуте оба — считаем стоп (осторожно)
                    out = -stop
                    break
                if good >= 2.0:
                    out = 2.0
                    break
            if out is None:
                out = d * (k[-1][4] / entry - 1) * 100
            res.append((sym, out - 0.11))
        tot = sum(x for _, x in res)
        print(f"  стоп −{stop}%: " + ", ".join(f"{s[:-4]} {x:+.2f}" for s, x in res) +
              f" | итого {tot:+.2f}%, на сделку {tot / len(res):+.2f}%")


if __name__ == "__main__":
    main()
