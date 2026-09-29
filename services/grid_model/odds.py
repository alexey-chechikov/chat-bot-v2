"""Шансы по текущему режиму: вероятность хода, уровни бота, точка отмены.

⚠️ ВЕРОЯТНОСТНАЯ ЧАСТЬ ЭТОГО МОДУЛЯ ЗАМЕНЕНА services/grid_model/odds_z.py
(29.09.2026). Зона SMA100 вне выборки оказалась самым слабым признаком
(+0.9% к базе против +10.4% у z-модели по волатильности), а вывод «после
ралли повтор реже» ниже держался на 867 днях с двумя-тремя эпизодами — на 9
годах он перевёрнут (63% против 53%). Отсюда живым остаётся bot_levels().

Отвечает на три вопроса, которые оператор задаёт каждый раз руками:
  1. какова вероятность, что цена дойдёт до уровня X за N дней — с поправкой
     на то, где мы сейчас относительно SMA100;
  2. где у конкретного бота критические уровни (граница, обнуление счёта);
  3. при какой цене текущий сценарий отменяется.

ЧТО ЗАМЕРЕНО (867 дней, 15.05.2024–28.09.2026, замер 28.09.2026).
Условие «цена выше SMA100 более чем на 20%» режет вероятность КРУПНОГО
дальнейшего хода примерно вдвое — 8 ячеек развёртки из 9:

    горизонт  порог   безусловно   при dist>20%
       30д     +20%       11%            9%
       30д     +32%        4%            2%
       60д     +20%       25%           13%
       60д     +32%       14%            9%
       90д     +20%       32%           13%
       90д     +32%       19%            9%

Исключение — мелкий ход на коротком горизонте (+10% за 30д: 38% → 42%).
Средняя доходность вперёд в этой зоне, наоборот, ВЫШЕ обычной. Противоречия
нет: много мелких плюсов тянут среднюю, а крупные рывки становятся реже.
Для сетки с ограниченным мешком важен хвост, а не среднее.

⚠️ ВЫБОРКА СЛАБАЯ. Дней с отклонением >20% всего 65 из 867 (7% времени), и
они собраны в один эпизод на 47 дней плюс девять коротких. Независимых
наблюдений два-три, а не 53. Карточка обязана показывать это числом.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BUCKETS = ((-1e9, 0.0, "ниже SMA100"), (0.0, 10.0, "0…10%"),
           (10.0, 20.0, "10…20%"), (20.0, 1e9, "выше 20%"))
HORIZONS = (30, 60, 90)


def load_daily() -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Дневные закрытия, отклонение от SMA100 в %, даты."""
    import pandas as pd

    from services.short_gate import loop as sg

    closes = sg.daily_closes_from_csv(sg.FROZEN_1M, "ts", "close", ms=True)
    closes.update(sg.daily_closes_from_csv(sg.LIVE_1M, "ts_utc", "close"))
    s = pd.Series(closes).sort_index()
    sma = s.rolling(100).mean()
    dist = ((s / sma - 1) * 100).to_numpy()
    return s.to_numpy(dtype=float), dist, [str(x) for x in s.index]


def bucket_of(dist_pct: float) -> str:
    for lo, hi, name in BUCKETS:
        if lo <= dist_pct < hi:
            return name
    return BUCKETS[-1][2]


def episodes(mask: np.ndarray) -> list[int]:
    """Длины непрерывных отрезков — чтобы видеть, сколько наблюдений НЕЗАВИСИМЫ."""
    out, cur = [], 0
    for x in mask:
        if x:
            cur += 1
        elif cur:
            out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out


@dataclass
class Odds:
    horizon: int
    pct: float
    base: float
    cond: float
    n_cond: int
    n_episodes: int


def prob_reach(prices: np.ndarray, dist: np.ndarray, pct: float, horizon: int,
               bucket: str, up: bool = True) -> Odds:
    """Вероятность, что цена ХОТЬ РАЗ дойдёт до ±pct за horizon дней."""
    base, cond, mask = [], [], []
    for i in range(len(prices) - horizon):
        w = prices[i:i + horizon + 1]
        move = (w.max() / w[0] - 1) if up else (w.min() / w[0] - 1)
        hit = move >= pct if up else move <= pct
        base.append(hit)
        in_b = (not np.isnan(dist[i])) and bucket_of(dist[i]) == bucket
        mask.append(in_b)
        if in_b:
            cond.append(hit)
    eps = episodes(np.array(mask))
    return Odds(horizon, pct,
                float(np.mean(base)) if base else float("nan"),
                float(np.mean(cond)) if cond else float("nan"),
                len(cond), len(eps))


@dataclass
class BotLevels:
    price: float
    avg: float
    position: float           # в монете, со знаком (шорт отрицательный)
    max_position: float
    capped_avg: float
    border: float | None
    zero_equity: float        # цена, где мешок съедает залог
    pct_to_zero: float


