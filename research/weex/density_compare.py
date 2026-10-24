"""21.10 вопрос оператора: что выгоднее — 4 сетки шага 0.1 с разными целями или «1 суперкороткая + 1 длинная»,
при РАВНОЙ ПЛОТНОСТИ (0.6 с ордером $600 против каждой 0.1 с ордером $100).

ПРАВИЛА ДО ПРОГОНА (не менять после):
- Механика — regime_grid.run, режим longflat (как живые сетки: лонг выше SMA100, при смене режима всё закрывается
  по рынку тейкер 0.048% + 0.02%), мейкер 0.016%, правило GinArea (шаг от крайнего открытого лота), путь минуты path4.
- Плотность: $1000 на 1% хода вниз у каждой сетки: шаг 0.6 — 0.0072 BTC (≈$600 при $83k), шаг 0.1 — 0.0012 BTC
  (≈$100). Объём в монете, соотношение ровно 6:1.
- Глубина: потолок позиции сетки в $ одинаковый ⇒ одинаковая глубина покрытия: $3 000 (≈3% хода, как живые B34/B49),
  $6 000 (6%), $12 000 (12%). Лимит лотов не мешает (100 000), держит только потолок $.
- Сетки: 0.1/0.34, 0.1/0.49, 0.1/0.89, 0.1/1.4 и 0.6/0.89, 0.6/1.4, 0.6/2.0 (соседи большой сетки).
- Портфели — РАВНЫЙ общий капитал (общая плотность $1000/1%, тот же общий потолок): среднее минутных кривых
  участников (механика линейна по объёму и потолку — сетка ×k = кривая ×k):
    P4  = 0.1/0.34 + 0.1/0.49 + 0.1/0.89 + 0.1/1.4 (по 1/4)
    P3  = 0.1/0.34 + 0.1/0.49 + 0.1/0.89 (живая тройка, по 1/3)
    P1+1 = 0.1/0.34 + 0.6/1.4 (по 1/2)
    S   = 0.6/1.4 одна
- Итог = закрыто − комиссии + мешок по закрытию последней минуты; половины — непрерывно (срез как regime_grid) и
  вторая с нуля (отдельный прогон с пустым учётом от минуты среза); просадка — по закрытиям минут совместной кривой.
  Фандинг — реальные ставки Binance BTCUSDT (каждые 8 ч, лонг платит Q·цена·ставка; файл кончается ~15.10).
Сверка: собственная быстрая петля (лоты — стек, учёт Q/QE) против regime_grid.run на отрезке — итог, срез, просадка
должны совпасть до центов, иначе отказ.
"""
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

# прогон по протоколу — на копии снимка: density_compare.py --src=<копия backtests/frozen/BTCUSDT_1m_2y.csv>
SNAP = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--src=")),
            "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")
sys.argv = [sys.argv[0], "BTCUSDT", f"--src={SNAP}", "--max-lots=100000"]
sys.path.insert(0, "/Users/alexeychechikov/code/bot7/research/weex")
import regime_grid as rg  # noqa: E402
import fast_grid as fg  # noqa: E402

MAKER, TAKER, SLIP = rg.MAKER, rg.TAKER, rg.SLIP
CAPS = (3000.0, 6000.0, 12000.0)
GRIDS = ((0.1, 0.34), (0.1, 0.49), (0.1, 0.89), (0.1, 1.4), (0.6, 0.89), (0.6, 1.4), (0.6, 2.0))
QTY = {0.1: 0.0012, 0.6: 0.0072}
PORTS = {"P4 четыре 0.1": [(0.1, 0.34), (0.1, 0.49), (0.1, 0.89), (0.1, 1.4)],
         "P3 живая тройка": [(0.1, 0.34), (0.1, 0.49), (0.1, 0.89)],
         "P1+1 0.1/0.34+0.6/1.4": [(0.1, 0.34), (0.6, 1.4)],
         "S одна 0.6/1.4": [(0.6, 1.4)]}


