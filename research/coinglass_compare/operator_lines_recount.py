"""Досчёт к operator_lines.py по разбору GPT e53a117 (вопрос 5): «3 из 4» = не меньше трёх НЕНУЛЕВЫХ наклонов одного
знака. В operator_lines порог стоял на сумме знаков (S ≥ 2 / S ≥ 3), а при нулевом наклоне (фандинг часто стоит на
0.0100%) «два плюса и два нуля» давали S = 2 и шли в счёт. Здесь — сколько таких дней было и меняется ли результат.
Данные, окна и контроль — те же, что в operator_lines.py; правила не меняются, меняется только определение согласия.

    .venv/bin/python3 research/coinglass_compare/operator_lines_recount.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import operator_lines as ol  # noqa: E402


def calls_count(df: pd.DataFrame, n: int, h: int, need: int, inds=ol.IND4, shift: int = 0) -> pd.DataFrame:
    sg = pd.DataFrame({c: ol.slope_sign(df[c], n) for c in inds})
    if shift:
        sg = pd.DataFrame(np.roll(sg.values, shift, axis=0), index=sg.index, columns=sg.columns)
    ok = sg.notna().all(axis=1)
    pos, neg, zero = (sg > 0).sum(axis=1), (sg < 0).sum(axis=1), (sg == 0).sum(axis=1)
    fwd = df["close"].shift(-h) / df["close"] - 1
    out = pd.DataFrame({"pos": pos, "neg": neg, "zero": zero, "S": sg.sum(axis=1), "fwd": fwd,
                        "mom": ol.slope_sign(df["close"], n)})[ok]
    out = out[out.index.hour == 0].dropna()
    out["call"] = np.where(out["pos"] >= need, 1, np.where(out["neg"] >= need, -1, 0))
    return out


def shift_rank(df, n, h, need, real_hit):
    better = tot = 0
    for k in range(240, len(df) - 240, 7):
        st = ol.stats(calls_count(df, n, h, need, shift=k))
        if st["n"] < 10:
            continue
        tot += 1
        better += st["hit"] >= real_hit
    return (better + 1) / (tot + 1), tot


def main() -> None:
    for sym in ("BTCUSDT", "ETHUSDT"):
        df = ol.load(sym)
        print(f"\n=== {sym}")
        for n, h in ((72, 72), (72, 24)):
            c = calls_count(df, n, h, 3)
            old = c["S"].abs() >= 2
            new = c["call"] != 0
            zeros = c[c["zero"] > 0]
            st = ol.stats(c)
            lo, hi = ol.wilson(st["hit"], st["n"])
            rank, tot = shift_rank(df, n, h, 3, st["hit"])
            print(f"  {n}/{h}: дней {len(c)}, с нулевым наклоном {len(zeros)}; по сумме |S|≥2 выводов {int(old.sum())}, "
                  f"по счёту ≥3 ненулевых {int(new.sum())} (расходятся {int((old != new).sum())}); "
                  f"попадание {st['hit']:.1%} [{lo:.0%}–{hi:.0%}] n {st['n']}, ранг сдвига {rank:.3f} ({tot})")
        c = calls_count(df, 72, 72, 4)
        st = ol.stats(c)
        print(f"  все 4 ненулевых в одну сторону 72/72: выводов {st['n']}, попадание {st['hit']:.0%}")


if __name__ == "__main__":
    main()
