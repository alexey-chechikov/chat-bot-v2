"""Стоп по падению для лонг-сеток (идея оператора 21.10): «за время T цена упала на X% от максимума — закрыть лоты
(мелких ботов или все лонги) и ждать сигнала на вход снова». Замер на истории ДО разбора по свечам в TradingView.

ПРАВИЛА ДО ПРОГОНА (не менять после):
- База — механика regime_grid/density_compare, режим longflat (лонг выше SMA100, на смене режима закрытие по рынку),
  мейкер 0.016%, тейкер 0.048% + проскальзывание 0.02%, путь минуты path4, фандинг Binance (лонг платит).
- Сетки — живые настройки: BTC 0.6/1.4 0.0012 потолок $12 000 / 50 лотов; B34 0.1/0.34 0.0012 $3 000 / 30;
  B49 0.1/0.49 0.0012 $3 000 / 30; B89 0.1/0.89 0.0012 $2 000 / 20.
- Стоп: пока лонг разрешён режимом и сетка не на паузе, по закрытию минуты i: close[i] ≤ max(high за последние T минут,
  но не раньше последнего возобновления) × (1 − X) → на открытии минуты i+1 все лоты сетки закрываются по рынку
  (тейкер + проскальзывание), входы на паузе. Стоп срабатывает и без лотов (тогда только пауза входов).
- Возобновление: «cool» — через 24 ч после стопа; «back» — первое закрытие минуты не ниже цены, по которой продали.
  На смене режима пауза снимается (режим сам решает, есть ли лонг).
- Сетка: X ∈ {3, 5, 8}%, T ∈ {6 ч, 24 ч, 72 ч}, возобновление ∈ {cool, back} — 18 вариантов на сетку + база без стопа.
- Отчёт: итог (закрыто − комиссии − фандинг + мешок), 1-я и 2-я половины непрерывно, худшая просадка по минутам,
  число стопов, деньги, отданные на стопах. Вариант считается, только если лучше базы И в обеих половинах, И по
  просадке; тогда — контроль «те же стопы, сдвинутые во времени» (как lfgshift 18.10). Без контроля выводов нет.

ВАРИАНТ --rally (21.10, вторая половина идеи оператора «выросли — продали, пауза входов»), правила до прогона:
- по закрытию минуты: close ≥ min(low за T, не раньше возобновления) × (1 + Y) → на открытии следующей минуты все
  лоты по рынку (тейкер + проскальзывание), входы на паузе;
- возобновление: «dip» — закрытие минуты ≤ максимума с начала паузы × (1 − 3%); «cool» — через 24 ч;
- Y ∈ {5, 8, 12}%, T ∈ {24 ч, 72 ч, 7 сут}; критерий и контроль — те же.
Запуск: drop_stop.py [BTCUSDT] --src=<копия frozen> [--rally]
"""
from __future__ import annotations

import sys
from collections import deque
from concurrent.futures import ProcessPoolExecutor

import numpy as np

SNAP = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--src=")),
            "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")
SYMBOL = next((a for a in sys.argv[1:] if a.endswith("USDT")), "BTCUSDT")
ARGV = list(sys.argv)
RALLY = "--rally" in sys.argv
# рабочие процессы (spawn) заново импортируют модуль с этим sys.argv — флаг --rally обязан в нём остаться
# (21.10: без этого вариант --rally молча считал стоп по падению)
sys.argv = [sys.argv[0], SYMBOL, f"--src={SNAP}", "--max-lots=100000"] + (["--rally"] if RALLY else [])
sys.path.insert(0, "/Users/alexeychechikov/code/bot7/research/weex")
import regime_grid as rg  # noqa: E402
import fast_grid as fg  # noqa: E402

MAKER, TAKER, SLIP = rg.MAKER, rg.TAKER, rg.SLIP
GRIDS = {"BTC 0.6/1.4": (0.6, 1.4, 0.0012, 12000.0, 50), "B34": (0.1, 0.34, 0.0012, 3000.0, 30),
         "B49": (0.1, 0.49, 0.0012, 3000.0, 30), "B89": (0.1, 0.89, 0.0012, 2000.0, 20)}