def bot_levels(price: float, avg: float, position: float, step_pct: float,
               order_size: float, deposit: float, border: float | None,
               short: bool, max_orders: int = 400,
               adverse_pct: float = 40.0) -> BotLevels:
    """Докуда бот доберёт и при какой цене обнулится залог.

    С границей набор упирается в неё. БЕЗ границы потолка нет, поэтому берём
    замеренный ход против позиции за калибровочный год (40% для Auto, 64% для
    одностороннего) — иначе точка обнуления считается по сегодняшней позиции
    и выглядит недостижимо далёкой.
    """
    pos = abs(position)
    lots, p = [], price
    limit = border if border else (
        price * (1 + adverse_pct / 100) if short
        else price * (1 - adverse_pct / 100))
    while len(lots) < max_orders:
        nxt = p * (1 + step_pct / 100) if short else p * (1 - step_pct / 100)
        if (nxt > limit) if short else (nxt < limit):
            break
        p = nxt
        lots.append(p)
    max_pos = pos + len(lots) * order_size
    capped_avg = ((pos * avg + sum(lots) * order_size) / max_pos
                  if max_pos > 0 else avg)
    zero = (capped_avg + deposit / max_pos if short
            else capped_avg - deposit / max_pos) if max_pos > 0 else 0.0
    return BotLevels(price, avg, position, max_pos, capped_avg, border, zero,
                     (zero / price - 1) * 100 if price else 0.0)


def card(prices: np.ndarray, dist: np.ndarray, dates: list[str],
         levels: BotLevels | None = None, name: str = "") -> str:
    now, d = float(prices[-1]), float(dist[-1])
    b = bucket_of(d)
    mask = np.array([(not np.isnan(x)) and bucket_of(x) == b for x in dist])
    eps = episodes(mask)
    out = [f"🎲 ШАНСЫ ПО РЕЖИМУ{' · ' + name if name else ''}",
           f"цена {now:,.0f} · SMA100 {now / (1 + d / 100):,.0f} · "
           f"отклонение {d:+.1f}% · зона «{b}»",
           f"в этой зоне {int(mask.sum())} дней из {len(prices)} "
           f"({mask.mean():.0%} времени), {len(eps)} эпизодов, "
           f"самый длинный {max(eps) if eps else 0} дней"]

    edge = next((lo for lo, hi, n in BUCKETS if n == b), None)
    hi_edge = next((hi for lo, hi, n in BUCKETS if n == b), None)
    if edge is not None and edge > -1e8:
        px = now / (1 + d / 100) * (1 + edge / 100)
        out.append(f"ОТМЕНА ЗОНЫ снизу: цена {px:,.0f} ({px / now - 1:+.1%}) — "
                   f"ниже неё статистика этой карточки не применима")
    if hi_edge is not None and hi_edge < 1e8:
        px = now / (1 + d / 100) * (1 + hi_edge / 100)
        out.append(f"ОТМЕНА ЗОНЫ сверху: цена {px:,.0f} ({px / now - 1:+.1%})")

    targets = [0.10, 0.20]
    if levels is not None:
        targets.append(round(abs(levels.pct_to_zero) / 100, 3))
    out.append("\nВЕРОЯТНОСТЬ ДОЙТИ ВВЕРХ (против шорта):")
    out.append(f"  {'порог':>8}{'30д':>18}{'60д':>18}{'90д':>18}")
    for t in sorted(set(targets)):
        row = f"  {t:>7.0%} "
        for h in HORIZONS:
            o = prob_reach(prices, dist, t, h, b)
            row += f"{o.base:>7.0%}→{o.cond:>7.0%}   "
        out.append(row)
    out.append("  (безусловно → в текущей зоне)")

    out.append("\nВЕРОЯТНОСТЬ ДОЙТИ ВНИЗ (в пользу шорта):")
    out.append(f"  {'порог':>8}{'30д':>18}{'60д':>18}{'90д':>18}")
    for t in (-0.05, -0.10, -0.20):
        row = f"  {t:>7.0%} "
        for h in HORIZONS:
            o = prob_reach(prices, dist, t, h, b, up=False)
            row += f"{o.base:>7.0%}→{o.cond:>7.0%}   "
        out.append(row)

    if levels is not None:
        out.append(f"\nУРОВНИ БОТА:")
        out.append(f"  позиция {levels.position:+.4f}, средняя {levels.avg:,.0f}")
        if levels.border:
            out.append(f"  граница {levels.border:,.0f} "
                       f"({levels.border / now - 1:+.1%}) — там набор встанет "
                       f"на {levels.max_position:.4f}, средняя "
                       f"{levels.capped_avg:,.0f}")
        else:
            out.append(f"  ГРАНИЦЫ НЕТ — набор смоделирован по замеренному ходу "
                       f"против позиции: до {levels.max_position:.4f}, средняя "
                       f"{levels.capped_avg:,.0f}")
        out.append(f"  ЗАЛОГ ОБНУЛЯЕТСЯ при {levels.zero_equity:,.0f} "
                   f"({levels.pct_to_zero:+.0f}%)")

    n = int(mask.sum())
    longest = max(eps) if eps else 0
    share = longest / n if n else 0.0
    if share > 0.5:
        honest = (f"один эпизод занимает {share:.0%} выборки — независимых "
                  f"наблюдений два-три, а не {n}")
    else:
        honest = (f"самый длинный эпизод {longest} дней из {n}, то есть "
                  f"наблюдения размазаны по {len(eps)} независимым случаям")
    out.append(f"\n⚠️ выборка: {n} дней в зоне, {len(eps)} эпизодов. {honest}. "
               f"Это лучшее, что дают данные, а не закон.")
    return "\n".join(out)
