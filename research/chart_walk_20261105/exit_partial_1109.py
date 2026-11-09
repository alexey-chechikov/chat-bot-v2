"""PREREG_trade_table_1109.md, слой 3: частичная фиксация половины на +k ATR (лимитка), остаток — по правилу. Запуск: python exit_partial_1109.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import words3_look as wl  # noqa: E402
from services.btc_signals import engine as en  # noqa: E402

MAKER = 0.016
CUT, CUT25 = 1672531200, 1735689600
pd.set_option("display.width", 220, "display.max_columns", 30)


def tp_leg(side, p0, p1):
    return side * (p1 / p0 - 1) * 100 - en.SC - MAKER * (p1 / p0)


def with_tp(a, e, k):
    """Итог позиции с фиксацией половины на +k ATR; None — уровень не достигнут (итог как в базе)."""
    p = e["pos"]
    s, i0, i1, p0, w = e["side"], p["entry_i"], e["i"], p["entry"], p["w"]
    lv = p0 + s * k * p["atr"]
    h, l, o = a["h"][i0 + 1:i1 + 1], a["l"][i0 + 1:i1 + 1], a["o"][i0 + 1:i1 + 1]
    hit = np.flatnonzero(h >= lv) if s == 1 else np.flatnonzero(l <= lv)
    if not len(hit):
        return None
    j = int(hit[0])
    tp = max(lv, float(o[j])) if s == 1 else min(lv, float(o[j]))
    x = e["px"]
    if e["tag"] == en.TAG432:
        return 0.5 * tp_leg(s, p0, tp) + 0.5 * en.leg_net(s, p0, x)
    res = w * en.FIRST * (0.5 * tp_leg(s, p0, tp) + 0.5 * en.leg_net(s, p0, x))
    if p["add_done"]:
        add_i = int(np.searchsorted(a["t"], p["add_t"]))
        if add_i <= i0 + 1 + j:
            res += w * en.ADD * (0.5 * tp_leg(s, p["add_px"], tp) + 0.5 * en.leg_net(s, p["add_px"], x))
        else:
            res += w * en.ADD * en.leg_net(s, p["add_px"], x)
    return res


def table(name, a, lay):
    ev, _ = en.simulate(a, lay)
    ev432, _, _ = en.simulate432(a)
    rows = []
    for E, typ_ks in ((ev, (3, 4, 6, 8)), (ev432, (2, 3, 4, 6, 8))):
        for e in [x for x in E if x["kind"] == "выход" and x["tag"] != en.CS]:
            r = {"ряд": name, "тип": e["tag"], "t0": e["pos"]["entry_t"], "база": e["res"]}
            for k in typ_ks:
                v = with_tp(a, e, k)
                r[f"k={k}"] = e["res"] if v is None else v
                r[f"дошло k={k}"] = v is not None
            rows.append(r)
    return pd.DataFrame(rows)


def main():
    a, _, _ = sc.load_coin("BTC")
    bs = [x for x in wl.series() if x[0] == "Bitstamp"][0]
    D = pd.concat([table("Binance", a, pl.layer(a)), table("Bitstamp", bs[1], pl.layer(bs[1]))], ignore_index=True)
    out = []
    for typ in ("над синей", "под синей", "432"):
        d = D[D["тип"] == typ]
        parts = {"2018–22": d[(d["ряд"] == "Binance") & (d["t0"] < CUT)], "2023–26": d[(d["ряд"] == "Binance") & (d["t0"] >= CUT)],
                 "с 2025": d[(d["ряд"] == "Binance") & (d["t0"] >= CUT25)], "Bitstamp": d[d["ряд"] == "Bitstamp"]}
        ks = [c for c in d.columns if c.startswith("k=") and d[c].notna().all()]
        for col in ["база"] + ks:
            row = {"тип": typ, "вариант": col}
            for nm, x in parts.items():
                row[nm] = round(float(x[col].sum()), 1)
            if col != "база":
                kk = col.split("=")[1]
                row["дошло, %"] = round(float(d[f"дошло k={kk}"].mean() * 100))
            out.append(row)
    R = pd.DataFrame(out)
    for typ in R["тип"].unique():
        base = R[(R["тип"] == typ) & (R["вариант"] == "база")].iloc[0]
        m = (R["тип"] == typ) & (R["вариант"] != "база")
        R.loc[m, "прошло"] = R[m].apply(lambda r: "да" if r["2018–22"] > base["2018–22"] and r["2023–26"] > base["2023–26"] and r["Bitstamp"] > base["Bitstamp"] else "нет", axis=1)
    print(R.to_string(index=False), flush=True)
    R.to_csv(Path(__file__).parent / "out" / "exit_partial_1109.csv", index=False)


if __name__ == "__main__":
    main()