XS = (0.05, 0.08, 0.12) if RALLY else (0.03, 0.05, 0.08)
TS = (1440, 4320, 10080) if RALLY else (360, 1440, 4320)
MODES = ("cool", "dip") if RALLY else ("cool", "back")
DIP = 0.03
COOL = 1440


def run(args):
    gname, X, T, mode, *rest = args
    forced = rest[0] if rest else None             # контроль: срабатывания в заданные минуты вместо правила
    fired: list[int] = []
    step, tgt, qty, cap, max_lots = GRIDS[gname]
    ts, o, h, l, c, reg = DATA[:6]
    bound = np.r_[False, reg[1:] != reg[:-1]].tolist()
    o, h, l, c, reg = o.tolist(), h.tolist(), l.tolist(), c.tolist(), reg.tolist()
    peak_p = 0.0
    pts, F = PTS, FUND
    g, t = step / 100, tgt / 100
    lots: list[list[float]] = []
    Q = QE = real = fee = fund = 0.0
    ref = None
    n = len(ts)
    mid_i = n // 2
    eq_mid = None
    peak = dd = 0.0
    paused, pending = False, False
    stop_i = 0
    stop_px = 0.0
    dq: deque = deque()
    n_stops = 0
    stop_pnl = 0.0
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
            paused, pending = False, False
            dq.clear()
        prev = bool(reg[i])
        if pending:                                   # стоп, решённый на закрытии прошлой минуты
            fired.append(i - 1)
            pending = False
            if lots:
                px = o[i] * (1 - SLIP)
                pnl = Q * px - QE
                real += pnl
                stop_pnl += pnl
                fee += Q * px * TAKER
                lots, Q, QE = [], 0.0, 0.0
            ref = None
            paused, stop_i, stop_px = True, i, o[i]
            peak_p = o[i]
            n_stops += 1
        if paused:
            if i > stop_i:
                peak_p = max(peak_p, h[i - 1])
            if (mode == "cool" and i - stop_i >= COOL) or (mode == "back" and i > stop_i and c[i - 1] >= stop_px) \
                    or (mode == "dip" and i > stop_i and c[i - 1] <= peak_p * (1 - DIP)):
                paused = False
                dq.clear()
        act = bool(reg[i]) and not paused
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
            if p <= lvl and len(lots) < max_lots and max(QE, Q * p) + qty * lvl <= cap:
                lots.append([lvl, lvl * (1 + t)])
                fee += qty * lvl * MAKER
                Q += qty
                QE += qty * lvl
        if act and forced is not None:
            if i in forced:
                pending = True
        elif act and X > 0 and RALLY:
            while dq and dq[-1][1] >= l[i]:
                dq.pop()
            dq.append((i, l[i]))
            while dq[0][0] <= i - T:
                dq.popleft()
            if c[i] >= dq[0][1] * (1 + X):
                pending = True
        elif act and X > 0:
            while dq and dq[-1][1] <= h[i]:
                dq.pop()
            dq.append((i, h[i]))
            while dq[0][0] <= i - T:
                dq.popleft()
            if c[i] <= dq[0][1] * (1 - X):
                pending = True
        eq = real - fee - fund + (Q * c[i] - QE)
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    eq = real - fee - fund + (Q * c[-1] - QE)
    return gname, X, T, mode, eq, eq_mid, dd, n_stops, stop_pnl, fired


def init(data, pts, fund):
    global DATA, PTS, FUND
    DATA, PTS, FUND = data, pts.tolist(), fund


