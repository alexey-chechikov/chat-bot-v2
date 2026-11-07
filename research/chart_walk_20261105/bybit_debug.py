"""Сверка с таблицей индикатора на его графике: линии на последнем закрытом часе, ATR входа шорта, расхождение pine_mirror и words2 на барах Bybit, и с какого первого бара графика получаются его 222 и +12.2%."""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import bybit_check as bc  # noqa: E402
import bybit_combos as bk  # noqa: E402
import pine_mirror as pm  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 200)


def main():
    a = bc.load_bybit()
    t = a["t"]
    frm = sm.T("2025-01-01")
    i = len(t) - 1
    print("последний час закрылся", sm.utc(t[i]))
    print("G Y R B4 B1h R1:", [round(float(a[k][i])) for k in ("f_G", "f_Y", "f_R", "f_B", "B1h", "R1")], "на скрине 76962 76695 77290 80126 78158–78161 77012–77020")
    print("под зелёной 4ч:", a["f_run_G"][i], "1ч под красной:", a["run_R"][i], "на скрине 7 и 26")
    st = {}
    legs = w2.run(a, **w2.MAIN26, stop_at=i, out=st)
    cur = st["cur"]
    print("открытая:", cur[3], sm.utc(t[cur[0]]), "вход", cur[1], "ATR", round(float(a["atr4"][cur[0]]), 1), "стоп", round(cur[1] + 2 * a["atr4"][cur[0]]), "тейк", round(cur[1] - 6 * a["atr4"][cur[0]]), "на скрине стоп 82301, тейк 74556", flush=True)

    ml = pm.run(a)
    print("words2 и mirror совпали:", pm.compare(legs, ml))
    print("mirror:", bk.total(a, ml, frm, True), "words2:", bk.total(a, [x[:6] for x in legs], frm, True), flush=True)
    diff = [(x[:6], y) for x, y in zip(legs, ml) if x[:6] != tuple(y)]
    print("разных сделок", len(diff), diff[:3], flush=True)

    rows = []
    starts = pd.date_range("2024-07-01", "2026-01-01", freq="MS")
    i00 = a["i0"]
    for g, at, x in itertools.product((True,), (True, False), (False, True)):
        for s in starts:
            a["i0"] = int(np.searchsorted(t, int(s.timestamp())))
            n, tot, sl, ss = bk.total(a, pm.run(a, optGate=g, optAtr=at, optX01=x), frm, True)
            rows.append({"2/6": at, "X01": x, "старт": s.strftime("%Y-%m"), "n": n, "итог": tot, "лонг": sl, "шорт": ss})
    a["i0"] = i00
    d = pd.DataFrame(rows)
    d["до_цели"] = (d["n"] - 222).abs() + (d["итог"] - 12.2).abs()
    print(d.sort_values("до_цели").head(12).drop(columns="до_цели").to_string(index=False), flush=True)
    print(d[(~d["2/6"] == False) & (d["X01"] == False)].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
