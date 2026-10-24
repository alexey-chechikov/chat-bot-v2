"""Стоп «падение без отката» для лонг-сеток (оператор 22.10 после ночи 21→22.10: «всю ночь падаем, нет никаких тейков
коротких сеток — если бы закрыли короткие лонги на 82 900…»). Прошлый замер (drop_stop.py: упали на X% от максимума) —
72/72 хуже: такой стоп срабатывает и в падениях с откатами, где сетка отыгрывает. Здесь признак — именно отсутствие
отката.

ПРАВИЛА ДО ПРОГОНА (не менять после):
- База — та же механика, что drop_stop.py / density_compare.py: longflat (лонг выше SMA100, смена режима — закрытие по
  рынку), мейкер 0.016%, тейкер 0.048% + 0.02%, path4, фандинг Binance; живые настройки сеток B34/B49/B89/BTC 0.6/1.4.
- Правило A «нет тейков»: у сетки лотов ≥ K (K = глубина D / шаг: D ∈ {1%, 2%}) и с последнего тейка (или с первого
  лота, если тейков не было) прошло ≥ H, H ∈ {2 ч, 4 ч, 8 ч} → на открытии следующей минуты все лоты по рынку, входы
  на паузе.
- Правило B «гладкое падение»: за T ∈ {4 ч, 8 ч} цена ниже на X ∈ {1.5%, 2.5%} и гладкость ≥ 0.4 (|изменение за T| /
  сумма |15-минутных изменений| за T) → то же.
- Возобновление: «bounce» — первое закрытие минуты ≥ минимум с момента стопа × 1.01; «cool» — через 24 ч. Смена режима
  снимает паузу.
- Вариант считается, только если лучше базы в обеих половинах И по просадке; затем контроль «те же срабатывания,
  сдвинутые во времени» на заранее выбранной ячейке (A: D 1%, H 4 ч, bounce; B: X 2.5%, T 8 ч, bounce).
- Отдельно (не для вывода): что правило сделало бы в ночь 21→22.10 — в общей таблице по датам срабатываний.
Запуск: exhaust_stop.py --src=<копия frozen BTC> [--ctl=N]
"""
from __future__ import annotations

import math
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

SNAP = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--src=")),
            "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")
ARGV = list(sys.argv)
sys.argv = [sys.argv[0], "BTCUSDT", f"--src={SNAP}", "--max-lots=100000"]
sys.path.insert(0, "/Users/alexeychechikov/code/bot7/research/weex")
import regime_grid as rg  # noqa: E402
import fast_grid as fg  # noqa: E402

MAKER, TAKER, SLIP = rg.MAKER, rg.TAKER, rg.SLIP
GRIDS = {"BTC 0.6/1.4": (0.6, 1.4, 0.0012, 12000.0, 50), "B34": (0.1, 0.34, 0.0012, 3000.0, 30),
         "B49": (0.1, 0.49, 0.0012, 3000.0, 30), "B89": (0.1, 0.89, 0.0012, 2000.0, 20)}
COOL = 1440
BOUNCE = 0.01
ER_MIN = 0.4
RULES = ([("A", d, h) for d in (0.01, 0.02) for h in (120, 240, 480)]
         + [("B", x, t) for x in (0.015, 0.025) for t in (240, 480)])
MODES = ("bounce", "cool")
PRE = {"A": ("A", 0.01, 240, "bounce"), "B": ("B", 0.025, 480, "bounce")}


def run(args):
    gname, rule, mode, *rest = args
    forced = rest[0] if rest else None
    kind, p1, p2 = rule if rule else (None, 0, 0)
    step, tgt, qty, cap, max_lots = GRIDS[gname]
    ts, o, h, l, c, reg = DATA[:6]
    bound = np.r_[False, reg[1:] != reg[:-1]].tolist()
    o, l, c, reg = o.tolist(), l.tolist(), c.tolist(), reg.tolist()
    er_num, er_den = ER
    pts, F = PTS, FUND
    g, t = step / 100, tgt / 100
    K = math.ceil(p1 * 100 / step - 1e-9) if kind == "A" else 0
    lots: list[list[float]] = []
    Q = QE = real = fee = fund = 0.0
    ref = None
    n = len(ts)
    mid_i = n // 2
    eq_mid = None
    peak = dd = 0.0
    paused = pending = False
    stop_i, low_p = 0, 0.0
    last_take = -1
    first_lot = -1
    fired: list[int] = []
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
            paused = pending = False
        prev = bool(reg[i])
        if pending:
            pending = False
            fired.append(i - 1)
            if lots:
                px = o[i] * (1 - SLIP)
                pnl = Q * px - QE
                real += pnl
                stop_pnl += pnl
                fee += Q * px * TAKER
                lots, Q, QE = [], 0.0, 0.0
            ref = None
            paused, stop_i, low_p = True, i, o[i]
        if paused:
            if i > stop_i:
                low_p = min(low_p, l[i - 1])
            if (mode == "cool" and i - stop_i >= COOL) or (mode == "bounce" and i > stop_i and c[i - 1] >= low_p * (1 + BOUNCE)):
                paused = False
                last_take = i
        act = bool(reg[i]) and not paused
        for p in pts[i]:
            while lots and p >= lots[-1][1]:
                e, tp = lots.pop()
                real += qty * (tp - e)
                fee += qty * tp * MAKER
                Q -= qty
                QE -= qty * e
                last_take = i
            if not lots:
                Q = QE = 0.0
                first_lot = -1
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
                if not lots:
                    first_lot = i
                lots.append([lvl, lvl * (1 + t)])
                fee += qty * lvl * MAKER
                Q += qty
                QE += qty * lvl
        if act:
            if forced is not None:
                if i in forced:
                    pending = True
            elif kind == "A":
                since = max(last_take, first_lot)
                if len(lots) >= K and since >= 0 and i - since >= p2:
                    pending = True
            elif kind == "B" and i >= p2:
                chg = c[i] / c[i - p2] - 1
                den = er_den[i] - er_den[i - p2]
                if chg <= -p1 and den > 0 and abs(c[i] - c[i - p2]) / den >= ER_MIN:
                    pending = True
        eq = real - fee - fund + (Q * c[i] - QE)
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    eq = real - fee - fund + (Q * c[-1] - QE)
    return gname, rule, mode, eq, eq_mid, dd, len(fired), stop_pnl, fired