def control(data, pts, fund, n_ctl, cfg):
    """Контроль «те же срабатывания, сдвинутые во времени» (как lfgshift 18.10): минуты решений настоящего прогона
    сдвигаются по кругу на случайную величину (10–90% длины); дальше та же продажа и то же правило паузы."""
    X, T, mode = cfg
    n = len(data[0])
    rng = np.random.default_rng(20261021)
    offs = rng.integers(n // 10, n - n // 10, size=n_ctl)
    with ProcessPoolExecutor(max_workers=4, initializer=init, initargs=(data, pts, fund)) as ex:
        real = {r[0]: r for r in ex.map(run, [(gn, X, T, mode) for gn in GRIDS])}
        base = {r[0]: r for r in ex.map(run, [(gn, 0.0, 0, 'none') for gn in GRIDS])}
        for gn in GRIDS:
            fired = real[gn][9]
            jobs = [(gn, X, T, mode, frozenset(int((f + o) % n) for f in fired)) for o in offs]
            sh = list(ex.map(run, jobs))
            eqs = np.array([r[4] for r in sh])
            dds = np.array([r[6] for r in sh])
            k_eq = int((eqs >= real[gn][4]).sum())
            k_dd = int((dds >= real[gn][6]).sum())
            print(f"{gn}: правило {X * 100:.0f}%/{T // 60}ч/{mode}: итог {real[gn][4]:+.0f} (база {base[gn][4]:+.0f}), "
                  f"просадка {real[gn][6]:+.0f} (база {base[gn][6]:+.0f}), срабатываний {len(fired)} | сдвинутые "
                  f"({n_ctl}): итог медиана {np.median(eqs):+.0f}, 10–90% {np.quantile(eqs, .1):+.0f}…"
                  f"{np.quantile(eqs, .9):+.0f}, ранг итога {(k_eq + 1) / (n_ctl + 1):.3f}; просадка медиана "
                  f"{np.median(dds):+.0f}, ранг {(k_dd + 1) / (n_ctl + 1):.3f}", flush=True)


def main():
    data = rg.load()
    ts = data[0]
    pts = fg.path4(*data[1:5])
    fr = rg.pd.read_csv(f"/Users/alexeychechikov/code/bot7/backtests/frozen/{SYMBOL}_funding_full.csv")
    ft = fr["fundingTime"].to_numpy(np.int64) // 1000
    idx = np.searchsorted(ts, ft, side="right") - 1
    ok = (idx >= 0) & (ft < ts[-1] + 60)
    fund = {int(i): float(r) for i, r in zip(idx[ok], fr["fundingRate"].to_numpy(float)[ok])}
    print(f"окно {rg.pd.to_datetime(ts[0], unit='s').date()} … {rg.pd.to_datetime(ts[-1], unit='s').date()}, "
          f"выше SMA100 {data[5].mean():.0%}, срез {rg.cut_label(ts)}; фандинг до "
          f"{rg.pd.to_datetime(int(ft[ok][-1]), unit='s')} UTC", flush=True)
    ctl = next((int(a.split('=', 1)[1]) for a in ARGV if a.startswith('--ctl=')), 0)
    if ctl:
        cfg = next(a.split('=', 1)[1] for a in ARGV if a.startswith('--cfg='))      # --cfg=0.12,4320,dip
        x, t, m = cfg.split(',')
        control(data, pts, fund, ctl, (float(x), int(t), m))
        return
    jobs = [(gn, 0.0, 0, "none") for gn in GRIDS]
    jobs += [(gn, X, T, m) for gn in GRIDS for X in XS for T in TS for m in MODES]
    with ProcessPoolExecutor(max_workers=4, initializer=init, initargs=(data, pts, fund)) as ex:
        res = list(ex.map(run, jobs))
    base = {r[0]: r for r in res if r[3] == "none"}
    for gn in GRIDS:
        b = base[gn]
        print(f"\n=== {gn}: без стопа итог {b[4]:+.0f} (1-я {b[5]:+.0f}, 2-я {b[4] - b[5]:+.0f}), просадка {b[6]:+.0f} ===")
        print(f"{'X':>4} {'T':>4} {'вход':>5} | {'итог':>6} {'Δитог':>6} {'Δ1-я':>6} {'Δ2-я':>6} | {'просадка':>8} "
              f"{'Δпрос':>6} | {'стопов':>6} {'на стопах':>9} | лучше базы везде")
        for r in res:
            if r[0] != gn or r[3] == "none":
                continue
            _, X, T, m, eq, mid, dd, ns, sp, _f = r
            d1, d2, ddd = mid - b[5], (eq - mid) - (b[4] - b[5]), dd - b[6]
            good = "ДА" if (d1 > 0 and d2 > 0 and ddd > 0) else ""
            print(f"{X * 100:3.0f}% {T // 60:3d}ч {m:>5} | {eq:+6.0f} {eq - b[4]:+6.0f} {d1:+6.0f} {d2:+6.0f} | "
                  f"{dd:+8.0f} {ddd:+6.0f} | {ns:6d} {sp:+9.0f} | {good}")


if __name__ == "__main__":
    main()
