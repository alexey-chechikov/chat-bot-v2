"""При каком состоянии рынка разумно разрешить мелким сеткам доп. ордера сверх потолка (оператор 22.10: «при каком
сетапе логично было бы добавить количество ордеров, чтобы сетки начали работу»).

ПРАВИЛА ДО ПРОГОНА (не менять после):
- Механика — как exhaust_stop.py / drop_stop.py: longflat (лонг выше SMA100, смена режима — закрытие по рынку), мейкер
  0.016%, тейкер 0.048% + 0.02%, path4, фандинг Binance; BTC 1m Binance spot (копия frozen).
- Сетки — живые B34 0.1/0.34 ($3 000), B49 0.1/0.49 ($3 000), B89 0.1/0.89 ($2 000), ордер 0.0012.
- Варианты потолка: «база» — как сейчас; «всегда ×2»; условные — сетка на потолке (следующий вход не помещается в базу)
  И условие → потолок ×2, пока себестоимость лотов снова не станет ниже базы (тогда расширение снимается):
    stab   — закрытие минуты ≥ минимум low за 4 ч × 1.005 (первый откат от дна);
    bounce — закрытие ≥ минимум low с момента упора в потолок × 1.01;
    nofall — цена не ниже максимума 12 ч более чем на 3.5% (не в состоянии «падение ≥3.5%», где замерено продолжение);
    deep   — цена ≥2% ниже средней лотов И не «падение ≥3.5%».
- Отчёт: итог (закрыто − комиссии − фандинг + мешок), половины, худшая просадка, итог/просадка, максимум себестоимости
  лотов (сколько денег держала сетка), сумма по трём сеткам. Условный вариант «работает», только если лучше базы в обеих
  половинах И итог/просадка не хуже «всегда ×2» и базы.
Запуск: cap_extend.py --src=<копия frozen BTC>
"""
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

SNAP = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--src=")),
            "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")
sys.argv = [sys.argv[0], "BTCUSDT", f"--src={SNAP}", "--max-lots=100000"]
sys.path.insert(0, "/Users/alexeychechikov/code/bot7/research/weex")
import regime_grid as rg  # noqa: E402
import fast_grid as fg  # noqa: E402

MAKER, TAKER, SLIP = rg.MAKER, rg.TAKER, rg.SLIP
GRIDS = {"B34": (0.1, 0.34, 0.0012, 3000.0), "B49": (0.1, 0.49, 0.0012, 3000.0), "B89": (0.1, 0.89, 0.0012, 2000.0)}
MODES = ("база", "всегда ×2", "stab", "bounce", "nofall", "deep")


