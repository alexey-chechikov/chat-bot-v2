"""«Стакан красный на росте → шорт / прикрыть лонг» (оператор 28.10 по картинке Bid&Ask Delta ±1%) и зеркальные условия.

ПРАВИЛА ЗАПИСАНЫ ДО ПРОГОНА (28.10.2026):
- данные: выгрузка CoinGlass 1h (research/coinglass_compare/data, atlas.load — только сверенные и закрытые бары);
  bid_ask_delta (заявки ±1%, монеты), close/high/low;
- S1 «продажи на росте» на закрытии бара t: рост за 24 ч ≥ +1.0% И из последних 6 баров ≥5 с bid_ask_delta < 0;
  C1 (контроль): тот же рост, красных ≤1 из 6; S2 «покупки на падении»: падение ≥1% и ≥5 из 6 зелёных (лонг);
  RISE — любой рост ≥1% (база);
- вход по close t, после срабатывания пауза 24 ч (неперекрывающиеся случаи);
- исход: ход за 6/12/24 ч; сделка S1/C1/RISE — шорт на 24 ч, S2 — лонг, минус 0.096% (тейкер×2); худший ход против за 24 ч;
- плацебо: ряд стакана сдвинут по кругу на случайные ≥7 сут (999 сдвигов), цена та же → ранг (k+1)/(n+1)
  (для S1/S2 — доля сдвигов с итогом сделки не ниже; для C1 — с ходом 24 ч не ниже, т.е. продолжение роста);
- разрез по времени: до 01.08.2026 / после.
Первый прогон 28.10 (BTC/ETH, выгрузка в scratchpad): S1 BTC n 57 −0.09% (ранг 0.33), ETH n 60 +0.10% (0.105);
C1 BTC n 31 ход +0.66% (ранг 0.013), ETH n 48 +0.75% (0.003). Здесь — тот же расчёт по всем сверенным монетам.

    .venv/bin/python3 research/indicator_atlas/book_on_rise.py [SYM ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.indicator_atlas import atlas  # noqa: E402

COST, RISE, RED_MIN, GREEN_MAX = 0.096, 1.0, 5, 1
CUT = pd.Timestamp("2026-08-01", tz="UTC")
OUT = Path(__file__).resolve().parent / "book_on_rise_result.json"


def triggers(c: np.ndarray, book: np.ndarray, kind: str) -> list[int]:
    red6 = pd.Series(np.where(np.isnan(book), np.nan, (book < 0).astype(float))).rolling(6, min_periods=6).sum().to_numpy()
    out, last = [], -10**9
    for t in range(24, len(c) - 24):
        if np.isnan(c[t]) or np.isnan(c[t - 24]):
            continue
        r24 = (c[t] / c[t - 24] - 1) * 100
        if kind == "S1":
            ok = r24 >= RISE and red6[t] >= RED_MIN
        elif kind == "C1":
            ok = r24 >= RISE and red6[t] <= GREEN_MAX
        elif kind == "S2":
            ok = r24 <= -RISE and (6 - red6[t]) >= RED_MIN
        else:
            ok = r24 >= RISE
        if ok and t - last >= 24:
            out.append(t)
            last = t
    return out


def outcome(df: pd.DataFrame, ts: list[int], short: bool) -> pd.DataFrame:
    c, h, lo = df["close"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float)
    rows = []
    for t in ts:
        if np.isnan(c[t + 24]):
            continue
        f = {k: (c[t + k] / c[t] - 1) * 100 for k in (6, 12, 24)}
        adverse = (np.nanmax(h[t + 1:t + 25]) / c[t] - 1) * 100 if short else (1 - np.nanmin(lo[t + 1:t + 25]) / c[t]) * 100
        rows.append({"t": df.index[t], **{f"f{k}": v for k, v in f.items()}, "adverse": adverse,
                     "pnl": (-f[24] if short else f[24]) - COST})
    return pd.DataFrame(rows, columns=["t", "f6", "f12", "f24", "adverse", "pnl"])


def summ(o: pd.DataFrame) -> dict:
    if o.empty:
        return {"n": 0}
    se = o["pnl"].std(ddof=1) / np.sqrt(len(o)) if len(o) > 1 else float("nan")
    return {"n": len(o), "f6": o.f6.mean(), "f12": o.f12.mean(), "f24": o.f24.mean(), "pnl": o.pnl.mean(),
            "ci95": 1.96 * se, "win": (o.pnl > 0).mean(), "adverse_med": o.adverse.median()}


def placebo(df, book, kind, short, stat, actual, reps=999, seed=7) -> float:
    rng = np.random.default_rng(seed)
    c = df["close"].to_numpy(float)
    k = 0
    for _ in range(reps):
        s = int(rng.integers(168, len(book) - 168))
        o = outcome(df, triggers(c, np.roll(book, s), kind), short)
        if len(o) and o[stat].mean() >= actual:
            k += 1
    return (k + 1) / (reps + 1)


def run(sym: str) -> dict:
    df = atlas.load(sym)
    c, book = df["close"].to_numpy(float), df["bid_ask_delta"].to_numpy(float)
    res = {"bars": len(df), "first": str(df.index[0]), "last": str(df.index[-1])}
    for kind, short in (("S1", True), ("C1", True), ("RISE", True), ("S2", False)):
        o = outcome(df, triggers(c, book, kind), short)
        r = summ(o)
        r["halves"] = {"до 01.08": summ(o[o.t < CUT]), "после": summ(o[o.t >= CUT])}
        if kind in ("S1", "S2") and r["n"]:
            r["rank_pnl"] = placebo(df, book, kind, short, "pnl", o["pnl"].mean())
        if kind == "C1" and r["n"]:
            r["rank_f24"] = placebo(df, book, kind, short, "f24", o["f24"].mean(), seed=11)
        res[kind] = r
    return res


def main() -> None:
    syms = [a.upper() for a in sys.argv[1:]] or atlas.available()
    out = {"rules": "см. docstring", "results": {}}
    for s in syms:
        r = run(s)
        out["results"][s] = r
        s1, c1 = r["S1"], r["C1"]
        print(f"{s:9s} S1 n {s1['n']:3d} сделка {s1.get('pnl', float('nan')):+.2f}% ранг {s1.get('rank_pnl', float('nan')):.3f} | "
              f"C1 n {c1['n']:3d} ход 24ч {c1.get('f24', float('nan')):+.2f}% ранг {c1.get('rank_f24', float('nan')):.3f} "
              f"(половины {c1['halves']['до 01.08'].get('f24', float('nan')):+.2f} / {c1['halves']['после'].get('f24', float('nan')):+.2f}) | "
              f"RISE ход 24ч {r['RISE'].get('f24', float('nan')):+.2f}%", flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
