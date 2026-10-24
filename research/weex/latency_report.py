"""Отчёт задержек сеток WEEX (21.10, давно открытый п.3 передачи): исполнение → тейк → новый вход. Только чтение.

Источник — биржа, не журнал: история ордеров (/capi/v3/order/history: clientOrderId, time = создание) и сделки
(/capi/v3/userTrades: time исполнения). Свои ордера — clientOrderId b7g + знак сетки + сторона + вид (e вход, t тейк).
Знаки: B — BTC, E — ETH, X — золото (холостое), 3/4/8 — B34/B49/B89, 5/6 — SB/SE.

Задержки по каждой сетке:
  вход исполнен → тейк этого лота выставлен (первый t-ордер сетки после полного исполнения входа);
  вход исполнен → следующий вход выставлен (первый e-ордер сетки после исполнения);
  тейк исполнен → вход переставлен (первый e-ордер сетки после исполнения тейка).
Считается «полное исполнение» = время последней сделки ордера. Пары дальше 15 мин не считаются (сетка стояла
по своей причине: потолок, пауза). Запросы к бирже — не чаще ~1 в секунду (тот же ключ, что у живых сеток).

Цена задержки: по записи сделок WEEX (state/weex_book/<SYM>_<день>_trades.csv, метки в мс) — доходила ли цена до
цены тейка между исполнением входа и постановкой тейка (тогда тейк этого лота упущен на этом движении).
Запуск: latency_report.py [дней=7]
"""
from __future__ import annotations

import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.weex_api.client import WeexClient  # noqa: E402

DAYS = float(sys.argv[1]) if len(sys.argv) > 1 else 7.0
SYMBOLS = ("BTCUSDT", "ETHUSDT")
NAMES = {"B": "BTC 0.6/1.4", "E": "ETH 0.6/1.4", "3": "B34", "4": "B49", "8": "B89", "5": "SB", "6": "SE", "X": "XAU"}
MAX_GAP = 15 * 60_000
PAUSE = 1.0


def fetch_orders(c, sym, t0, t1):
    """WEEX игнорирует page (проверено 15.10 и 21.10: страницы 0/1/5 одинаковы) — окно с 100 ордерами делится
    пополам, как в engine._history_window."""
    out = {}
    stack = [(a, min(a + 6 * 3_600_000, t1)) for a in range(t0, t1, 6 * 3_600_000)]
    while stack:
        a, b = stack.pop()
        r = c.order_history(sym, limit=100, page=0, start_ms=a, end_ms=b)
        time.sleep(PAUSE)
        if len(r) >= 100 and b - a > 1000:
            m = (a + b) // 2
            stack += [(a, m), (m + 1, b)]
            continue
        for x in r:
            out[str(x["orderId"])] = x
    return out


def fetch_trades(c, sym, t0, t1):
    """Сделки окнами; окно с 100 сделками (предел ответа) делится пополам."""
    out = {}
    stack = [(a, min(a + 86_400_000 - 1, t1)) for a in range(t0, t1, 86_400_000)]   # окно API ≤ 7 сут
    while stack:
        a, b = stack.pop()
        r = c.user_trades(sym, start_ms=a, end_ms=b) or []
        time.sleep(PAUSE)
        if len(r) >= 100 and b - a > 60_000:
            m = (a + b) // 2
            stack += [(a, m), (m + 1, b)]
            continue
        for x in r:
            out[str(x["id"])] = x
    return list(out.values())


def market_trades(sym, t0, t1):
    """Сделки рынка WEEX из записи стакана: (метки мс, цены), по возрастанию времени."""
    book = Path('/Users/alexeychechikov/code/bot7/state/weex_book')
    parts = []
    for day in pd.date_range(pd.to_datetime(t0, unit='ms').normalize(), pd.to_datetime(t1, unit='ms'), freq='D'):
        f = book / f"{sym}_{day:%Y%m%d}_trades.csv"
        if f.exists():
            parts.append(pd.read_csv(f, usecols=['T', 'p']))
    if not parts:
        return np.array([], dtype=np.int64), np.array([])
    d = pd.concat(parts).sort_values('T')
    return d['T'].to_numpy(np.int64), d['p'].to_numpy(float)


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def fmt(xs):
    if not xs:
        return "—"
    return (f"n {len(xs):4d} | медиана {statistics.median(xs):5.1f} с | 90% {q(xs, .9):5.1f} с | "
            f"макс {max(xs):6.1f} с")