def run(args):
    gname, mode = args
    step, tgt, qty, base = GRIDS[gname]
    ts, o, h, l, c, reg = DATA[:6]
    bound = np.r_[False, reg[1:] != reg[:-1]].tolist()
    o, c, reg = o.tolist(), c.tolist(), reg.tolist()
    low4, high12 = EXTRA
    lw = l.tolist()
    pts, F = PTS, FUND
    g, t = step / 100, tgt / 100
    lots: list[list[float]] = []
    Q = QE = real = fee = fund = 0.0
    ref = None
    n = len(ts)
    mid_i = n // 2
    eq_mid = None
    peak = dd = 0.0
    ext = mode == "всегда ×2"
    capped_low = None
    max_cost = 0.0
    ext_on = 0
    prev = None
    for i in range(n):
        if i == mid_i:
            eq_mid = real - fee - fund + (Q * c[i - 1] - QE)
        if i in F:
            fund += Q * o[i] * F[i]
        if prev is not None and bound[i]:
            if prev and lots:
                px = o[i] * (1 - SLIP)
                real += Q * px - QE
                fee += Q * px * TAKER
                lots, Q, QE, ref = [], 0.0, 0.0, None
            capped_low = None
            if mode != "всегда ×2":
                ext = False
        prev = bool(reg[i])
        act = bool(reg[i])
        cap = base * 2 if ext else base
        for p in pts[i]:
            while lots and p >= lots[-1][1]:
                e, tp = lots.pop()
                real += qty * (tp - e)
                fee += qty * tp * MAKER
                Q -= qty
                QE -= qty * e
            if not lots:
                Q = QE = 0.0
            if not act:
                continue
            if lots:
                ref = lots[-1][0]
            elif ref is None:
                ref = p
            else:
                ref = max(ref, p)
            lvl = ref * (1 - g)
            if p <= lvl:
                if max(QE, Q * p) + qty * lvl <= cap:
                    lots.append([lvl, lvl * (1 + t)])
                    fee += qty * lvl * MAKER
                    Q += qty
                    QE += qty * lvl
                elif not ext and capped_low is None:
                    capped_low = p                       # упёрлась в базовый потолок
        max_cost = max(max_cost, QE)
        # решения о расширении — по закрытию минуты, действуют со следующей
        if mode not in ("база", "всегда ×2"):
            if ext and QE + qty * c[i] <= base:
                ext, capped_low = False, None            # тейки вернули под базу — расширение снято
            elif not ext and capped_low is not None and act:
                capped_low = min(capped_low, lw[i])
                avg = QE / Q if Q > 0 else c[i]
                strong_fall = c[i] < high12[i] * (1 - 0.035)
                cond = {"stab": c[i] >= low4[i] * 1.005,
                        "bounce": c[i] >= capped_low * 1.01,
                        "nofall": not strong_fall,
                        "deep": c[i] <= avg * 0.98 and not strong_fall}[mode]
                if cond:
                    ext = True
                    ext_on += 1
            if capped_low is not None and QE + qty * c[i] <= base * 0.9 and not ext:
                capped_low = None                        # ушла от потолка — эпизод закончился
        eq = real - fee - fund + (Q * c[i] - QE)
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    eq = real - fee - fund + (Q * c[-1] - QE)
    return gname, mode, eq, eq_mid, dd, max_cost, ext_on


def init(data, pts, fund, extra):
    global DATA, PTS, FUND, EXTRA
    DATA, PTS, FUND, EXTRA = data, pts.tolist(), fund, extra


def main():
    data = rg.load()
    ts = data[0]
    pts = fg.path4(*data[1:5])
    fr = rg.pd.read_csv("/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_funding_full.csv")
    ft = fr["fundingTime"].to_numpy(np.int64) // 1000
    idx = np.searchsorted(ts, ft, side="right") - 1
    ok = (idx >= 0) & (ft < ts[-1] + 60)
    fund = {int(i): float(r) for i, r in zip(idx[ok], fr["fundingRate"].to_numpy(float)[ok])}
    low4 = rg.pd.Series(data[3]).rolling(240, min_periods=1).min().tolist()
    high12 = rg.pd.Series(data[2]).rolling(720, min_periods=1).max().tolist()
    print(f"окно {rg.pd.to_datetime(ts[0], unit='s').date()} … {rg.pd.to_datetime(ts[-1], unit='s')} UTC, срез "
          f"{rg.cut_label(ts)}", flush=True)
    jobs = [(gn, m) for gn in GRIDS for m in MODES]
    with ProcessPoolExecutor(max_workers=4, initializer=init, initargs=(data, pts, fund, (low4, high12))) as ex:
        res = {(r[0], r[1]): r for r in ex.map(run, jobs)}
    print(f"\n{'режим':<10} | {'сетка':<5} {'итог':>6} {'1-я':>6} {'2-я':>6} | {'просадка':>8} {'итог/пр':>7} | "
          f"{'макс. в лотах':>13} {'включений':>9}")
    for m in MODES:
        tot = [0.0, 0.0, 0.0]
        for gn in GRIDS:
            _, _, eq, mid, dd, mc, on = res[(gn, m)]
            tot = [tot[0] + eq, tot[1] + mid, tot[2] + dd]
            print(f"{m:<10} | {gn:<5} {eq:+6.0f} {mid:+6.0f} {eq - mid:+6.0f} | {dd:+8.0f} {eq / -dd if dd < 0 else 0:7.2f} | "
                  f"${mc:>12,.0f} {on:9d}")
        print(f"{m:<10} | всего {tot[0]:+6.0f} {tot[1]:+6.0f} {tot[0] - tot[1]:+6.0f} | (сумма просадок {tot[2]:+.0f})\n")


if __name__ == "__main__":
    main()
