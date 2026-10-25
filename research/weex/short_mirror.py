"""Три шорт-сетки, зеркальные B34/B49/B89 (оператор 22.10: «включить 3 аналогичные шортовые сетки с короткими таргетами»).

ПРАВИЛА ДО ПРОГОНА (не менять после):
- Механика — та же петля, что density_compare/exhaust_stop (правило GinArea: шаг от крайнего открытого лота; path4;
  мейкер 0.016% на входе и тейке; закрытие по смене режима — тейкер 0.048% + 0.02%; фандинг Binance: шорт получает
  при положительной ставке). BTC 1m Binance spot (копия frozen).
- Шорт-сетки: шаг 0.1, цели 0.34 / 0.49 / 0.89, ордер 0.0012 BTC, потолок $3 000 / $3 000 / $2 000 (зеркало живых B).
- Режимы шортов: «всегда» (без режима — так просит оператор; сейчас режим лонговый); «ниже SMA100» (канон: шорт только
  ниже, на смене режима — закрытие по рынку). Лонговые B — как живут: «выше SMA100».
- Отчёт: по каждой сетке итог / 1-я / 2-я половина / просадка; тройки и совместная кривая «лонговые B + шортовые»
  (сумма минутных кривых) — итог, половины, просадка совместной кривой, итог/просадка. Отдельно — что шорт-тройка «всегда»
  сделала бы с 21.10 18:00 UTC по сейчас (ночь падения) и в ралли (худший отрезок).
Запуск: short_mirror.py --src=<копия frozen BTC>
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
GRIDS = {"34": (0.1, 0.34, 0.0012, 3000.0), "49": (0.1, 0.49, 0.0012, 3000.0), "89": (0.1, 0.89, 0.0012, 2000.0)}


def curve(args):
    """d=+1 лонг (активен выше SMA100), d=−1 шорт: mode 'always' или 'below' (активен ниже SMA100)."""
    name, d, mode = args
    step, tgt, qty, cap = GRIDS[name]
    ts, o, h, l, c, reg = DATA[:6]
    bound = np.r_[False, reg[1:] != reg[:-1]].tolist()
    o, c, reg = o.tolist(), c.tolist(), reg.tolist()
    pts, F = PTS, FUND
    g, t = step / 100, tgt / 100
    lots: list[list[float]] = []
    Q = QE = real = fee = fund = 0.0
    ref = None
    n = len(ts)
    eq_arr = np.empty(n, dtype=np.float64)
    prev = None
    for i in range(n):
        if i in F:
            fund += d * Q * o[i] * F[i]                     # лонг платит, шорт получает при ставке > 0
        act = (bool(reg[i]) if d > 0 else (True if mode == "always" else not bool(reg[i])))
        if prev is not None and bound[i] and prev and not act:  # 25.10 R1 (аудит GPT): сброс опорной и без лотов — иначе вход от уровня старого режима
            px = o[i] * (1 - d * SLIP)
            real += d * (Q * px - QE)
            fee += Q * px * TAKER
            lots, Q, QE, ref = [], 0.0, 0.0, None
        prev = act
        for p in pts[i]:
            while lots and ((d > 0 and p >= lots[-1][1]) or (d < 0 and p <= lots[-1][1])):
                e, tp = lots.pop()
                real += d * qty * (tp - e)
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
                ref = max(ref, p) if d > 0 else min(ref, p)
            lvl = ref * (1 - d * g)
            if ((d > 0 and p <= lvl) or (d < 0 and p >= lvl)) and max(QE, Q * p) + qty * lvl <= cap:
                lots.append([lvl, lvl * (1 + d * t)])
                fee += qty * lvl * MAKER
                Q += qty
                QE += qty * lvl
        eq_arr[i] = real - fee - fund + d * (Q * c[i] - QE)
    return name, d, mode, eq_arr.astype(np.float32)


def init(data, pts, fund):
    global DATA, PTS, FUND
    DATA, PTS, FUND = data, pts.tolist(), fund


def stats(x: np.ndarray, mid: int) -> tuple[float, float, float, float]:
    x = x.astype(np.float64)
    dd = float((x - np.maximum.accumulate(np.maximum(x, 0.0))).min())
    return float(x[-1]), float(x[mid - 1]), dd, float(x[-1]) / -dd if dd < 0 else float("inf")


def main():
    data = rg.load()
    ts = data[0]
    pts = fg.path4(*data[1:5])
    fr = rg.pd.read_csv("/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_funding_full.csv")
    ft = fr["fundingTime"].to_numpy(np.int64) // 1000
    idx = np.searchsorted(ts, ft, side="right") - 1
    ok = (idx >= 0) & (ft < ts[-1] + 60)
    fund = {int(i): float(r) for i, r in zip(idx[ok], fr["fundingRate"].to_numpy(float)[ok])}
    mid = len(ts) // 2
    print(f"окно {rg.pd.to_datetime(ts[0], unit='s').date()} … {rg.pd.to_datetime(ts[-1], unit='s')} UTC, срез "
          f"{rg.cut_label(ts)}, выше SMA100 {data[5].mean():.0%} времени", flush=True)
    jobs = [(n_, 1, "above") for n_ in GRIDS] + [(n_, -1, m) for n_ in GRIDS for m in ("always", "below")]
    with ProcessPoolExecutor(max_workers=4, initializer=init, initargs=(data, pts, fund)) as ex:
        res = {(r[0], r[1], r[2]): r[3] for r in ex.map(curve, jobs)}
    print(f"\n{'сетка':<26} {'итог':>7} {'1-я':>7} {'2-я':>7} {'просадка':>9} {'итог/пр':>7}")
    groups = {}
    for (name, d, mode), x in res.items():
        tag = (f"лонг B{name} (выше SMA)" if d > 0 else f"шорт S{name} ({'всегда' if mode == 'always' else 'ниже SMA'})")
        eq, m, dd, r = stats(x, mid)
        print(f"{tag:<26} {eq:+7.0f} {m:+7.0f} {eq - m:+7.0f} {dd:+9.0f} {r:7.2f}")
        groups.setdefault((d, mode), []).append(x.astype(np.float64))
    L = sum(groups[(1, "above")])
    SA, SB = sum(groups[(-1, "always")]), sum(groups[(-1, "below")])
    print()
    for tag, x in (("лонг-тройка B (как сейчас)", L), ("шорт-тройка всегда", SA), ("шорт-тройка ниже SMA", SB),
                   ("B + шорт всегда", L + SA), ("B + шорт ниже SMA", L + SB)):
        eq, m, dd, r = stats(x, mid)
        print(f"{tag:<26} {eq:+7.0f} {m:+7.0f} {eq - m:+7.0f} {dd:+9.0f} {r:7.2f}")
    a = int(np.searchsorted(ts, rg.pd.Timestamp("2026-10-21 18:00").value // 10**9))
    print(f"\nночь 21.10 18:00 → {rg.pd.to_datetime(ts[-1], unit='s')} UTC: шорт-тройка всегда "
          f"{SA[-1] - SA[a]:+.0f}$, лонг-тройка {L[-1] - L[a]:+.0f}$")
    worst = np.argmin(SA - np.maximum.accumulate(SA))
    peak = int(np.argmax(SA[:worst + 1]))
    print(f"худший отрезок шорт-тройки «всегда»: {rg.pd.to_datetime(ts[peak], unit='s'):%d.%m.%Y} → "
          f"{rg.pd.to_datetime(ts[worst], unit='s'):%d.%m.%Y}, {SA[worst] - SA[peak]:+.0f}$; цена "
          f"{data[4][peak]:,.0f} → {data[4][worst]:,.0f} ({(data[4][worst] / data[4][peak] - 1) * 100:+.1f}%)")


if __name__ == "__main__":
    main()
