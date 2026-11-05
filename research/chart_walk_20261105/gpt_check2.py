"""Дополнение к gpt_check.py. Записано ПОСЛЕ просмотра новых данных, поэтому части 1 и 2 — разбор, а не проверка:
1) стороны A отдельно и держание, те же 4 ряда; 2) вне рынка под голубой как следствие; 3) сигнал 04.04.2025 на двух площадках (п. 5 GPT); 4) сеточные эпизоды GPT на Binance через gridk."""
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

pd.set_option("display.width", 280, "display.max_columns", 40, "display.max_rows", 100)
EP = (("2025-02-17", "2025-02-20"), ("2025-02-22", "2025-02-25"), ("2025-03-21", "2025-03-24"), ("2025-04-17", "2025-04-21"))


def hold(a):
    c = a["c"][a["i0"]:]
    pct = (c / c[0] - 1) * 100
    return {"держание_%": round(float(pct[-1]), 1), "держание_просадка_%": round(float((pct - np.maximum.accumulate(pct)).min()), 1)}


def sides(a, fm, coin):
    tr = lg.trades_a(a)
    per = {"всё": (0, 2**40)}
    rows = []
    for lab, sel in (("обе", tr), ("лонг, под голубой вне рынка", [x for x in tr if x[4] == 1]), ("только шорт", [x for x in tr if x[4] == -1])):
        s = lg.summary(a, fm, sel, lab, coin, per)
        rows.append({k: s[k] for k in ("монета", "что", "n", "среднее_%", "плюс_%", "сумма_%", "фандинг_%", "просадка_часы_%", "под_водой_дней", "блок_низ_%", "блок_верх_%")} | hold(a))
    return rows


def signal_0404(a, h4, lab):
    t0 = cw.T("2025-04-04 04:00")
    i = int(np.searchsorted(h4.index.to_numpy(), t0))
    r = h4.iloc[i]
    print(lab, "4ч с", pos.utc_full(h4.index[i]), "закрытие", round(float(r["close"]), 2), "жёлтая", round(float(r["Y"]), 2), "закрытий подряд над жёлтой", int(r["run_Y"]))
    b = lg.trades_b(a, 0.5)
    for x in b:
        if abs(int(a["t"][x[0]]) - cw.T("2025-04-04 08:00")) <= 4 * 3600:
            print("  вход B50", pos.utc_full(a["t"][x[0]]), "выход", pos.utc_full(a["t"][x[1]]), "результат", round(float((x[3] / x[2] - 1) * 100 - pos.COST), 2), "%")


def grid_eps(m, fund):
    mk = cw.gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(), m["close"].to_numpy(), fund)
    rows = []
    for x, y in EP:
        i0, i1 = mk.idx([cw.T(x)]), mk.idx([cw.T(y)])
        lng, sht = float(mk.run(i0, i1, 1, cap=500.0)[0, 0]), float(mk.run(i0, i1, -1, cap=500.0)[0, 0])
        rows.append({"эпизод": f"{x}…{y}", "лонг_$": round(lng, 2), "шорт_$": round(sht, 2), "вместе_$": round(lng + sht, 2)})
    return pd.DataFrame(rows)


def main():
    m, h1, h4, d1, fund = cw.load()
    a, _ = gc.er.prep(h1, h4, d1, fund)
    print(grid_eps(m, fund).to_string(index=False), flush=True)
    del m
    m2, h1e, h4e, d1e, fe = pd.read_pickle(gc.er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = gc.er.prep(h1e, h4e, d1e, fe)
    bs, fbs = gc.load_bitstamp()
    xr, fx = gc.load_xrp()
    rows = []
    for x, f, coin in ((a, fund, "BTC 2018–26"), (e, fe, "ETH 2018–26"), (bs, fbs, "Bitstamp 2014–17"), (xr, fx, "XRP 2020–26")):
        rows += sides(x, lg.funding_marks(x, f), coin)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "gpt_check_sides.csv", index=False)
    print(t.to_string(index=False), flush=True)
    signal_0404(a, h4, "Binance")
    f = pd.read_csv(gc.HD / "bybit_btcusdt_1h.csv")
    f["ts"] = (f["ms"] // 1000).astype(np.int64)
    h4y = cw.md.add_ind(cw.md.bars(f, 14400))
    h4y["run_Y"] = cw.run_len(np.sign((h4y["close"] - h4y["Y"]).to_numpy()))
    by, _ = gc.load_bybit()
    signal_0404(by, h4y, "Bybit")


if __name__ == "__main__":
    main()
