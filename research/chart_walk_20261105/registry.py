"""Реестр просмотренных вариантов (разбор GPT 5d9e542, п. 5): все строки таблиц out/*.csv, где считался результат варианта. Сводка — сколько на самом деле, а не «около 350»."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "out"
RES = ("сумма_%", "итог_$", "всего_%", "A_сумма", "A_%", "A")


def main():
    rows, parts = [], []
    for p in sorted(OUT.glob("*.csv")):
        if p.name.startswith(("registry", "gpt_check")):             # проверка разбора GPT — заранее записанные правила, не отбор
            continue
        d = pd.read_csv(p)
        if not any(c in d.columns for c in RES) or "n" not in d.columns and "сделок" not in d.columns:
            rows.append({"таблица": p.name, "вариантов": 0, "считается": "нет, описание"})
            continue
        rows.append({"таблица": p.name, "вариантов": len(d), "считается": "да"})
        x = d.copy()
        x.insert(0, "таблица", p.name)
        parts.append(x)
    t = pd.DataFrame(rows)
    pd.concat(parts, ignore_index=True).to_csv(OUT / "registry_all.csv", index=False)
    t.to_csv(OUT / "registry_summary.csv", index=False)
    print(t.to_string(index=False))
    print("всего вариантов:", int(t["вариантов"].sum()))


if __name__ == "__main__":
    main()
