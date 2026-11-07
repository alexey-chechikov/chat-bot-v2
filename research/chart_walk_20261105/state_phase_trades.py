"""Где вход: итог сделок автомата по фазе входа на 24 рядах, два периода. Половина размера между голубыми и цель, пройденная до сигнала, в полном потоке. Ряды просмотрены, это замер."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import fetch_coins as fc  # noqa: E402
import gpt_r3_flow as gf  # noqa: E402
import ledger as lg  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import portrait_holdout2 as p2  # noqa: E402
import pos  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 200)
A = {"gate": "shorts"}
BEST = {**A, "s_stop": 2.0, "s_tp": 6.0, "s_after": "covered"}


def by_phase(coin, grp, a, fm, legs, lab):
    rows = []
    for x in legs:
        i0 = x[0]
        rows.append({"ряд": coin, "группа": grp, "книга": lab, "s": x[4], "фаза": a["phase"][i0], "период": "2025–26" if a["t"][i0] >= ph.CUT else "до 2025", "r": w2.net(fm, x)})
    return rows


def half_between(a, fm, legs):
    """Сделки с входом между голубыми половиной размера, остальные полным. Лонг вне описания здесь не трогаем: одно уменьшение за раз."""
    bet = [x for x in legs if a["phase"][x[0]] == "между голубыми"]
    rest = [x for x in legs if a["phase"][x[0]] != "между голубыми"]
    e1, e2 = lg.equity(a, fm, [x[:5] for x in rest]), lg.equity(a, fm, [x[:5] for x in bet])
    b, t = a["i0"], a["t"]
    cut = int(np.searchsorted(t, ph.CUT))
    out = {}
    for lab, w in (("полный", 1.0), ("половина", 0.5), ("ноль", 0.0)):
        eq, worst = e1[0] + w * e2[0], e1[1] + w * e2[1]
        out[f"{lab}_итог"] = round(eq[-1] / lg.NOTIONAL * 100, 1)
        out[f"{lab}_дд"] = round(lg.drawdown(eq[b:], worst[b:], t[b:])[0] / lg.NOTIONAL * 100, 1)
        out[f"{lab}_с2025"] = round((eq[-1] - eq[min(max(cut, b), len(eq) - 1)]) / lg.NOTIONAL * 100, 1) if cut < len(eq) - 1 else 0.0
    return out


def main():
    series = [("основные", k, a, f) for k, a, f in ec.load_all()]
    series += [("монеты", c, *ph.load(c + "USDT")) for c in fc.COINS + p2.COINS2]
    rows, hb, fl = [], [], []
    for grp, k, a, f in series:
        sm.add_state(a)
        legs = w2.run(a, **A)
        rows += by_phase(k, grp, a, f, legs, "A")
        hb.append({"ряд": k, "группа": grp, **half_between(a, f, legs)})
        for lab, kw in (("A", A), ("A без пройденной цели", {**A, "no_passed": True}), ("A+2/6", BEST), ("A+2/6 без пройденной цели", {**BEST, "no_passed": True})):
            fl.append(gf.row(k, grp, a, f, lab, w2.run(a, **kw)))
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "state_phase_trades.csv", index=False)
    t = d.groupby(["группа", "s", "фаза", "период"])["r"].agg(["size", "sum", "mean"]).round(2).unstack("период")
    print(t.to_string(), flush=True)
    per = d.groupby(["s", "фаза", "ряд"])["r"].sum().reset_index()
    print(per.groupby(["s", "фаза"])["r"].apply(lambda v: f"плюс на {(v > 0).sum()} из {len(v)}").to_string(), flush=True)
    h = pd.DataFrame(hb)
    h.to_csv(pos.OUT / "state_half_between.csv", index=False)
    print(h[h["группа"] == "основные"].drop(columns="группа").to_string(index=False), flush=True)
    m = h[h["группа"] == "монеты"]
    print("20 монет:", {c: round(m[c].sum()) if "дд" not in c else float(m[c].median()) for c in m.columns if c not in ("ряд", "группа")}, flush=True)
    z = pd.DataFrame(fl)
    z.to_csv(pos.OUT / "state_no_passed.csv", index=False)
    print(z[z["группа"] == "основные"].drop(columns="группа").to_string(index=False), flush=True)
    m = z[z["группа"] == "монеты"]
    base = {lab: g.set_index("ряд")["итог"] for lab, g in m.groupby("вариант")}
    print(m.groupby("вариант", sort=False).agg(n=("n", "sum"), итог=("итог", "sum"), с2025=("с2025", "sum"), дд=("просадка", "median")).round(1).to_string(), flush=True)
    print("без цели лучше A на", int((base["A без пройденной цели"] > base["A"]).sum()), "монетах", flush=True)


if __name__ == "__main__":
    main()