def curve(args):
    """Лонг по режиму (longflat) с минуты i0; кривая капитала по закрытию каждой минуты от i0, срез, взятия."""
    step, tgt, qty, cap, i0, fund_on = args
    ts, o, h, l, c, reg = DATA[:6]
    bound = np.r_[False, reg[1:] != reg[:-1]].tolist()
    o, c, reg = o.tolist(), c.tolist(), reg.tolist()
    pts = PTS
    g, t = step / 100, tgt / 100
    lots: list[list[float]] = []                 # [вход, тейк] — по убыванию входа (новый всегда ниже крайнего)
    Q = QE = real = fee = 0.0
    ref = None
    n = len(ts) - i0
    eq_arr = np.empty(n, dtype=np.float64)
    mid_i = len(ts) // 2
    eq_mid = None
    takes = flips = 0
    fund = 0.0
    F = FUND if fund_on else {}
    flip_pnl = 0.0
    prev = None
    for k in range(n):
        i = i0 + k
        if i == mid_i and i0 == 0:
            pc = c[i - 1]
            eq_mid = real - fee - fund + (Q * pc - QE)
        if i in F:                                  # фандинг на начале минуты: лонг платит Q·цена·ставка
            fund += Q * o[i] * F[i]
        act = bool(reg[i])
        if prev is not None and bound[i]:
            flips += 1
            if prev:
                px = o[i] * (1 - SLIP)
                pnl = Q * px - QE
                real += pnl
                flip_pnl += pnl
                fee += Q * px * TAKER
                lots, Q, QE, ref = [], 0.0, 0.0, None
        prev = act
        for p in pts[i]:
            while lots and p >= lots[-1][1]:
                e, tp = lots.pop()
                real += qty * (tp - e)
                fee += qty * tp * MAKER
                Q -= qty
                QE -= qty * e
                takes += 1
            if not lots:
                Q = QE = 0.0                      # без накопления ошибки округления
            if not act:
                continue
            if lots:
                ref = lots[-1][0]
            elif ref is None:
                ref = p
            else:
                ref = max(ref, p)
            lvl = ref * (1 - g)
            if p <= lvl and max(QE, Q * p) + qty * lvl <= cap:
                lots.append([lvl, lvl * (1 + t)])
                fee += qty * lvl * MAKER
                Q += qty
                QE += qty * lvl
        eq_arr[k] = real - fee - fund + (Q * c[i] - QE)
    return step, tgt, cap, i0, eq_arr.astype(np.float32), eq_mid, takes, flips, flip_pnl, fee, fund


def init(data, pts, fund=None):
    global DATA, PTS, FUND
    DATA, PTS, FUND = data, pts.tolist(), fund or {}
    rg.DATA = data


def dd_of(x):
    return float((x - np.maximum.accumulate(np.maximum(x, 0.0))).min())


def check(data, pts):
    """Сверка с regime_grid.run на первых 200 000 минутах (своя петля обязана совпасть)."""
    sl = tuple(a[:200_000] for a in data[:6])
    init(sl, pts[:200_000])
    for step, tgt, cap in ((0.1, 0.34, 3000.0), (0.6, 1.4, 6000.0), (0.1, 0.89, 12000.0)):
        r = rg.run((f"{step}/{tgt}", "longflat", 0, step, tgt, QTY[step], cap))
        m = curve((step, tgt, QTY[step], cap, 0, False))
        mine_eq, mine_mid = float(m[4][-1]), m[5]
        mine_dd = dd_of(m[4].astype(np.float64))
        ok = abs(mine_eq - r[5]) < 0.05 and abs(mine_mid - r[6]) < 0.05 and abs(mine_dd - r[7]) < 0.05
        print(f"сверка {step}/{tgt} ${cap:.0f}: regime_grid итог {r[5]:+.2f} срез {r[6]:+.2f} просадка {r[7]:+.2f} | "
              f"своя {mine_eq:+.2f} {mine_mid:+.2f} {mine_dd:+.2f} → {'совпало' if ok else 'НЕ СОВПАЛО'}")
        if not ok:
            sys.exit("своя петля расходится с regime_grid — отказ")


