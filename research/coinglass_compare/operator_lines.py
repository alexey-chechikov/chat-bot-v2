"""Проверка чтения оператора 28.10 («видно, что продают или покупают и как сильно; в совокупности с другими
индикаторами можно сделать вероятностный вывод заранее» — скрин BTCUSDT 1ч 05.09–03.10: линии тренда по Aggregated
Futures Bid & Ask Delta, фандингу, L/S аккаунтов, Whale Index 2; все вверх 09–21.09 → рост, все вниз 23.09–03.10).

ПРАВИЛА — записаны до прогона, после не менять:
- Данные: CoinGlass суперчарт 1ч (exportData, сверен с легендой), 01.05–27.10.2026 (бесплатная глубина 180 дней),
  BTCUSDT и ETHUSDT; цена — Binance close оттуда же. Скачивает research/coinglass_compare/tv_history.py.
- Тренд индикатора в момент t: знак наклона МНК по последним N часовым значениям, бары ≤ t (будущего нет).
  Индикаторы с его скрина: B = Bid & Ask Delta (стакан ±1%), F = ставка фандинга Binance, L = L/S аккаунтов,
  W = Whale Index 2. Вариант S5 — плюс T = дельта тейкеров (кто покупает по рынку), все биржи.
- Совокупность S4 = sgn(B)+sgn(F)+sgn(L)+sgn(W). Вывод «вверх» при S4 ≥ +3, «вниз» при S4 ≤ −3, иначе вывода нет.
- Решение раз в сутки в 00:00 UTC (решения не перекрываются по времени принятия). Исход — знак доходности close
  через H часов. Основной вариант: N = 72, H = 72, порог 3. Соседи (отдельной таблицей): N 24/168, H 24/72, порог 2/4.
- Контроли: (1) доля «вверх» среди всех дней (дрейф); (2) импульс цены — знак наклона цены за те же N часов;
  (3) сдвиг всех индикаторов вместе по кругу относительно цены на k часов (k от 240 до длины−240), ранг
  (k_лучше+1)/(n+1); (4) половины: май–июль и август–октябрь.
- Порог «работает»: попадание выше 50% и выше дрейфа, ранг сдвига ≤ 0.05, обе половины выше 50%. BTC и ETH — не
  независимые подтверждения.

    .venv/bin/python3 research/coinglass_compare/operator_lines.py
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
IND4 = ("bid_ask_delta", "fr_pct", "ls_acc", "wi2")
IND5 = IND4 + ("taker_delta",)


def load(sym: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{sym}_1h.csv", parse_dates=["bar_utc"]).set_index("bar_utc").sort_index()
    df = df[df.index >= "2026-05-01"]
    df.index = df.index + pd.Timedelta(hours=1)             # метка = закрытие бара: значение известно в этот момент
    return df


def slope_sign(x: pd.Series, n: int) -> pd.Series:
    """Знак наклона МНК по последним n значениям (только прошлое и текущий закрытый бар)."""
    t = np.arange(n, dtype=float)
    t -= t.mean()
    den = (t ** 2).sum()
    s = x.rolling(n, min_periods=n).apply(lambda v: np.dot(t, v - v.mean()) / den, raw=True)
    return np.sign(s)


def calls(df: pd.DataFrame, n: int, h: int, thr: int, inds=IND4, shift: int = 0) -> pd.DataFrame:
    """Решения в 00:00 UTC: сумма знаков трендов, вывод при |S| ≥ thr, исход — знак доходности через h часов.
    shift — сдвиг индикаторов по кругу относительно цены (контроль)."""
    sg = pd.DataFrame({c: slope_sign(df[c], n) for c in inds})
    if shift:
        sg = pd.DataFrame(np.roll(sg.values, shift, axis=0), index=sg.index, columns=sg.columns)
    s = sg.sum(axis=1, min_count=len(inds))
    fwd = df["close"].shift(-h) / df["close"] - 1
    mom = slope_sign(df["close"], n)
    out = pd.DataFrame({"S": s, "fwd": fwd, "mom": mom})
    out = out[(out.index.hour == 0)].dropna()
    out["call"] = np.where(out["S"] >= thr, 1, np.where(out["S"] <= -thr, -1, 0))
    return out


def stats(c: pd.DataFrame) -> dict:
    k = c[c["call"] != 0]
    hit = (np.sign(k["fwd"]) == k["call"]).mean() if len(k) else float("nan")
    return {"n": len(k), "hit": hit, "ret": (k["call"] * k["fwd"]).mean() * 100 if len(k) else float("nan"),
            "days": len(c), "up_share": (c["fwd"] > 0).mean(),
            "mom_hit": (np.sign(c["fwd"]) == c["mom"]).mean()}


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n or math.isnan(p):
        return float("nan"), float("nan")
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - m, c + m


def shift_rank(df: pd.DataFrame, n: int, h: int, thr: int, inds, real_hit: float) -> tuple[float, int]:
    L = len(df)
    ks = range(240, L - 240, 7)                             # шаг 7 ч — разные фазы суток
    better = 0
    tot = 0
    for k in ks:
        st = stats(calls(df, n, h, thr, inds, shift=k))
        if st["n"] < 10:
            continue
        tot += 1
        better += st["hit"] >= real_hit
    return (better + 1) / (tot + 1), tot


def main() -> None:
    for sym in ("BTCUSDT", "ETHUSDT"):
        df = load(sym)
        print(f"\n=== {sym}: {df.index[0]:%d.%m} – {df.index[-1]:%d.%m}, {len(df)} ч")
        for name, inds in (("S4 (его скрин)", IND4), ("S5 (+ тейкеры)", IND5)):
            c = calls(df, 72, 72, 3 if name.startswith("S4") else 4, inds)
            st = stats(c)
            lo, hi = wilson(st["hit"], st["n"])
            rank, tot = shift_rank(df, 72, 72, 3 if name.startswith("S4") else 4, inds, st["hit"])
            half = [stats(c[c.index < "2026-08-01"]), stats(c[c.index >= "2026-08-01"])]
            print(f"{name}: выводов {st['n']} из {st['days']} дней, попадание {st['hit']:.0%} "
                  f"[{lo:.0%}–{hi:.0%}], средняя доходность по выводу {st['ret']:+.2f}% за 72 ч; "
                  f"дрейф (доля роста) {st['up_share']:.0%}; импульс цены {st['mom_hit']:.0%}; "
                  f"ранг сдвига {rank:.3f} ({tot}); половины {half[0]['hit']:.0%} (n {half[0]['n']}) / "
                  f"{half[1]['hit']:.0%} (n {half[1]['n']})")
        print("одиночные индикаторы (знак наклона 72 ч → знак 72 ч, все дни):")
        for ind in IND5:
            c = calls(df, 72, 72, 1, (ind,))
            st = stats(c)
            print(f"  {ind}: {st['hit']:.0%} (n {st['n']})")
        print("соседи (S4): N/H/порог → выводов, попадание, доходность")
        for n in (24, 72, 168):
            for h in (24, 72):
                for thr in (2, 3, 4):
                    st = stats(calls(df, n, h, thr, IND4))
                    print(f"  {n:>3}/{h:>2}/{thr}: {st['n']:>3} {st['hit']:.0%} {st['ret']:+.2f}%")
        # ПОСЛЕ прогона (не основной вариант): «все четыре в одну сторону» почти не бывает (S4 чётное: ±4 только
        # при полном согласии), поэтому — «3 из 4» (порог 2) и лучшие клетки соседей — тем же контролем сдвига
        print("после прогона, порог 2 (3 из 4): N/H → попадание [ДИ], ранг сдвига, половины")
        for n, h in ((72, 72), (72, 24), (168, 72)):
            c = calls(df, n, h, 2, IND4)
            st = stats(c)
            lo, hi = wilson(st["hit"], st["n"])
            rank, tot = shift_rank(df, n, h, 2, IND4, st["hit"])
            half = [stats(c[c.index < "2026-08-01"]), stats(c[c.index >= "2026-08-01"])]
            print(f"  {n}/{h}: {st['hit']:.0%} [{lo:.0%}–{hi:.0%}] n {st['n']}, ранг {rank:.3f} ({tot}), "
                  f"половины {half[0]['hit']:.0%} (n {half[0]['n']}) / {half[1]['hit']:.0%} (n {half[1]['n']})")
        c = calls(df, 72, 24, 2, IND4)
        k = c[c["call"] != 0]
        print(f"  72/24: импульс цены на тех же днях {(np.sign(k['fwd']) == k['mom']).mean():.0%}, "
              f"вывод совпал с импульсом {(k['call'] == k['mom']).mean():.0%}; без одного индикатора (3 из 3):",
              ", ".join(f"−{d} {stats(calls(df, 72, 24, 3, tuple(i for i in IND4 if i != d)))['hit']:.0%}"
                        f" (n {stats(calls(df, 72, 24, 3, tuple(i for i in IND4 if i != d)))['n']})" for d in IND4))
        ex = calls(df, 72, 72, 1, IND4)
        ex = ex[(ex.index >= "2026-09-07") & (ex.index <= "2026-10-04")]
        print("его пример 07.09–03.10 (S4 в 00:00 UTC, доходность 72 ч):")
        print("  " + "  ".join(f"{t:%d.%m}:{int(r.S):+d}/{r.fwd * 100:+.1f}%" for t, r in ex.iterrows()))


if __name__ == "__main__":
    main()
