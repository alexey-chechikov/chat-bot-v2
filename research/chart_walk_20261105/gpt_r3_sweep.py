"""Соседи стопа и тейка шорта и стопа лонга на варианте A, полный поток. Контексты выхода X01 на всех 24 рядах, цели, пройденные до сигнала, и новый контроль сдвигами. Ряды просмотрены, правило 2/6 записано до прогона на монетах."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import fetch_coins as fc  # noqa: E402
import gpt_r3_check as gr  # noqa: E402
import gpt_r3_flow as gf  # noqa: E402
import ledger as lg  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import portrait_holdout2 as p2  # noqa: E402
import pos  # noqa: E402
import state_map as sm  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 300)
A = {"gate": "shorts"}
NOF = 1e9
CELLS = {f"шорт {s}/{t}": {**A, "s_stop": s, "s_tp": t, "s_after": "covered"} for s in (1.5, 2.0, 2.5, 3.0, 4.0) for t in (4.0, 6.0, 8.0, 10.0)}
CELLS |= {f"шорт стоп {s}": {**A, "s_stop": s, "s_tp": NOF, "s_after": "covered"} for s in (2.0, 3.0)}
CELLS |= {f"шорт тейк {t}": {**A, "s_stop": NOF, "s_tp": t, "s_after": "covered"} for t in (6.0, 8.0)}
CELLS |= {f"лонг стоп {s}": {**A, "l_stop": s} for s in (2.0, 3.0, 4.0, 6.0, 8.0)}


def spec(coin, a, fm):
    """Цель, пройденная до сигнала, и положение цены: сделки автомата v1."""
    sm.add_state(a)
    rows = []
    for x in wd.run(a):
        i0, _, p0, _, s, tag, _ = x
        ph_ = a["phase"][i0]
        passed = s == 1 and tag == "к голубой" and p0 >= a["B4p"][i0 + 1 if i0 + 1 < len(a["B4p"]) else i0] * 0.995
        b4 = "растёт" if a["s_b4"][i0] > sm.FLAT_B4 else ("падает" if a["s_b4"][i0] < -sm.FLAT_B4 else "плоская")
        rows.append({"ряд": coin, "s": s, "тег": tag, "пройдена": passed, "b4": b4, "фаза": ph_, "r": w2.net(fm, x)})
    return rows


def main():
    series = ec.load_all()
    coins = [(c, *ph.load(c + "USDT")) for c in fc.COINS + p2.COINS2]
    print("== новый контроль сдвигами: нулевой сдвиг = учёт", flush=True)
    for k, a, f in series:
        for lab, legs in (("v1", wd.run(a)), ("A", w2.run(a, **A)), ("A+2/6", w2.run(a, **A, s_stop=2.0, s_tp=6.0, s_after="covered"))):
            s = lg.shift_rank(a, f, [x[:5] for x in legs])
            print(k, lab, "сумма", s["всё"]["сумма_%"], "лучше", s["всё"]["лучше_%"], "| лонг", s["лонг"]["лучше_%"], "| шорт", s["шорт"]["сумма_%"], s["шорт"]["лучше_%"], flush=True)
    rows = []
    for k, a, f in series:
        rows.append(gf.row(k, "основные", a, f, "A", w2.run(a, **A)))
        for lab, kw in CELLS.items():
            rows.append(gf.row(k, "основные", a, f, lab, w2.run(a, **kw)))
    for k, a, f in coins:
        rows.append(gf.row(k, "монеты", a, f, "A", w2.run(a, **A)))
        for lab, kw in CELLS.items():
            rows.append(gf.row(k, "монеты", a, f, lab, w2.run(a, **kw)))
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "gpt_r3_sweep.csv", index=False)
    m = d[d["группа"] == "монеты"]
    base = m[m["вариант"] == "A"].set_index("ряд")["итог"]
    main4 = d[d["группа"] == "основные"].pivot(index="вариант", columns="ряд", values="итог")[["BTC", "ETH", "Bitstamp", "XRP"]].round()
    out = []
    for lab, g in m.groupby("вариант", sort=False):
        out.append({"вариант": lab, "монеты_итог": round(g["итог"].sum()), "шорт": round(g["шорт"].sum()), "лонг": round(g["лонг"].sum()), "с2025": round(g["с2025"].sum()), "просадка_медиана": g["просадка"].median(), "лучше_A": int((g.set_index("ряд")["итог"] > base).sum()), **main4.loc[lab].to_dict()})
    print(pd.DataFrame(out).to_string(index=False), flush=True)
    print("== X01 на тех же входах: контекст GPT на 24 рядах", flush=True)
    rows = []
    for k, a, f in series + coins:
        p = gr.paired(a, f, wd.run(a))
        new = p["t0"] >= gr.OLD
        for lab, m_ in (("к B4, B4 не растёт, G<Y<R", (p["тип"] == "к голубой") & ~p["рост_B4"] & p["вниз"]), ("к B4, остальные", (p["тип"] == "к голубой") & ~(~p["рост_B4"] & p["вниз"])), ("портрет", p["портрет"]), ("над голубыми вне портрета", (p["тип"] != "к голубой") & ~p["портрет"])):
            for per, mm in (("до 2025", ~new), ("2025–26", new)):
                g = p[m_ & mm]
                rows.append({"ряд": k, "контекст": lab, "период": per, "n": len(g), "разница": (g["новый"] - g["старый"]).sum(), "старый": g["старый"].sum(), "новый": g["новый"].sum()})
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "gpt_r3_paired24.csv", index=False)
    ag = t.groupby(["контекст", "период"]).agg(рядов=("n", lambda v: int((v > 0).sum())), n=("n", "sum"), старый=("старый", "sum"), новый=("новый", "sum"), разница=("разница", "sum")).round(1)
    ag["лучше_рядов"] = t[t["n"] > 0].groupby(["контекст", "период"])["разница"].apply(lambda v: int((v > 0).sum()))
    print(ag.to_string(), flush=True)
    print("== пропуски описания в v1, 4 ряда", flush=True)
    rows = []
    for k, a, f in series:
        rows += spec(k, a, f)
    z = pd.DataFrame(rows)
    z.to_csv(pos.OUT / "gpt_r3_spec.csv", index=False)
    print("лонг к голубой, цель уже пройдена к сигналу:", z[z["пройдена"]].groupby("ряд")["r"].agg(["size", "sum"]).round(1).to_dict("index"), flush=True)
    print(z.groupby(["s", "фаза"])["r"].agg(["size", "sum", "mean"]).round(2).to_string(), flush=True)
    print(z.groupby(["s", "b4"])["r"].agg(["size", "sum", "mean"]).round(2).to_string(), flush=True)


if __name__ == "__main__":
    main()
