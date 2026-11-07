"""Просчёт вариантов по запискам 06.11 на 4 рядах и 20 монетах, все ряды уже просмотрены: замер, а не проверка. Список вариантов полный, число просмотренных печатается. База сравнения — A + 2/6 (индикатор)."""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fetch_coins as fc  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import portrait_holdout2 as p2  # noqa: E402
import pos  # noqa: E402
import words2 as w2  # noqa: E402
import words3 as w3  # noqa: E402
import words3_look as wl  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
SIMPLE = {"l_align": False, "s_align": False}


def variants():
    V = {}
    for k, ex, la, sa in itertools.product((1, 2, 3), ("G", "Y", "R"), (False, "stack", True), (False, "stack", True)):
        V[f"k{k} выход {ex} лонг:{la} шорт:{sa}"] = dict(k=k, l_exit=ex, l_align=la, s_align=sa)
    for ex in ("G", "Y"):
        base = {**SIMPLE, "l_exit": ex}
        pre = f"{ex}|"
        V[pre + "к синей"] = {**base, "l_counter": True}
        for line, tg, w in itertools.product(("R", "Y"), ("B4", "B1"), (1.0, 0.5)):
            V[pre + f"шорт от {line} цель {tg} вес {w}"] = {**base, "s_up": line, "s_up_tgt": tg, "s_up_w": w}
        for x, part in itertools.product((3, 4, 5, 6, 8), (0.5, 1.0)):
            V[pre + f"отрыв {x} ATR доля {part}"] = {**base, "far": float(x), "part": part}
        for x in (2, 3, 4, 6):
            V[pre + f"добор после {x} ATR"] = {**base, "add": True, "add_far": float(x)}
        V[pre + "всё: к синей, от R, отрыв 4/0.5, добор 3"] = {**base, "l_counter": True, "s_up": "R", "far": 4.0, "part": 0.5, "add": True, "add_far": 3.0}
    return V


def series():
    out = [(k, "основные", a, f) for k, a, f in wl.series()]
    for c in fc.COINS + p2.COINS2:
        a, f = ph.load(c + "USDT")
        out.append((c, "монеты", a, f))
    return out


def main():
    V = variants()
    print("вариантов", len(V), flush=True)
    rows = []
    S = series()
    for k, grp, a, f in S:
        rows.append({"ряд": k, "группа": grp, "вариант": "A+2/6", **w3.stats(a, f, w2.run(a, **w2.MAIN26))})
        rows.append({"ряд": k, "группа": grp, "вариант": "A", **w3.stats(a, f, w2.run(a, **w2.MAIN))})
        for lab, kw in V.items():
            rows.append({"ряд": k, "группа": grp, "вариант": lab, **w3.stats(a, f, w3.run(a, **kw))})
        pd.DataFrame(rows).to_csv(pos.OUT / "w3_sweep.csv", index=False)
        print(k, "готово", flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "w3_sweep.csv", index=False)
    print("готово всё", flush=True)


if __name__ == "__main__":
    main()
