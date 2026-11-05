"""Дополнение к A и C (дописано после первого прогона, это уже выбор): соседи тейка «доля пути» для L1, проверка на ETH (другая монета, правила те же),
шорт от голубой целиком (метка blue>G ставится только выжившим, поэтому отдельно она заглядывает вперёд), шорт от голубой с входом только после закрытия под зелёной,
перекладка в шорт над и под голубыми, зеркало L1 под голубой не считается: это шорт к голубой сверху."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import history_v1 as hv  # noqa: E402
import pos  # noqa: E402
import rules  # noqa: E402
import tp_blue as tb  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 200)
ETH_PKL = Path("/private/tmp/claude-501/-Users-alexeychechikov/85655d8a-c366-454b-bd04-314adf4588cf/scratchpad/mr/bars_5cee39b1d0e5b669_d02bb3475692fe5d.pkl")
tb.FR = [0.25, 0.33, 0.4, 0.5, 0.6, 0.67, 0.75, 1.0]


def l1_table(a, label):
    t = a["t"]
    x = tb.make_arrays(a, 1)
    ev = tb.events(a, 1, "L1", x)
    per = pos.period_of(t[ev])
    room = (x["B4p"] / x["c"] - 1) * 100
    pool_all = np.where((room >= tb.ROOM) & (np.arange(len(room)) >= a["i0"]))[0]
    rng = np.random.default_rng(20261105)
    pool_s = np.sort(rng.choice(pool_all, size=min(6000, len(pool_all)), replace=False))
    pp = pos.period_of(t[pool_s])
    rr = pd.DataFrame([tb.run_one(x, a, i, 1) for i in ev])
    u = rr["недолёт_%"].to_numpy()
    print(label, "L1: n", len(ev), "дошли до голубой", round(float((u <= 0).mean() * 100), 1), {f"≤{y}": round(float((u <= y).mean() * 100), 1) for y in (5, 3, 2, 1, 0.5)})
    rows = []
    for stop in ("S0", "S1", "S2", "S3"):
        real = tb.outcomes(a, x, ev, 1, stop)
        ctrl = tb.outcomes(a, x, pool_s, 1, stop)
        for nm, v in real.items():
            ok = ~np.isnan(v)
            if ok.sum() < 20:
                continue
            row = {"монета": label, "стоп": stop, "тейк": nm, "n": int(ok.sum()), "среднее_%": round(float(v[ok].mean()), 3), "плюс_%": round(float((v[ok] > 0).mean() * 100), 1), "сумма_%": round(float(v[ok].sum()), 1), "просадка_%": pos.max_dd(v[ok])}
            tot_ctl = np.zeros(999)
            tot_real = 0.0
            for p in pos.PER:
                vp = v[ok & (per == p)]
                row[f"{p}_%"] = round(float(vp.sum()), 1)
                cp = ctrl[nm][(pp == p) & ~np.isnan(ctrl[nm])]
                if len(vp) and len(cp):
                    tot_ctl += cp[rng.integers(0, len(cp), size=(999, len(vp)))].sum(axis=1)
                    tot_real += vp.sum()
            row["лучше_случайного_%"] = round(float((tot_ctl < tot_real).mean() * 100), 1)
            row["случайные_медиана_%"] = round(float(np.median(tot_ctl)), 1)
            se = v[ok].std(ddof=1) / np.sqrt(ok.sum())
            row["ди_низ"] = round(float(v[ok].mean() - 1.96 * se), 3)
            rows.append(row)
    return pd.DataFrame(rows)


def eth_arrays():
    m, h1, h4, d1, fund = pd.read_pickle(ETH_PKL)
    del m
    h1f, h4f = cw.features(h1, h4, 1), cw.features(h4, h1, 4)
    a = rules.prepare(h1f, h4f)
    t = a["t"]
    f = np.zeros(len(t))
    idx = np.clip(np.searchsorted(t, fund.index.to_numpy(), side="left"), 0, len(t) - 1)
    np.add.at(f, idx, fund.to_numpy())
    a["F"] = np.cumsum(f) * 100
    a["atr4"] = h4f["atr"].to_numpy()[a["j"]]
    a["R1"], a["B1h"] = h1f["R"].to_numpy(), h1f["B"].to_numpy()
    a["i0"] = int(np.searchsorted(t, cw.T("2018-01-01")))
    return a


def main():
    a, h1, h4, d1, fund = pos.load()
    t_btc = l1_table(a, "BTC")
    t_btc.to_csv(pos.OUT / "tp_blue_L1_BTC.csv", index=False)
    show = ["монета", "стоп", "тейк", "n", "среднее_%", "плюс_%", "сумма_%", "просадка_%", "A_%", "B_%", "C_%", "ди_низ", "лучше_случайного_%", "случайные_медиана_%"]
    print(t_btc[t_btc["тейк"].str.startswith("f") | t_btc["тейк"].isin(["y3", "y1.5", "без_тейка"])][show].to_string(index=False))
    t_eth = l1_table(eth_arrays(), "ETH")
    t_eth.to_csv(pos.OUT / "tp_blue_L1_ETH.csv", index=False)
    print(t_eth[t_eth["тейк"].isin(["без_тейка", "y3", "y1.5", "y0", "f0.4", "f0.5", "f0.6"])][show].to_string(index=False))
    # шорт от голубой целиком и с входом только после закрытия под зелёной
    t_end = int(a["t"][-1])
    d = hv.legs_frame(a, rules.run(a, hv.T0, t_end))
    blue = d[d["tag"].isin(["blue", "blue>G"])]
    print("шорт от голубой целиком:", pos.stats(blue["pnl"].to_numpy()), {p: round(float(blue.loc[blue["per"] == p, "pnl"].sum()), 1) for p in pos.PER})
    real = {p: float(blue.loc[blue["per"] == p, "pnl"].sum()) for p in pos.PER}
    print("контроль", pos.rank_row(real, pos.control_fixed(a, blue["i0"].to_numpy(), (blue["i1"] - blue["i0"]).to_numpy(), -1))["всё"])
    # перекладка в шорт и лонг по стороне голубых на входе
    fc, fb, fb1 = a["f_close"], a["f_B"], a["f_B1"]
    for side, tag in (("S", "flip"), ("L", "flip"), ("L", "fresh"), ("S", "reshort")):
        g = d[(d["side"] == side) & (d["tag"] == tag)]
        i0 = g["i0"].to_numpy()
        under = (fc[i0] < fb[i0]) & (fc[i0] < fb1[i0])
        over = (fc[i0] > fb[i0]) & (fc[i0] > fb1[i0])
        for nm, m in (("под обеими", under), ("над обеими", over), ("между", ~under & ~over)):
            gg = g[m]
            if len(gg) == 0:
                continue
            rr = {p: float(gg.loc[gg["per"] == p, "pnl"].sum()) for p in pos.PER}
            rk = pos.rank_row(rr, pos.control_fixed(a, gg["i0"].to_numpy(), (gg["i1"] - gg["i0"]).to_numpy(), int(gg["s"].iloc[0])))
            print(side, tag, nm, "n", len(gg), "среднее", round(float(gg["pnl"].mean()), 3), "сумма", round(float(gg["pnl"].sum()), 1), {p: rk[p]["сумма_%"] for p in pos.PER}, "лучше случайного", rk["всё"]["лучше_случайного_%"], "случайные", rk["всё"]["случайные_медиана_%"])


if __name__ == "__main__":
    main()