def main():
    data = rg.load()
    ts = data[0]
    pts = fg.path4(*data[1:5])
    check(data, pts)
    fr = rg.pd.read_csv('/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_funding_full.csv')
    ft = (fr['fundingTime'].to_numpy(np.int64) // 1000)
    idx = np.searchsorted(ts, ft, side='right') - 1
    ok = (idx >= 0) & (ft < ts[-1] + 60)
    fund = {int(i): float(r) for i, r in zip(idx[ok], fr['fundingRate'].to_numpy(float)[ok])}
    print(f"фандинг Binance BTCUSDT: расчётов в окне {len(fund)}, последний "
          f"{rg.pd.to_datetime(int(ft[ok][-1]), unit='s')} UTC, средняя ставка {np.mean(list(fund.values())) * 100:.4f}%")
    init(data, pts, fund)
    mid = len(ts) // 2
    print(f"окно {rg.pd.to_datetime(ts[0], unit='s').date()} … {rg.pd.to_datetime(ts[-1], unit='s').date()}, "
          f"выше SMA100 {data[5].mean():.0%}, срез {rg.cut_label(ts)}", flush=True)
    jobs = [(s, t, QTY[s], cap, i0, True) for cap in CAPS for s, t in GRIDS for i0 in (0, mid)]
    with ProcessPoolExecutor(max_workers=3, initializer=init, initargs=(data, pts, fund)) as ex:
        res = list(ex.map(curve, jobs))
    R = {(r[0], r[1], r[2], r[3]): r for r in res}
    for cap in CAPS:
        print(f"\n=== потолок ${cap:,.0f} на сетку (глубина ≈{cap / 1000:.0f}% хода), плотность $1000/1% ===")
        print(f"{'сетка':>9} | {'итог':>7} {'1-я':>7} {'2-я неп':>7} {'2-я с 0':>7} | {'просадка':>8} {'итог/пр':>7} | "
              f"{'тейков':>6} {'закр.режим':>10} {'комиссии':>8} {'фандинг':>7}")
        for s, t in GRIDS:
            full, half = R[(s, t, cap, 0)], R[(s, t, cap, mid)]
            x = full[4].astype(np.float64)
            eq, m, dd = x[-1], full[5], dd_of(x)
            print(f"{s:g}/{t:g}".rjust(9) + f" | {eq:+7.0f} {m:+7.0f} {eq - m:+7.0f} {float(half[4][-1]):+7.0f} | "
                  f"{dd:+8.0f} {eq / -dd if dd < 0 else float('inf'):7.2f} | {full[6]:6d} {full[8]:+10.0f} {full[9]:8.0f} {full[10]:7.0f}")
        print(f"{'портфель (равный капитал)':>26} | {'итог':>7} {'1-я':>7} {'2-я неп':>7} {'2-я с 0':>7} | "
              f"{'просадка':>8} {'итог/пр':>7}")
        for name, mem in PORTS.items():
            x = np.mean([R[(s, t, cap, 0)][4].astype(np.float64) for s, t in mem], axis=0)
            m = float(np.mean([R[(s, t, cap, 0)][5] for s, t in mem]))
            h0 = np.mean([R[(s, t, cap, mid)][4].astype(np.float64) for s, t in mem], axis=0)
            eq, dd = x[-1], dd_of(x)
            print(f"{name:>26} | {eq:+7.0f} {m:+7.0f} {eq - m:+7.0f} {h0[-1]:+7.0f} | {dd:+8.0f} "
                  f"{eq / -dd if dd < 0 else float('inf'):7.2f}")


if __name__ == "__main__":
    main()