def main():
    c = WeexClient()
    t1 = int(time.time() * 1000)
    t0 = t1 - int(DAYS * 86_400_000)
    lat = defaultdict(lambda: defaultdict(list))
    miss = defaultdict(lambda: {'n': 0, 'hit': 0})
    for sym in SYMBOLS:
        orders = fetch_orders(c, sym, t0 - 86_400_000, t1)      # тейки ставились и до окна
        trades = fetch_trades(c, sym, t0, t1)
        mT, mp = market_trades(sym, t0, t1)
        last_fill = defaultdict(int)
        for tr in trades:
            last_fill[str(tr["orderId"])] = max(last_fill[str(tr["orderId"])], int(tr["time"]))
        own = defaultdict(list)                                  # знак сетки → [(создан, вид, orderId)]
        for oid, o in orders.items():
            cid = str(o.get("clientOrderId") or "")
            if cid.startswith("b7g") and len(cid) > 5:
                own[cid[3]].append((int(o["time"]), cid[5], oid))
        for tag, lst in own.items():
            lst.sort()
            creates = {k: [t for t, kk, _ in lst if kk == k] for k in ("e", "t")}

            tp_list = [(t, oid) for t, kk, oid in lst if kk == 't']

            def first_after(kind, ts):
                for t in creates[kind]:
                    if t > ts:
                        return t - ts if t - ts <= MAX_GAP else None
                return None

            for t_create, kind, oid in lst:
                tf = last_fill.get(oid)
                if not tf or tf < t0 or orders[oid].get("status") != "FILLED":
                    continue
                if kind == "e":
                    nxt = next(((t, o2) for t, o2 in tp_list if t > tf), None)
                    if nxt and nxt[0] - tf <= MAX_GAP and len(mT):
                        a, b = np.searchsorted(mT, tf, 'left'), np.searchsorted(mT, nxt[0], 'right')
                        tp_px = float(orders[nxt[1]]['price'])
                        hit = b > a and float(mp[a:b].max()) >= tp_px
                        miss[tag]['n'] += 1
                        miss[tag]['hit'] += int(hit)
                    for key, k2 in (("вход → тейк", "t"), ("вход → след. вход", "e")):
                        d = first_after(k2, tf)
                        if d is not None:
                            lat[tag][key].append(d / 1000)
                elif kind == "t":
                    d = first_after("e", tf)
                    if d is not None:
                        lat[tag]["тейк → вход переставлен"].append(d / 1000)
        print(f"{sym}: ордеров в истории {len(orders)}, сделок {len(trades)}", file=sys.stderr)
    print(f"Окно {DAYS:g} сут до {time.strftime('%d.%m %H:%M', time.gmtime(t1 / 1000))} UTC; пары дальше 15 мин не считаются")
    for tag in sorted(lat, key=lambda k: "BE3485X6".find(k)):
        print(f"\n{NAMES.get(tag, tag)}")
        for key in ("вход → тейк", "вход → след. вход", "тейк → вход переставлен"):
            print(f"  {key:<25} {fmt(lat[tag][key])}")
        m = miss[tag]
        if m['n']:
            print(f"  цена дошла до тейка, пока его не было: {m['hit']} из {m['n']} входов ({m['hit'] / m['n'] * 100:.1f}%)")
    allx = [x for t in lat.values() for x in t["вход → тейк"]]
    print(f"\nВсе сетки, вход → тейк: {fmt(allx)}; дольше 30 с — {sum(x > 30 for x in allx)}")


if __name__ == "__main__":
    main()
