"""Симулятор ETH Auto (DYNAMIC, две стороны, выход по средней) на минутках.

⚠️ НЕ СОШЁЛСЯ С GINAREA (01.10.2026): ошибка против развёртки оператора от
+135% до −2400% во всех трёх вариантах механики. Набор GinArea в тренде
(ETH −68% в окне) не воспроизводится. Не использовать для решений — вместо
него tools/ginarea_target_sweep.py гоняет сам движок GinArea через API.
Оставлен как документ попытки.

Задача: ответить, должна ли цель зависеть от волатильности. Прежде чем
верить симулятору, он обязан повторить развёртку оператора в GinArea
(шаг 0.1, ордер 0.01, 800 ордеров, выход по средней ВКЛ, окно
25.09.2025→17.09.2026): 0.6 → $865 … 2.0 → $3 010, 2.5 → $3 198 (±15%).

Механика (GINAREA_MECHANICS.md + живые ордера 30.09.2026):
- шорты набираются на росте: следующий шорт на шаг выше последнего входа;
  после отката уровень входа «тянется» за ценой вниз на расстоянии
  смещения so — поэтому у живого бота шорты открыты и на низких ценах;
- лонги — зеркально;
- выход по средней: сторона закрывается целиком, когда цена доходит до
  средней стороны × (1 ∓ цель); без него — каждый ордер на своём тейке;
- комиссия 0.05% на сторону, оборот = вход + выход (как в GinArea: маржа
  0.502 × цель − 0.053 % на оборот);
- итог = реализованное + нереализованное на конце окна.
Путь минутной свечи: open → low → high → close (или high раньше low, если
свеча красная).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backtests" / "frozen" / "ETHUSDT_1m_2y.csv"
FEE = 0.0005


def load(a: str | None = None, b: str | None = None, path: Path = SRC) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["ts"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
    d = d.set_index("ts")[["open", "high", "low", "close"]].astype(float)
    return d.loc[a:b] if (a or b) else d


def path_points(d: pd.DataFrame) -> np.ndarray:
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    up = c >= o
    p = np.empty((len(d), 4))
    p[:, 0] = o
    p[:, 1] = np.where(up, l, h)
    p[:, 2] = np.where(up, h, l)
    p[:, 3] = c
    return p.ravel()


@dataclass
class Result:
    net: float
    realized: float
    unrealized: float
    turnover: float
    max_pos: float
    worst_bag: float
    closes: int

    @property
    def survival(self) -> float:
        return self.net / self.realized if self.realized else float("nan")


def run(pts: np.ndarray, target: float, step: float = 0.1, qty: float = 0.01,
        max_orders: int = 800, so: float = 0.75, obap: bool = True,
        targets: np.ndarray | None = None, fee: float = FEE,
        trail: bool = True, ioo: float | None = None, reset_both: bool = False) -> Result:
    """pts — цены пути; target/step/so в процентах. targets — цель на каждую
    точку пути (для правила «цель по волатильности»); тогда target игнорируется
    для НОВЫХ выходов: выход стороны считается по цели в момент проверки."""
    T, g, s = target / 100, step / 100, so / 100
    shift = (ioo / 100) if ioo is not None else None
    shorts_q = shorts_qe = 0.0      # сумма qty и qty×entry
    longs_q = longs_qe = 0.0
    s_ent: list[float] = []         # входы (для режима без выхода по средней)
    l_ent: list[float] = []
    n_open = 0
    p0 = pts[0]
    s_trig, l_trig = p0 * (1 + s), p0 * (1 - s)
    realized = turnover = 0.0
    max_pos = worst = 0.0
    closes = 0
    tarr = targets
    for i in range(1, len(pts)):
        p = pts[i]
        if tarr is not None:
            T = tarr[i] / 100
        # ── набор шортов на росте
        while p >= s_trig and n_open < max_orders:
            e = s_trig
            shorts_q += qty
            shorts_qe += qty * e
            s_ent.append(e)
            n_open += 1
            turnover += qty * e
            realized -= qty * e * fee
            if shift is None:
                s_trig = e * (1 + g)
            else:                      # документация: вход шорта двигает ОБЕ границы вверх
                s_trig = max(s_trig * (1 + shift), e * (1 + g))
                l_trig = l_trig * (1 + shift)
        # ── набор лонгов на падении
        while p <= l_trig and n_open < max_orders:
            e = l_trig
            longs_q += qty
            longs_qe += qty * e
            l_ent.append(e)
            n_open += 1
            turnover += qty * e
            realized -= qty * e * fee
            if shift is None:
                l_trig = e * (1 - g)
            else:
                l_trig = min(l_trig * (1 - shift), e * (1 - g))
                s_trig = s_trig * (1 - shift)
        # ── уровни входа тянутся за ценой на расстоянии смещения
        if trail:
            if p * (1 + s) < s_trig:
                s_trig = p * (1 + s)
            if p * (1 - s) > l_trig:
                l_trig = p * (1 - s)
        # ── выходы
        if obap:
            if shorts_q > 0:
                ex = shorts_qe / shorts_q * (1 - T)
                if p <= ex:
                    realized += shorts_qe - shorts_q * ex - shorts_q * ex * fee
                    turnover += shorts_q * ex
                    n_open -= len(s_ent)
                    shorts_q = shorts_qe = 0.0
                    s_ent = []
                    closes += 1
                    s_trig = p * (1 + s)
                    if reset_both:
                        l_trig = p * (1 - s)
            if longs_q > 0:
                ex = longs_qe / longs_q * (1 + T)
                if p >= ex:
                    realized += longs_q * ex - longs_qe - longs_q * ex * fee
                    turnover += longs_q * ex
                    n_open -= len(l_ent)
                    longs_q = longs_qe = 0.0
                    l_ent = []
                    closes += 1
                    l_trig = p * (1 - s)
                    if reset_both:
                        s_trig = p * (1 + s)
        else:
            if s_ent and p <= max(s_ent) * (1 - T):
                keep = []
                for e in s_ent:
                    if p <= e * (1 - T):
                        ex = e * (1 - T)
                        realized += qty * (e - ex) - qty * ex * fee
                        turnover += qty * ex
                        shorts_q -= qty
                        shorts_qe -= qty * e
                        n_open -= 1
                        closes += 1
                    else:
                        keep.append(e)
                s_ent = keep
            if l_ent and p >= min(l_ent) * (1 + T):
                keep = []
                for e in l_ent:
                    if p >= e * (1 + T):
                        ex = e * (1 + T)
                        realized += qty * (ex - e) - qty * ex * fee
                        turnover += qty * ex
                        longs_q -= qty
                        longs_qe -= qty * e
                        n_open -= 1
                        closes += 1
                    else:
                        keep.append(e)
                l_ent = keep
        if i % 240 == 0:
            pos = shorts_q + longs_q
            if pos > max_pos:
                max_pos = pos
            bag = (shorts_qe - shorts_q * p) + (longs_q * p - longs_qe)
            if bag < worst:
                worst = bag
    p = pts[-1]
    unreal = (shorts_qe - shorts_q * p) + (longs_q * p - longs_qe)
    return Result(realized + unreal, realized, unreal, turnover, max_pos, worst, closes)


SWEEP = [(0.6, 865.49), (0.8, 1025.97), (1.0, 629.0), (1.1, 1528.86),
         (1.3, 1777.01), (1.4, 1975.38), (1.49, 2166.70), (1.69, 2565.33),
         (1.89, 2885.22), (2.0, 3009.89), (2.2, 2516.0), (2.5, 3197.76)]


VARIANTS = {
    "тянутся": dict(trail=True),
    "док": dict(trail=False, ioo=0.1),
    "док+сброс обеих": dict(trail=False, ioo=0.1, reset_both=True),
    "тянутся+сброс обеих": dict(trail=True, reset_both=True),
}


if __name__ == "__main__":
    import sys
    var = sys.argv[1] if len(sys.argv) > 1 else "док"
    so = 0.75
    d = load("2025-09-25", "2026-09-17 23:59")
    pts = path_points(d)
    print(f"окно {d.index[0]} → {d.index[-1]}, {len(d)} минут, вариант «{var}»")
    errs = []
    for tgt, ga in SWEEP:
        r = run(pts, tgt, so=so, **VARIANTS[var])
        err = r.net / ga - 1
        errs.append(err)
        print(f"цель {tgt:>4}: сим ${r.net:>7,.0f} GinArea ${ga:>7,.0f} ({err:+.0%}) | "
              f"реализ {r.realized:,.0f} мешок конца {r.unrealized:,.0f} "
              f"оборот {r.turnover:,.0f} закрытий {r.closes} макс поз {r.max_pos:.2f} "
              f"худший мешок {r.worst_bag:,.0f}")
    print(f"медиана |ошибки| {np.median(np.abs(errs)):.0%}")
