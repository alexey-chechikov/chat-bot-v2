"""Две зацепки из разбивки убытков, полный поток с пересчётом входов на 24 рядах: вход только рядом с синей и стоп от входа. Простое правило, выход под красной и под зелёной. Все ряды просмотрены: замер, не проверка. Без выключателей поток обязан совпасть с прежним."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import pos  # noqa: E402
import words3 as w3  # noqa: E402
import words3_sweep as ws  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 200)
BASE = {"l_align": False, "s_align": False}


def variants():
    V = {}
    for ex in ("R", "G"):
        V[f"{ex} база"] = {**BASE, "l_exit": ex}
        for x in (2, 3, 4, 6):
            V[f"{ex} вход до {x} ATR от синей"] = {**BASE, "l_exit": ex, "max_blue": float(x)}
        for x in (2, 3, 4, 6):
            V[f"{ex} стоп {x} ATR"] = {**BASE, "l_exit": ex, "stop": float(x)}
    return V


def main():
    V = variants()
    rows = []
    for k, grp, a, f in ws.series():
        for lab, kw in V.items():
            rows.append({"ряд": k, "группа": grp, "вариант": lab, **w3.stats(a, f, w3.run(a, **kw))})
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "where_lose3.csv", index=False)
    out = []
    for lab, g in d.groupby("вариант", sort=False):
        g = g.set_index("ряд")
        m = g[g["группа"] == "монеты"]
        bl = d[(d["вариант"] == lab[0] + " база") & (d["группа"] == "монеты")].set_index("ряд")["итог"]
        row = {"вариант": lab}
        for c in ("BTC", "ETH", "Bitstamp", "XRP"):
            row[c] = f"{g.loc[c, 'итог']:+.0f}/{g.loc[c, 'просадка']:.0f}"
        row.update({"монеты": round(m["итог"].sum()), "лучше_базы": int((m["итог"] > bl.reindex(m.index)).sum()), "пр_мед": round(m["просадка"].median()), "с2025_BTC": g.loc["BTC", "с2025"], "с2025_ETH": g.loc["ETH", "с2025"], "с2025_мон": round(m["с2025"].sum()), "n_BTC": int(g.loc["BTC", "n"])})
        out.append(row)
    print(pd.DataFrame(out).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
