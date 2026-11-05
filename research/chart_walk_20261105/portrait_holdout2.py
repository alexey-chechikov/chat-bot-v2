"""Вторая проверка PREREG_portrait.md: скачивает вторую партию монет и делает один прогон. Настройки не меняются."""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import fetch_coins as fc  # noqa: E402
import ledger as lg  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 100)
COINS2 = ("BCH", "XLM", "ATOM", "ALGO", "FIL", "AAVE", "UNI", "NEAR", "VET", "XTZ")
CFG = (("v1", None), ("A", {"gate": "shorts"}), ("B", {"gate": "shorts", "xl": True, "sflip": True, "sblue": True}))
MIN_DAYS = 2 * 365 + 180


def one(a, fm, lab, kw):
    legs = wd.run(a) if kw is None else w2.run(a, **kw)
    r = np.array([w2.net(fm, x) for x in legs])
    s = np.array([x[4] for x in legs])
    t0 = a["t"][np.array([x[0] for x in legs])]
    eq, worst, _, _ = lg.equity(a, fm, [x[:5] for x in legs])
    b = a["i0"]
    return {f"{lab}_итог": round(float(r.sum())), f"{lab}_n": len(r), f"{lab}_лонг": round(float(r[s == 1].sum())), f"{lab}_шорт": round(float(r[s == -1].sum())), f"{lab}_с2025": round(float(r[t0 >= ph.CUT].sum())), f"{lab}_дд": round(lg.drawdown(eq[b:], worst[b:], a["t"][b:])[0] / lg.NOTIONAL * 100), f"{lab}_случ": lg.shift_rank(a, fm, [x[:5] for x in legs])["всё"]["лучше_%"]}


def portrait_split(a, fm):
    v1 = wd.run(a)
    out = {}
    for k, side, flag in (("Л_портрет", 1, True), ("Л_вне", 1, False), ("Ш_портрет", -1, True), ("Ш_вне", -1, False)):
        sel = [x for x in v1 if x[4] == side and w2.in_portrait(a, x[0], side) == flag]
        out[k] = round(sum(w2.net(fm, x) for x in sel))
        out[k + "_n"] = len(sel)
    return out


def main():
    rows, dropped = [], []
    for c in COINS2:
        sym = c + "USDT"
        try:
            fc.klines(sym)
            fc.funding(sym)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError, IndexError) as e:
            dropped.append((c, repr(e)))
            continue
        p = fc.DIR / f"{sym}_1h.csv"
        f = pd.read_csv(p)
        days = (f["ms"].iloc[-1] - f["ms"].iloc[0]) / 86400000
        if days < MIN_DAYS or f["ms"].iloc[-1] < (cw.T("2026-10-01") * 1000):
            dropped.append((c, f"ряд {days:.0f} дней, конец {pd.Timestamp(f['ms'].iloc[-1], unit='ms')}"))
            continue
        a, fm = ph.load(sym)
        row = {"монета": c, "с": pd.Timestamp(int(a["t"][a["i0"]]), unit="s").strftime("%m.%Y")}
        for lab, kw in CFG:
            row.update(one(a, fm, lab, kw))
        row.update(portrait_split(a, fm))
        rows.append(row)
        print(row, flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "portrait_holdout2.csv", index=False)
    print("выпали:", dropped, flush=True)
    print(d[["монета", "с", "v1_итог", "A_итог", "B_итог", "v1_шорт", "A_шорт", "B_шорт", "v1_с2025", "A_с2025", "B_с2025", "v1_дд", "A_дд", "B_дд", "v1_n", "A_n", "B_n", "v1_случ", "A_случ", "B_случ"]].to_string(index=False), flush=True)
    print(d[["монета", "Л_портрет", "Л_портрет_n", "Л_вне", "Л_вне_n", "Ш_портрет", "Ш_портрет_n", "Ш_вне", "Ш_вне_n"]].to_string(index=False), flush=True)
    n = len(d)
    print("\nКРИТЕРИИ, монет", n, flush=True)
    for k in ("A", "B"):
        print(k, "1 сумма", d[f"{k}_итог"].sum(), "v1", d["v1_итог"].sum(), "|2 лучше v1 на", int((d[f"{k}_итог"] > d["v1_итог"]).sum()), "из", n, "|3 шорты", d[f"{k}_шорт"].sum(), "v1", d["v1_шорт"].sum(), "|4 сделок", round(d[f"{k}_n"].sum() / d["v1_n"].sum() * 100), "% |5 с 2025", d[f"{k}_с2025"].sum(), "v1", d["v1_с2025"].sum(), "| просадка медиана", d[f"{k}_дд"].median(), "v1", d["v1_дд"].median(), flush=True)
    for k in ("Л_портрет", "Л_вне", "Ш_портрет", "Ш_вне"):
        print(k, "сумма", d[k].sum(), "сделок", d[k + "_n"].sum(), "среднее", round(d[k].sum() / d[k + "_n"].sum(), 2), "плюс на монетах", int((d[k] > 0).sum()), "из", n, flush=True)


if __name__ == "__main__":
    main()
