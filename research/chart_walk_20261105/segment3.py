"""Участок 3 (BTC 20.04–15.05.2025). Точки записки 3, крест голубой 4ч и дневной SMA100, правила на истории позициями (BTC и ETH):
P1 лонг над всеми линиями до закрепления под жёлтой 4ч; P2 короткий шорт над голубой 4ч: под красной 4ч, выход над зелёной 4ч и над голубой 1ч;
P3 лонг после возврата над жёлтой 4ч над голубыми до закрепления под красной 4ч; P4 крест голубой 4ч и SMA100. Записано до прогона, соседи перечислены в коде."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import pos  # noqa: E402
import rules  # noqa: E402
import segment1 as s1  # noqa: E402
import short_r1 as sr  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 200)


def with_runs(a, h4, d1):
    for c in ("run_R", "run_G"):
        a["f_" + c] = h4[c].to_numpy()[a["j"]]
    sma = d1["close"].rolling(100, min_periods=90).mean().to_numpy()
    k = np.searchsorted(d1["known"].to_numpy(), a["t"], side="right") - 1
    a["sma100"] = np.where(k >= 0, sma[np.clip(k, 0, None)], np.nan)
    return a


def machine(a, enter, exit_):
    """enter(i), exit_(i) проверяются на закрытии 4ч; → ноги (i0, i1)."""
    legs, cur, jp = [], None, -1
    for i in range(a["i0"], len(a["t"])):
        if a["j"][i] == jp:
            continue
        jp = a["j"][i]
        if cur is None:
            if enter(i):
                cur = i
        elif exit_(i):
            legs.append((cur, i))
            cur = None
    if cur is not None:
        legs.append((cur, len(a["t"]) - 1))
    return legs


def variants(a):
    fc, g, y, r, b, b1 = a["f_close"], a["f_G"], a["f_Y"], a["f_R"], a["f_B"], a["f_B1"]
    ry, rr, rg, rb1 = a["f_run_Y"], a["f_run_R"], a["f_run_G"], a["run_B1"]
    over_all = (fc > g) & (fc > y) & (fc > r) & (fc > b) & (fc > b1)
    over_blues = (fc > b) & (fc > b1)
    out = []
    for k in (1, 2, 3):
        out.append(("P1 лонг над всеми, выход под жёлтой", f"закрытий под жёлтой {k}", 1, lambda i, k=k: over_all[i], lambda i, k=k: ry[i] <= -k))
    out.append(("P1 лонг над всеми, выход под зелёной", "закрытий 2", 1, lambda i: over_all[i], lambda i: rg[i] <= -2))
    out.append(("P1 лонг над всеми, выход под красной", "закрытий 2", 1, lambda i: over_all[i], lambda i: rr[i] <= -2))
    for k in (1, 2):
        for kx in (1, 2):
            out.append(("P2 шорт над голубой 4ч под красной, выход над зелёной и над голубой 1ч", f"вход {k}, выход {kx}", -1,
                        lambda i, k=k: rr[i] <= -k and fc[i] > b[i], lambda i, kx=kx: rg[i] >= kx and rb1[i] >= 3))
    out.append(("P2 то же, выход только над зелёной", "вход 2, выход 1", -1, lambda i: rr[i] <= -2 and fc[i] > b[i], lambda i: rg[i] >= 1))
    out.append(("P2 то же, выход только над голубой 1ч", "вход 2", -1, lambda i: rr[i] <= -2 and fc[i] > b[i], lambda i: rb1[i] >= 3))
    out.append(("P2 то же, только если ещё над голубой 1ч", "вход 2, выход 1", -1, lambda i: rr[i] <= -2 and fc[i] > b[i] and fc[i] > b1[i], lambda i: rg[i] >= 1 and rb1[i] >= 3))
    for k in (1, 2, 3):
        out.append(("P3 лонг: свежий возврат над жёлтой над голубыми, выход под красной", f"закрытий под красной {k}", 1,
                    lambda i, k=k: ry[i] == 1 and over_blues[i], lambda i, k=k: rr[i] <= -k))
    out.append(("P3 то же, выход под жёлтой", "закрытий 2", 1, lambda i: ry[i] == 1 and over_blues[i], lambda i: ry[i] <= -2))
    bs = a["sma100"]
    out.append(("P4 лонг: голубая 4ч над SMA100 дн", "пока так", 1, lambda i: b[i] > bs[i], lambda i: b[i] < bs[i]))
    out.append(("P4 шорт: голубая 4ч под SMA100 дн", "пока так", -1, lambda i: b[i] < bs[i], lambda i: b[i] > bs[i]))
    return out


def table(a, coin):
    rows = []
    for nm, var, side, en, ex in variants(a):
        legs = machine(a, en, ex)
        if len(legs) < 5:
            continue
        d = sr.frame(a, legs, side)
        rows.append({"монета": coin, "правило": nm, "вариант": var, **{k: v for k, v in sr.row_of(a, d, "").items() if k != "что"}, "часов_медиана": float((d["i1"] - d["i0"]).median())})
    return pd.DataFrame(rows)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a = rules.prepare(h1, h4)
    t = a["t"]
    f = np.zeros(len(t))
    np.add.at(f, np.clip(np.searchsorted(t, fund.index.to_numpy(), side="left"), 0, len(t) - 1), fund.to_numpy())
    a["F"] = np.cumsum(f) * 100
    a["atr4"] = h4["atr"].to_numpy()[a["j"]]
    a["R1"], a["B1h"], a["run_B1"] = h1["R"].to_numpy(), h1["B"].to_numpy(), h1["run_B"].to_numpy()
    a["i0"] = int(np.searchsorted(t, cw.T("2018-01-01")))
    a = with_runs(a, h4, d1)
    # крест голубых
    w = (t >= cw.T("2025-04-01")) & (t <= cw.T("2025-05-20"))
    x = np.sign(a["f_B"] - a["sma100"])
    for i in np.where(w & (np.r_[0, np.diff(x)] != 0))[0]:
        print("голубая 4ч через SMA100 дн:", cw.utc(int(t[i])), "голубая", round(float(a["f_B"][i])), "SMA100", round(float(a["sma100"][i])), "цена", round(float(a["c"][i])))
    x = np.sign(a["B1h"] - a["f_B"])
    for i in np.where(w & (np.r_[0, np.diff(x)] != 0))[0]:
        print("голубая 1ч через голубую 4ч:", cw.utc(int(t[i])), round(float(a["B1h"][i])), round(float(a["f_B"][i])))
    # 4ч-таблица участка
    s = h4[(h4["known"] > cw.T("2025-05-01")) & (h4["known"] <= cw.T("2025-05-16"))].copy()
    s.insert(0, "закр", [cw.utc(int(v)) for v in s["known"]])
    print(s[["закр", "high", "low", "close", "G", "Y", "R", "B", "B1", "d_G", "d_Y", "d_R", "d_Bo", "width3", "run_G", "run_Y", "run_R", "vol_vs30"]].round(1).iloc[::2].to_string(index=False))
    h1c = h1[(h1["known"] > cw.T("2025-05-03")) & (h1["known"] <= cw.T("2025-05-08"))]
    first = h1c[(h1c["run_B"] >= 1)].iloc[:1]
    print("1ч над голубой первые:", [cw.utc(int(v)) for v in first["known"]])
    # история
    tb = table(a, "BTC")
    print(tb.drop(columns=["монета"]).to_string(index=False))
    tb.to_csv(pos.OUT / "segment3_rules_BTC.csv", index=False)
    e = sr.tb2.eth_arrays()
    m2, h1e, h4e, d1e, fe = pd.read_pickle(sr.tb2.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e["run_B1"] = h1e["run_B"].to_numpy()
    e = with_runs(e, h4e, d1e)
    te = table(e, "ETH")
    te.to_csv(pos.OUT / "segment3_rules_ETH.csv", index=False)
    print(te[["правило", "вариант", "n", "среднее_%", "сумма_%", "просадка_%", "A_%", "B_%", "C_%", "лучше_случайного_%"]].to_string(index=False))
    # сделки правил на участке
    for nm, var, side, en, ex in variants(a):
        if (nm.startswith("P1 лонг над всеми, выход под жёлтой") and var.endswith("2")) or (nm.startswith("P2 шорт") and var == "вход 2, выход 1") or (nm.startswith("P3 лонг: свежий") and var.endswith("2")):
            d = sr.frame(a, machine(a, en, ex), side)
            g = d[(t[d["i0"]] >= cw.T("2025-03-15")) & (t[d["i0"]] < cw.T("2025-05-20"))]
            print(nm, var)
            print(pd.DataFrame({"вход": [cw.utc(int(t[i])) for i in g["i0"]], "выход": [cw.utc(int(t[i])) for i in g["i1"]], "цена_вх": g["p0"].round(), "цена_вых": g["p1"].round(), "итог_%": g["pnl"].round(2)}).to_string(index=False))


if __name__ == "__main__":
    main()
