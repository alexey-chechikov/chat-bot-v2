"""Записки оператора 08.11: сверка 123/+34.6 на Bybit и почему не было перезахода в шорт 13–23.11.2025 и около 03.02.2026."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import bybit_check as bc  # noqa: E402
import pine_mirror_pyr as pm  # noqa: E402
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
from services.btc_signals import engine as en  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 200)


def utc(t):
    return pd.Timestamp(int(t), unit="s").strftime("%d.%m.%y %H:%M")


def trades(a, ev, a0, a1):
    rows = []
    for e in ev:
        if e["kind"] == "выход" and sm.T(a0) <= e["pos"]["entry_t"] < sm.T(a1):
            p = e["pos"]
            rows.append({"вход": utc(p["entry_t"]), "выход": utc(e["t"]), "сделка": ("L " if e["side"] == 1 else "S ") + e["tag"], "цена входа": round(p["entry"]), "выхода": round(e["px"]), "итог": round(e["res"], 2), "почему": e["why"], "добор": "да" if p["add_done"] else ""})
    return pd.DataFrame(rows)


def states(a, lay, ev, a0, a1):
    rk, W = lay
    side = np.zeros(len(a["t"]), int)
    cur, last = 0, 0
    for e in ev:
        side[last:e["i"]] = cur
        cur = e["side"] if e["kind"] == "вход" else (0 if e["kind"] == "выход" else cur)
        last = e["i"]
    side[last:] = cur
    new = np.r_[True, a["j"][1:] != a["j"][:-1]]
    idx = np.flatnonzero(new & (a["t"] >= sm.T(a0)) & (a["t"] < sm.T(a1)))
    rows = []
    for i in idx:
        rows.append({"4ч": utc(a["t"][i]), "закрытие": round(a["c"][i]), "синяя": round(a["f_B"][i]), "над синей": bool(a["f_close"][i] > a["f_B"][i]), "зел": int(a["f_run_G"][i]), "жёл": int(a["f_run_Y"][i]), "кр": int(a["f_run_R"][i]),
                     "ранг": round(float(rk[i]), 2), "шорт можно": not rk[i] > en.RANK_TH, "позиция": {1: "лонг", -1: "шорт", 0: ""}[int(side[i])]})
    return pd.DataFrame(rows)


def main():
    by = bc.load_bybit()
    lby = pl.layer(by)
    frm = sm.T("2025-01-01")
    print("Bybit 4ч с 01.01.2025:", pm.expect(by, pm.run(by, lby, h4=True), frm), flush=True)
    out = pm.run(by, lby, h4=True)
    for x in [q for q in out if by["t"][q[0]] >= sm.T("2026-10-25")]:
        print("  Bybit сделка", utc(by["t"][x[0]]), "→", utc(by["t"][x[1]]), "сторона", x[2], "итог", round(x[3], 2), flush=True)

    a, _, _ = sc.load_coin("BTC")
    lay = pl.layer(a)
    ev, pos = en.simulate(a, lay)
    for lab, a0, a1 in (("окно 7 и ноябрь 2025", "2025-10-20", "2025-12-06"), ("январь–февраль 2026", "2026-01-20", "2026-02-16"), ("окно 10, апрель 2026", "2026-04-05", "2026-05-01"), ("окно 5, сентябрь 2023", "2023-08-20", "2023-10-01")):
        print(f"== сделки системы (Binance): {lab}", flush=True)
        print(trades(a, ev, a0, a1).to_string(index=False), flush=True)
    for lab, a0, a1 in (("13–24.11.2025", "2025-11-12", "2025-11-25"), ("28.01–06.02.2026", "2026-01-28", "2026-02-07")):
        print(f"== состояние на закрытиях 4ч: {lab}", flush=True)
        print(states(a, lay, ev, a0, a1).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
