"""Выбор варианта для второй проверки: на 14 уже просмотренных рядах. Лонги все, шорты по описанию; выходы прошлые (A) или из записок 4–6 (B). Новые монеты второй партии здесь не участвуют."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_common as ec  # noqa: E402
import fetch_coins as fc  # noqa: E402
import ledger as lg  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 100)
CUT = cw.T("2025-01-01")
CFG = (("v1", None), ("A лонги все, шорт по описанию", {"gate": "shorts"}), ("B то же, выходы записок 4–6", {"gate": "shorts", "xl": True, "sflip": True, "sblue": True}), ("C только выходы записок", {"xl": True, "sflip": True, "sblue": True}))


def main():
    rows = []
    series = [(c, a, fm) for c, a, fm in ec.load_all()]
    for c in fc.COINS:
        a, fm = ph.load(c + "USDT")
        series.append((c, a, fm))
    for coin, a, fm in series:
        row = {"ряд": coin}
        for lab, kw in CFG:
            legs = wd.run(a) if kw is None else w2.run(a, **kw)
            r = np.array([w2.net(fm, x) for x in legs])
            s = np.array([x[4] for x in legs])
            t0 = a["t"][np.array([x[0] for x in legs])]
            eq, worst, _, _ = lg.equity(a, fm, [x[:5] for x in legs])
            b = a["i0"]
            k = lab[0] if lab != "v1" else "v1"
            row[f"{k}_итог"] = round(float(r.sum()))
            row[f"{k}_n"] = len(r)
            row[f"{k}_шорт"] = round(float(r[s == -1].sum()))
            row[f"{k}_25–26"] = round(float(r[t0 >= CUT].sum()))
            row[f"{k}_дд"] = round(lg.drawdown(eq[b:], worst[b:], a["t"][b:])[0] / lg.NOTIONAL * 100)
        rows.append(row)
        print(row, flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "portrait_pick.csv", index=False)
    print(d[["ряд", "v1_итог", "A_итог", "B_итог", "C_итог", "v1_шорт", "A_шорт", "B_шорт", "C_шорт"]].to_string(index=False), flush=True)
    print(d[["ряд", "v1_25–26", "A_25–26", "B_25–26", "C_25–26", "v1_дд", "A_дд", "B_дд", "C_дд", "v1_n", "A_n", "B_n", "C_n"]].to_string(index=False), flush=True)
    for k in ("A", "B", "C"):
        print(k, "сумма", d[f"{k}_итог"].sum(), "v1", d["v1_итог"].sum(), "| лучше v1 на рядах", int((d[f"{k}_итог"] > d["v1_итог"]).sum()), "из", len(d), "| шорт", d[f"{k}_шорт"].sum(), "v1", d["v1_шорт"].sum(), "| с 2025", d[f"{k}_25–26"].sum(), "v1", d["v1_25–26"].sum(), "| просадка медиана", d[f"{k}_дд"].median(), "v1", d["v1_дд"].median(), "| сделок к v1", round(d[f"{k}_n"].sum() / d["v1_n"].sum() * 100), "%", flush=True)


if __name__ == "__main__":
    main()
