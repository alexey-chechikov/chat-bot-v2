"""Свод семейства И. Смотрит готовую таблицу. Второй шаг отбирается правилом из PREREG_win.md: на слое Простое+ не хуже кандидата по итогу и просадке на BTC и не теряет на ETH больше 5%.
Запуск: python -X utf8 fam_i_look.py [файл без расширения]"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 400, "display.max_colwidth", 46)
OUT = Path(__file__).parent / "out"


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "fam_i"
    d = pd.read_csv(OUT / f"{tag}.csv")
    cols = ["вариант", "BTC_n", "BTC_итог", "BTC_просадка", "BTC_с2025", "BTC_p1", "BTC_p2", "BTC_p3", "ETH_итог", "ETH_просадка", "ETH_с2025", "XRP_итог", "XRP_просадка", "XRP_с2025", "Bitstamp_итог", "Bitstamp_просадка"]
    for lay in ("постоянный", "плюс"):
        g = d[d["слой"] == lay]
        b = g[g["вариант"] == "база"].iloc[0]
        print(f"\n########## слой: {lay}; база BTC {b['BTC_итог']} / {b['BTC_просадка']}, ETH {b['ETH_итог']} / {b['ETH_просадка']}, XRP {b['XRP_итог']} / {b['XRP_просадка']}, Bitstamp {b['Bitstamp_итог']} / {b['Bitstamp_просадка']}")
        for fam, q in g.groupby("семейство", sort=False):
            if fam == "база":
                continue
            q = q.copy()
            q["о"] = q["BTC_итог"] / q["BTC_просадка"].abs().clip(lower=1)
            show = q.sort_values("о", ascending=False)
            print(f"--- {fam}: {len(q)}; не хуже базы по итогу и просадке на BTC: {int(((q['BTC_итог'] >= b['BTC_итог']) & (q['BTC_просадка'] >= b['BTC_просадка'])).sum())}; ещё и на ETH: {int(((q['BTC_итог'] >= b['BTC_итог']) & (q['BTC_просадка'] >= b['BTC_просадка']) & (q['ETH_итог'] >= b['ETH_итог']) & (q['ETH_просадка'] >= b['ETH_просадка'])).sum())}")
            print(show.head(30 if fam == "И10" else 7)[cols].to_string(index=False))
    g = d[d["слой"] == "плюс"]
    b = g[g["вариант"] == "база"].iloc[0]
    sel = g[(g["BTC_итог"] >= b["BTC_итог"]) & (g["BTC_просадка"] >= b["BTC_просадка"]) & (g["ETH_итог"] >= b["ETH_итог"] * 0.95) & (g["вариант"] != "база")]
    print("\n===== Второй шаг, правило из предрегистрации: на слое Простое+ не хуже по итогу и просадке на BTC, ETH минус не больше 5%")
    print(sel[cols].to_string(index=False) if len(sel) else "таких нет")


if __name__ == "__main__":
    main()
