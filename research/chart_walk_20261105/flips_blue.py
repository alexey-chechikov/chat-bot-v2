"""Перекладка позицией по голубой 4ч: лонг над ней, шорт под ней. В сетке это было −$262 на участках, позицией на истории резко иначе, поэтому разбираю отдельно:
лонг и шорт, годы, без лучших сделок, контроль, соседи: подтверждение и запас от линии. Пороги соседей записаны до прогона."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_rules as er  # noqa: E402
import history_v1 as hv  # noqa: E402
import pos  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 100)


def flip_legs(a, conf, band):
    """На закрытии 4ч: conf закрытий подряд дальше band% за голубой — позиция в эту сторону. Иначе прежняя."""
    t, j, fc, fb = a["t"], a["j"], a["f_close"], a["f_B"]
    legs, side, cur, up, dn, jp = [], 0, None, 0, 0, -1
    for i in range(a["i0"], len(t)):
        if j[i] == jp:
            continue
        jp = j[i]
        d = (fc[i] / fb[i] - 1) * 100
        up = up + 1 if d > band else 0
        dn = dn + 1 if d < -band else 0
        new = 1 if up >= conf else (-1 if dn >= conf else side)
        if new != side:
            if cur is not None:
                legs.append((cur, i, side))
            cur, side = i, new
    if cur is not None:
        legs.append((cur, len(t) - 1, side))
    return legs


def frame(a, legs):
    d = pd.DataFrame(legs, columns=["i0", "i1", "s"])
    d["pnl"] = [pos.pnl(a, np.array([x]), np.array([y]), s)[0] for x, y, s in legs]
    d["per"] = pos.period_of(a["t"][d["i0"]])
    d["side"] = d["s"].map({1: "L", -1: "S"})
    d["год"] = pd.to_datetime(a["t"][d["i0"]], unit="s").year
    return d


def row(a, d, lab, coin):
    r = d["pnl"].to_numpy()
    st = pos.stats(r)
    s = np.sort(r)
    return {"монета": coin, "что": lab, "n": st["n"], "среднее_%": st["среднее_%"], "плюс_%": st["плюс_%"], "сумма_%": st["сумма_%"], "просадка_%": pos.max_dd(r), **{p: round(float(r[d["per"] == p].sum()), 1) for p in pos.PER}, "ди_низ": st["ди_низ"], "без_5_лучших_%": round(float(s[:-5].sum()), 1), "часов_медиана": float((d["i1"] - d["i0"]).median())}


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = er.prep(h1, h4, d1, fund)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = er.prep(h1e, h4e, d1e, fe)
    rows, ctl = [], []
    for x, coin in ((a, "BTC"), (e, "ETH")):
        for conf, band in ((1, 0), (2, 0), (3, 0), (1, 0.5), (1, 1), (1, 2), (2, 1), (2, 2)):
            d = frame(x, flip_legs(x, conf, band))
            lab = f"закрытий {conf}, запас {band}%"
            rows.append(row(x, d, lab, coin))
            rows.append(row(x, d[d["s"] == 1], lab + ", лонг", coin))
            rows.append(row(x, d[d["s"] == -1], lab + ", шорт", coin))
            if conf == 1 and band == 0:
                print(coin, "по годам", d.groupby("год")["pnl"].sum().round(0).to_dict())
                d["тип"] = "голубая"
                t = hv.group_table(x, d, "тип")
                t.insert(0, "монета", coin)
                ctl.append(t)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "flips_blue.csv", index=False)
    print(t.to_string(index=False))
    print(pd.concat(ctl).to_string(index=False))


if __name__ == "__main__":
    main()
