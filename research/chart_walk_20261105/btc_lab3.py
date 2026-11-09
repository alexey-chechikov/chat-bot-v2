"""Шорт под жёлтой точно как в записке оператора по марту 2024 (разбор GPT 1cbcd0f, п.1): после основного лонга, при жёлтой выше зелёной. Только BTC, судья три периода и Bitstamp."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import plus as pl  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 60, "display.max_colwidth", 60)


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    V = [("Простое+", {})]
    for wt in (0.5, 1.0):
        V += [(f"cs {wt} без условий", dict(rules={"cs": wt})), (f"cs {wt} при Y>G", dict(rules={"cs": wt}, cs_yg=True))]
        for d in (3, 7, 14, 30):
            V.append((f"cs {wt} лонг закрылся ≤{d}д", dict(rules={"cs": wt}, cs_after=d)))
            V.append((f"cs {wt} лонг ≤{d}д и Y>G", dict(rules={"cs": wt}, cs_after=d, cs_yg=True)))
    rows = []
    for lab, kw in V:
        la = bl.run(a, lay, cut=bl.CUT, **kw)
        s = bl.row(a, f, la)
        sb = pl.stats(b, fb, bl.run(b, layb, **kw))
        n = sum(1 for x in la if x[5] == "S cs")
        v = sum(pl.unit(f, [x])[0][0] * x[7] for x in la if x[5] == "S cs")
        rows.append({"вариант": lab, "шортов": n, "их_сумма": round(float(v), 1), "итог": s["итог"], "просадка": s["просадка"], "с2025": s["с2025"], "18–21": s["18–21"], "22–07.24": s["22–07.24"], "08.24–26": s["08.24–26"], "Bitstamp": sb["итог"]})
    d = pd.DataFrame(rows)
    d.to_csv(bl.OUT / "btc_lab3.csv", index=False)
    print(d.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
