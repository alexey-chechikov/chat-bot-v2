"""Разбор провала PREREG_portrait.md: какая часть портрета держится на 10 новых монетах, а какая нет. Настройки не меняются, только разрез сделок v1 по сторонам. Записки 1–6 и выбор монет те же."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fetch_coins as fc  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 100)


def rows_for(c, a, fm):
    v1 = wd.run(a)
    row = {"монета": c}
    groups = {"Л_портрет": lambda x: x[4] == 1 and w2.in_portrait(a, x[0], 1), "Л_вне": lambda x: x[4] == 1 and not w2.in_portrait(a, x[0], 1), "Ш_портрет": lambda x: x[4] == -1 and w2.in_portrait(a, x[0], -1), "Ш_вне": lambda x: x[4] == -1 and not w2.in_portrait(a, x[0], -1),
              "Л_против": lambda x: x[4] == 1 and not w2.allow(a, x[0], 1, x[5], "against"), "Ш_против": lambda x: x[4] == -1 and not w2.allow(a, x[0], -1, x[5], "against")}
    for k, fn in groups.items():
        sel = [x for x in v1 if fn(x)]
        row[k] = round(sum(w2.net(fm, x) for x in sel))
        row[k + "_n"] = len(sel)
    return row


def main():
    rows = []
    for c in fc.COINS:
        a, fm = ph.load(c + "USDT")
        rows.append(rows_for(c, a, fm))
        print(rows[-1], flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "portrait_diag.csv", index=False)
    cols = ["Л_портрет", "Л_вне", "Ш_портрет", "Ш_вне", "Л_против", "Ш_против"]
    print(d[["монета"] + cols].to_string(index=False), flush=True)
    for k in cols:
        print(k, "сумма", d[k].sum(), "сделок", d[k + "_n"].sum(), "среднее", round(d[k].sum() / d[k + "_n"].sum(), 2), "плюс на монетах", int((d[k] > 0).sum()), "из 10", flush=True)


if __name__ == "__main__":
    main()
