"""Какие окна BTC дать оператору на разметку: неразобранные участки 2024–26, где ответ больше всего меняет правила. Окно 28 дней, шаг 7. Настройки как у индикатора по умолчанию."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_r3_check as gr  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 200)
DAYS = 28


def main():
    a, fm, _ = sc.load_coin("BTC")
    legs = w2.run(a, **w2.MAIN26)
    t, c, h, l = a["t"], a["c"], a["h"], a["l"]
    eq = lg.equity(a, fm, [x[:5] for x in legs])[0] / lg.NOTIONAL * 100
    i0 = np.array([x[0] for x in legs])
    r = np.array([w2.net(fm, x) for x in legs])
    side = np.array([x[4] for x in legs])
    p = gr.paired(a, fm, [x for x in legs])
    tp = p["t0"].to_numpy()
    dx = (p["новый"] - p["старый"]).to_numpy()
    cnt = np.zeros(len(t))
    np.add.at(cnt, i0, 1)
    saw = pd.Series(cnt).rolling(240, min_periods=1).sum().to_numpy() >= 6
    loc = a["flat"] == 2
    between = a["phase"] == "между голубыми"
    notes = [(sm.T(x), sm.T(z)) for x, z, _ in sm.WINDOWS]
    rows = []
    for s in pd.date_range("2024-01-01", "2026-10-08", freq="7D"):
        x, z = int(s.timestamp()), int(s.timestamp()) + DAYS * 86400
        if any(x < n1 and z > n0 for n0, n1 in notes):
            continue
        w = (t >= x) & (t < z)
        k = np.where(w)[0]
        tr = (t[i0] >= x) & (t[i0] < z)
        pk = (tp >= x) & (tp < z)
        d = eq[k] - np.maximum.accumulate(eq[k])
        hi, lo = h[k].max(), l[k].min()
        rows.append({"с": s.strftime("%Y-%m-%d"), "по": pd.Timestamp(z, unit="s").strftime("%Y-%m-%d"), "счёт": round(eq[k[-1]] - eq[k[0]], 1), "просадка": round(d.min(), 1), "сделок": int(tr.sum()), "лонг": round(r[tr & (side == 1)].sum(), 1), "шорт": round(r[tr & (side == -1)].sum(), 1),
                     "диапазон_%": round(loc[w].mean() * 100), "пила_%": round(saw[w].mean() * 100), "между_%": round(between[w].mean() * 100), "ход_%": round((c[k[-1]] / c[k[0]] - 1) * 100, 1), "размах_%": round((hi / lo - 1) * 100, 1), "итог/размах": round(abs(c[k[-1]] - c[k[0]]) / (hi - lo), 2), "x01": round(dx[pk].sum(), 1), "x01_n": int(pk.sum())})
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "windows_pick.csv", index=False)
    show = ["с", "по", "счёт", "просадка", "сделок", "лонг", "шорт", "диапазон_%", "пила_%", "между_%", "ход_%", "размах_%", "итог/размах", "x01"]
    print("== худший счёт", flush=True)
    print(d.sort_values("счёт").head(8)[show].to_string(index=False), flush=True)
    print("== больше всего сделок", flush=True)
    print(d.sort_values("сделок", ascending=False).head(6)[show].to_string(index=False), flush=True)
    print("== мой флет: локальный диапазон", flush=True)
    print(d.sort_values("диапазон_%", ascending=False).head(6)[show].to_string(index=False), flush=True)
    print("== цена стоит, а серого мало: узкий размах, диапазон <15, пила <15", flush=True)
    print(d[(d["диапазон_%"] < 15) & (d["пила_%"] < 15)].sort_values("размах_%").head(6)[show].to_string(index=False), flush=True)
    print("== X01 дороже всего", flush=True)
    print(d.sort_values("x01").head(6)[show].to_string(index=False), flush=True)
    print("== X01 полезнее всего", flush=True)
    print(d.sort_values("x01", ascending=False).head(6)[show].to_string(index=False), flush=True)
    print("== лучший счёт", flush=True)
    print(d.sort_values("счёт", ascending=False).head(4)[show].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
