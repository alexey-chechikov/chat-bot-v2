"""Какие окна дать оператору на разбор: где автомат «слова» теряет и зарабатывает больше всего за 35 дней, плюс счёт выходов по причинам. Окна после его скринов (с 15.05.2025) он ещё не видел."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 100)
L = 35


def net(fm, x):
    m, f, u = lg.trade_cash(fm, x[:5])
    return (m - f - u) / lg.NOTIONAL * 100


def pick(eq, t, x, z, worst, k):
    """Непересекающиеся окна по 35 дней с наибольшим падением или ростом кривой."""
    d0 = np.arange(int(np.searchsorted(t, cw.T(x))), int(np.searchsorted(t, cw.T(z))) - L * 24, 24)
    ch = (eq[d0 + L * 24] - eq[d0]) / lg.NOTIONAL * 100
    out = []
    for q in (np.argsort(ch) if worst else np.argsort(-ch)):
        if all(abs(d0[q] - o) >= L * 24 for o in out):
            out.append(d0[q])
        if len(out) == k:
            break
    return out


def describe(a, fm, legs, i, group):
    t = a["t"]
    e = i + L * 24
    inw = [x for x in legs if i <= x[0] < e]
    long_, short_ = [x for x in inw if x[4] == 1], [x for x in inw if x[4] == -1]
    tags = {}
    for x in inw:
        k = ("L " if x[4] == 1 else "S ") + x[5]
        tags[k] = tags.get(k, 0.0) + net(fm, x)
    worst = sorted(tags.items(), key=lambda v: v[1])
    return {"группа": group, "с": pos.utc_full(t[i])[:10], "по": pos.utc_full(t[e])[:10], "цена": f"{a['c'][i]:.0f}→{a['c'][e]:.0f}", "мин": round(float(a["l"][i:e].min())), "макс": round(float(a["h"][i:e].max())),
            "над_голубой_%": round(float((a["f_close"][i:e] > a["f_B"][i:e]).mean() * 100)), "сделок": len(inw), "лонг": round(sum(net(fm, x) for x in long_), 1), "шорт": round(sum(net(fm, x) for x in short_), 1), "итог": round(sum(net(fm, x) for x in inw), 1),
            "хуже": f"{worst[0][0]} {worst[0][1]:.1f}" if worst else "", "лучше": f"{worst[-1][0]} {worst[-1][1]:.1f}" if worst else ""}


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    fm = lg.funding_marks(a, fund)
    legs = wd.run(a)
    eq, _, _, _ = lg.equity(a, fm, [x[:5] for x in legs])
    t = a["t"]
    rows = []
    for i in pick(eq, t, "2025-05-15", "2026-11-06", True, 4):
        rows.append(describe(a, fm, legs, i, "новые, потери"))
    for i in pick(eq, t, "2025-05-15", "2026-11-06", False, 2):
        rows.append(describe(a, fm, legs, i, "новые, заработок"))
    for i in pick(eq, t, "2021-01-01", "2022-01-01", True, 1):
        rows.append(describe(a, fm, legs, i, "2021, потери"))
    for i in pick(eq, t, "2022-01-01", "2023-01-01", False, 1):
        rows.append(describe(a, fm, legs, i, "2022, заработок"))
    w = pd.DataFrame(rows)
    w.to_csv(pos.OUT / "words_windows.csv", index=False)
    print(w.to_string(index=False))
    d = pd.DataFrame([{"сторона": "L" if x[4] == 1 else "S", "тип": x[5], "причина": x[6].split(":")[0], "r": net(fm, x)} for x in legs])
    print(d.groupby(["сторона", "причина"])["r"].agg(["size", "sum", "mean"]).round(2).to_string())
    print(d.groupby(["сторона", "тип"])["r"].agg(["size", "sum", "mean"]).round(2).to_string())


if __name__ == "__main__":
    main()
