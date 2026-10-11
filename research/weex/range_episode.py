"""⚠️ ИТОГ 11.10: НЕТ на всех трёх. BTC 48 эпизодов −$79.87 (обе половины минус, 9/9 соседей минус, случайные часы
лучше: 47/50 не хуже), 32 из 48 — пробой коридора; ETH 63 эпизода −$95.88 (48/50 случайных не хуже); золото 8
эпизодов −$3.65. Стоп на пробое превращает мешок в убыток чаще, чем тейки успевают заработать; спокойные 48 ч не
предсказывают спокойные следующие 24 ч.

Сетка «по ситуации» — диапазонный эпизод (11.10; оператор: «нет задачи постоянной сетки, входить по
ситуации, понимать где отмена, ограничивать риск»; спецификация GPT docs/WEEX_GPT_STATE_ANSWERS_2026-10-11.md п.3).

ПРАВИЛА ЗАФИКСИРОВАНЫ ДО ПРОГОНА:
  ПРОВЕРКА — на закрытии каждого часа, когда эпизода нет. Окно 48 закрытых часов: L = min low, U = max high,
    P = (L+U)/2. Условие: ширина (U−L)/P от 3.6% до 6%; |close − open окна| ≤ 0.25·(U−L); close в центральных 40%.
    Включение — условие выполнено на ДВУХ проверках подряд (обе после конца прошлого эпизода).
  ЭПИЗОД — L/U/P фиксируются. Уровни: лонг P·(1−0.006)^j, шорт P·(1+0.006)^j, j=1..4, только внутри [L,U];
    одинаковый объём; лимитки (мейкер), исполнение — цена прошла уровень на 0.02%; на уровне один открытый лот,
    после тейка уровень можно взять снова. Тейк лота 1.4% от входа (мейкер).
  ОТМЕНА — цена вне [L,U] → всё закрыть по рынку (тейкер + 0.02% проскальзывания, по фактической цене — гэп
    учитывается); 24 ч → всё закрыть по рынку. Следующий эпизод — только после новых двух проверок.
  РАЗМЕР — капитал $3 000 (без реинвестирования); бюджет эпизода 0.5% = $15: q = 15 / Σ по всем уровням обеих
    сторон (вход − стоп L·0.994 / U·1.006 + комиссии + проскальзывание); и нотионал всех уровней ≤ 50% капитала.
  КОМИССИИ — мейкер 0.016%, тейкер 0.048%.
Контроль: те же эпизоды по числу, ширине и механике, но в СЛУЧАЙНЫЕ часы (50 сидов) — есть ли польза от выбора
момента. Разрез по времени: две половины окна. Соседи (BTC): шаг 0.5/0.6/0.8 × тейк 1.0/1.4/2.0.
Данные — минутки Binance research/weex/data (BTC/ETH спот, золото фьючерс), 11.12.2025–10.2026."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fast_grid as fg  # noqa: E402

C0, RISK, GROSS = 3000.0, 0.005, 0.5
MAKER, TAKER, SLIP, PEN = 0.00016, 0.00048, 0.0002, 0.0002
WMIN, WMAX, NLVL = 0.036, 0.06, 4


def checks(ts, o, h, l, c):
    """Индексы закрытий часов и условие диапазона на каждом (по 48 закрытым часам)."""
    d = pd.DataFrame({"o": o, "h": h, "l": l, "c": c}, index=pd.to_datetime(ts, unit="s", utc=True))
    hh = d.resample("1h").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna()
    L = hh["l"].rolling(48).min()
    U = hh["h"].rolling(48).max()
    O = hh["o"].shift(47)
    P = (L + U) / 2
    w = (U - L) / P
    pos = (hh["c"] - L) / (U - L)
    ok = (w >= WMIN) & (w <= WMAX) & ((hh["c"] - O).abs() <= 0.25 * (U - L)) & (pos >= 0.3) & (pos <= 0.7)
    # конец часа → индекс последней минуты часа в массиве минуток
    end_ts = (hh.index + pd.Timedelta("1h")).asi8 // 10**9 - 60
    idx = np.searchsorted(ts, end_ts)
    good = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == end_ts)
    return pd.DataFrame({"i": idx[good], "ok": ok.to_numpy()[good], "L": L.to_numpy()[good],
                         "U": U.to_numpy()[good], "w": w.to_numpy()[good]}).dropna()


def run_episode(pts, ts, c, i0, L, U, step, tp, eq_log):
    """Один эпизод с минуты i0+1. Возвращает (минута конца, итог $, причина, оборот)."""
    P = (L + U) / 2
    lv = [(1, P * (1 - step) ** j) for j in range(1, NLVL + 1) if P * (1 - step) ** j >= L] + \
         [(-1, P * (1 + step) ** j) for j in range(1, NLVL + 1) if P * (1 + step) ** j <= U]
    if not lv:
        return i0 + 1, 0.0, "нет уровней", 0.0
    loss = sum((e - L * 0.994) if d > 0 else (U * 1.006 - e) for d, e in lv) + \
        sum(e * MAKER + e * (TAKER + SLIP) for _, e in lv)
    q = min(C0 * RISK / loss, C0 * GROSS / sum(e for _, e in lv))
    lots = {}                                            # номер уровня → цена входа
    pnl, vol = 0.0, 0.0
    end = min(i0 + 1 + 1440, len(c))
    for i in range(i0 + 1, end):
        for p in pts[i]:
            if p < L or p > U:                           # отмена: пробой коридора — всё по рынку
                for k, e in lots.items():
                    d = lv[k][0]
                    px = p * (1 - d * SLIP)
                    pnl += d * q * (px - e) - q * px * TAKER
                    vol += q * px
                eq_log.append((ts[i], pnl))
                return i, pnl, "пробой", vol
            for k in list(lots):                         # тейки
                d, e = lv[k][0], lots[k]
                t = e * (1 + d * tp)
                if (d > 0 and p >= t * (1 + PEN)) or (d < 0 and p <= t * (1 - PEN)):
                    pnl += d * q * (t - e) - q * t * MAKER
                    vol += q * t
                    del lots[k]
            for k, (d, e) in enumerate(lv):              # входы
                if k not in lots and ((d > 0 and p <= e * (1 - PEN)) or (d < 0 and p >= e * (1 + PEN))):
                    lots[k] = e
                    pnl -= q * e * MAKER
                    vol += q * e
        eq_log.append((ts[i], pnl + sum(lv[k][0] * q * (c[i] - e) for k, e in lots.items())))
    i = end - 1                                          # 24 ч — всё по рынку
    for k, e in lots.items():
        d = lv[k][0]
        px = c[i] * (1 - d * SLIP)
        pnl += d * q * (px - e) - q * px * TAKER
        vol += q * px
    return i, pnl, "24 ч", vol


def simulate(data, step=0.006, tp=0.014, rng=None, widths=None):
    ts, o, h, l, c = data
    pts = fg.path4(o, h, l, c)
    ch = checks(ts, o, h, l, c)
    eps, eq_log = [], []
    free_from = 0
    prev_ok_i = None
    rows = ch.to_dict("records")
    if rng is None:
        for r in rows:
            if r["i"] <= free_from:
                prev_ok_i = None
                continue
            if r["ok"] and prev_ok_i is not None:
                e_i, pnl, why, vol = run_episode(pts, ts, c, int(r["i"]), r["L"], r["U"], step, tp, eq_log)
                eps.append({"t": ts[int(r["i"])], "pnl": pnl, "why": why, "vol": vol, "w": r["w"]})
                free_from, prev_ok_i = e_i, None
            else:
                prev_ok_i = r["i"] if r["ok"] else None
    else:                                                # контроль: случайные часы, ширины как у настоящих
        n = len(widths)
        cand = [r for r in rows]
        picks = sorted(rng.choice(len(cand), size=min(len(cand), n * 4), replace=False))
        k = 0
        for j in picks:
            if k >= n:
                break
            r = cand[j]
            if r["i"] <= free_from:
                continue
            P = c[int(r["i"])]
            w = widths[k]
            e_i, pnl, why, vol = run_episode(pts, ts, c, int(r["i"]), P * (1 - w / 2), P * (1 + w / 2), step, tp, eq_log)
            eps.append({"t": ts[int(r["i"])], "pnl": pnl, "why": why, "vol": vol, "w": w})
            free_from = e_i
            k += 1
    return pd.DataFrame(eps), eq_log


def report(sym, eps, eq_log, mid_ts):
    if eps.empty:
        print(f"{sym}: эпизодов нет")
        return
    eq = pd.Series([0.0] + [v for _, v in eq_log])
    # капитал: закрытые эпизоды + плавающий текущего (eq_log внутри эпизода — от его начала)
    cum, last_ep, path = 0.0, 0.0, [0.0]
    for t, v in eq_log:
        path.append(cum + v)
    closed = eps["pnl"].cumsum().tolist()
    h1 = eps[eps["t"] < mid_ts]["pnl"].sum()
    h2 = eps[eps["t"] >= mid_ts]["pnl"].sum()
    why = eps["why"].value_counts().to_dict()
    run = np.maximum.accumulate(np.r_[0.0, closed])
    dd = (np.r_[0.0, closed] - run).min()
    print(f"{sym}: эпизодов {len(eps)} ({why}), итог ${eps['pnl'].sum():+.2f}, 1-я половина ${h1:+.2f}, 2-я ${h2:+.2f}; "
          f"в плюсе {(eps['pnl'] > 0).mean():.0%}; средний ${eps['pnl'].mean():+.2f}, худший ${eps['pnl'].min():+.2f}; "
          f"просадка по эпизодам ${dd:+.2f}; оборот ${eps['vol'].sum():,.0f}")
    del eq, cum, last_ep, path


def main():
    syms = sys.argv[1:] or ["BTCUSDT", "ETHUSDT", "XAUUSDT"]
    for sym in syms:
        data = fg.load(sym)
        mid_ts = data[0][len(data[0]) // 2]
        eps, log = simulate(data)
        report(sym, eps, log, mid_ts)
        if eps.empty:
            continue
        real = eps["pnl"].sum()
        ctl = []
        for seed in range(50):
            e2, _ = simulate(data, rng=np.random.default_rng(seed), widths=eps["w"].tolist())
            ctl.append(e2["pnl"].sum() if not e2.empty else 0.0)
        ctl = np.array(ctl)
        print(f"   контроль (случайные часы, 50 сидов): медиана ${np.median(ctl):+.2f}, 10–90% "
              f"${np.quantile(ctl, 0.1):+.2f}…${np.quantile(ctl, 0.9):+.2f}; не хуже настоящего {int((ctl >= real).sum())}/50")
        if sym == "BTCUSDT":
            print("   соседи BTC (шаг × тейк → итог $, эпизодов):")
            for st in (0.005, 0.006, 0.008):
                cells = []
                for tp in (0.010, 0.014, 0.020):
                    e3, _ = simulate(data, step=st, tp=tp)
                    cells.append(f"тейк {tp * 100:.1f}%: ${e3['pnl'].sum():+.2f}")
                print(f"     шаг {st * 100:.1f}%: " + "; ".join(cells))


if __name__ == "__main__":
    main()
