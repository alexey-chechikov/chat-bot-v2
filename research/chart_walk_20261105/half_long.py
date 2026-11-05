"""Замер следующего шага: вариант A, лонги вне описания половиной объёма (его слова «сделки в пол объёма»). Все ряды уже просмотрены, это оценка, а не проверка: новая проверка только на будущих данных."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import fetch_coins as fc  # noqa: E402
import ledger as lg  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import portrait_holdout2 as p2  # noqa: E402
import pos  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 60)


def curve(a, fm, legs):
    if not legs:
        z = np.zeros(len(a["c"]))
        return z, z
    eq, worst, _, _ = lg.equity(a, fm, [x[:5] for x in legs])
    return eq, worst


def row_for(coin, grp, a, fm):
    legs = w2.run(a, **w2.MAIN)
    is_out = [x[4] == 1 and not w2.in_portrait(a, x[0], 1) for x in legs]
    keep = [x for x, o in zip(legs, is_out) if not o]
    out = [x for x, o in zip(legs, is_out) if o]
    e1, w1 = curve(a, fm, keep)
    e2, w2_ = curve(a, fm, out)
    b, t = a["i0"], a["t"]
    cut = int(np.searchsorted(t, ph.CUT))
    row = {"ряд": coin, "группа": grp, "лонг_вне_n": len(out), "лонг_вне": round(e2[-1] / lg.NOTIONAL * 100)}
    for lab, w in (("A", 1.0), ("половина", 0.5)):
        eq, worst = e1 + w * e2, w1 + w * w2_
        row[lab] = round(eq[-1] / lg.NOTIONAL * 100)
        row[lab + "_дд"] = round(lg.drawdown(eq[b:], worst[b:], t[b:])[0] / lg.NOTIONAL * 100)
        row[lab + "_с2025"] = round((eq[-1] - eq[min(max(cut, b), len(eq) - 1)]) / lg.NOTIONAL * 100) if cut < len(eq) - 1 else 0
    return row


def main():
    rows = [row_for(c, "просмотрено", a, fm) for c, a, fm in ec.load_all()]
    for c in fc.COINS + p2.COINS2:
        a, fm = ph.load(c + "USDT")
        rows.append(row_for(c, "монеты", a, fm))
        print(rows[-1], flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "half_long.csv", index=False)
    print(d.to_string(index=False), flush=True)
    m = d[d["группа"] == "монеты"]
    print("20 монет: A", m["A"].sum(), "половина", m["половина"].sum(), "| с 2025 A", m["A_с2025"].sum(), "половина", m["половина_с2025"].sum(), "| просадка медиана A", m["A_дд"].median(), "половина", m["половина_дд"].median(), "| итог/просадка лучше на", int(((m["половина"] / m["половина_дд"].abs()) > (m["A"] / m["A_дд"].abs())).sum()), "из 20", flush=True)


if __name__ == "__main__":
    main()