def init(data, pts, fund, er):
    global DATA, PTS, FUND, ER
    DATA, PTS, FUND, ER = data, pts.tolist(), fund, er


def er_arrays(c: np.ndarray):
    """Знаменатель гладкости: сумма |15-минутных изменений| — кумулятивно по каждому остатку минуты mod 15."""
    d15 = np.zeros_like(c)
    d15[15:] = np.abs(c[15:] - c[:-15])
    cs = d15.copy()
    for i in range(15, len(c)):
        cs[i] += cs[i - 15]
    return None, cs.tolist()


def main():
    data = rg.load()
    ts = data[0]
    pts = fg.path4(*data[1:5])
    fr = rg.pd.read_csv("/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_funding_full.csv")
    ft = fr["fundingTime"].to_numpy(np.int64) // 1000
    idx = np.searchsorted(ts, ft, side="right") - 1
    ok = (idx >= 0) & (ft < ts[-1] + 60)
    fund = {int(i): float(r) for i, r in zip(idx[ok], fr["fundingRate"].to_numpy(float)[ok])}
    er = er_arrays(data[4])
    print(f"окно {rg.pd.to_datetime(ts[0], unit='s').date()} … {rg.pd.to_datetime(ts[-1], unit='s')} UTC, срез "
          f"{rg.cut_label(ts)}", flush=True)
    ctl = next((int(a.split("=", 1)[1]) for a in ARGV if a.startswith("--ctl=")), 0)
    with ProcessPoolExecutor(max_workers=4, initializer=init, initargs=(data, pts, fund, er)) as ex:
        if ctl:
            control(ex, ts, ctl)
            return
        jobs = [(gn, None, "none") for gn in GRIDS] + [(gn, r, m) for gn in GRIDS for r in RULES for m in MODES]
        res = list(ex.map(run, jobs))
    base = {r[0]: r for r in res if r[1] is None}
    night = (rg.pd.Timestamp("2026-10-21 18:00").value // 10**9, rg.pd.Timestamp("2026-10-22 09:30").value // 10**9)
    for gn in GRIDS:
        b = base[gn]
        print(f"\n=== {gn}: без стопа итог {b[3]:+.0f} (1-я {b[4]:+.0f}, 2-я {b[3] - b[4]:+.0f}), просадка {b[5]:+.0f} ===")
        print(f"{'правило':<18} {'вход':>6} | {'итог':>6} {'Δитог':>6} {'Δ1-я':>6} {'Δ2-я':>6} | {'просадка':>8} {'Δпрос':>6} | "
              f"{'стопов':>6} {'на стопах':>9} | ночь 21→22 | лучше везде")
        for r in res:
            if r[0] != gn or r[1] is None:
                continue
            _, rule, m, eq, mid, dd, ns, sp, fired = r
            d1, d2, ddd = mid - b[4], (eq - mid) - (b[3] - b[4]), dd - b[5]
            nt = [rg.pd.to_datetime(int(ts[f]), unit="s").strftime("%d.%m %H:%M") for f in fired
                  if night[0] <= ts[f] <= night[1]]
            name = (f"A лотов≥{rule[1] * 100:.0f}% {rule[2] // 60}ч" if rule[0] == "A"
                    else f"B −{rule[1] * 100:.1f}% за {rule[2] // 60}ч")
            print(f"{name:<18} {m:>6} | {eq:+6.0f} {eq - b[3]:+6.0f} {d1:+6.0f} {d2:+6.0f} | {dd:+8.0f} {ddd:+6.0f} | "
                  f"{ns:6d} {sp:+9.0f} | {','.join(nt) or '—':<10} | {'ДА' if d1 > 0 and d2 > 0 and ddd > 0 else ''}")


def control(ex, ts, n_ctl):
    n = len(ts)
    offs = np.random.default_rng(20261022).integers(n // 10, n - n // 10, size=n_ctl)
    for fam, (kind, p1, p2, mode) in PRE.items():
        real = {r[0]: r for r in ex.map(run, [(gn, (kind, p1, p2), mode) for gn in GRIDS])}
        base = {r[0]: r for r in ex.map(run, [(gn, None, "none") for gn in GRIDS])}
        for gn in GRIDS:
            fired = real[gn][8]
            sh = list(ex.map(run, [(gn, None, mode, frozenset(int((f + o) % n) for f in fired)) for o in offs]))
            eqs, dds = np.array([r[3] for r in sh]), np.array([r[5] for r in sh])
            print(f"{fam} {gn}: правило итог {real[gn][3]:+.0f} (база {base[gn][3]:+.0f}), просадка {real[gn][5]:+.0f} "
                  f"(база {base[gn][5]:+.0f}), срабатываний {len(fired)} | сдвинутые ({n_ctl}): итог медиана "
                  f"{np.median(eqs):+.0f}, ранг {(int((eqs >= real[gn][3]).sum()) + 1) / (n_ctl + 1):.3f}; просадка "
                  f"медиана {np.median(dds):+.0f}, ранг {(int((dds >= real[gn][5]).sum()) + 1) / (n_ctl + 1):.3f}",
                  flush=True)


if __name__ == "__main__":
    main()
