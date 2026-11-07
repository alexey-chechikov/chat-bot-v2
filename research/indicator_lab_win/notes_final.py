"""Итоговые числа ответа по запискам оператора 07.11. Запуск: python -X utf8 notes_final.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import candidate as cd
import fam_i as fi
import lab_core as lc
import lab_data as ld
import lab_stats as ls_
import notes_marks as nm
import words4 as w4

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 200, "display.max_colwidth", 48)
NAMED = ["база", "выход лонга под жёлтой", "выход под жёлтой только при Y>G", "выход шорта над жёлтой", "выход шорта при построении вверх", "только чистый шорт", "шорт кроме чистого", "противовес under_y w0.5 отмена Y", "противовес under_y w1.0 отмена Y", "противовес y_over_g w0.5 отмена Y", "противовес y_under_r w0.5 отмена G", "противовес after_exit w0.5 отмена Y", "лонг к синей over_y w1.0 отмена Y", "лонг к синей over_y w0.5 отмена G", "лонг к синей stack_up w1.0 отмена G", "лонг от синей wrong допуск 0.5", "шорт от синей wrong допуск 0.5 отмена Y", "вход над зелёной под красной, цель красная", "ось жёлтая k2", "ось жёлтая k3", "ось жёлтая k2 + оба w0.5", "лонг и шорт по синей k2", "шорт после 3д под синей, выход над B", "шорт после 14д под синей, выход над B", "основной шорт только первые 30д под синей", "всё вместе словами оператора", "выход шорта при построении вверх или над синей", "выход шорта над красной", "к красной: запас от 1.0 ATR, закрытий над зелёной 2", "к красной: запас от 2.0 ATR, закрытий над зелёной 2", "к красной: запас от 1.0 ATR, закрытий над зелёной 1", "к красной: запас от 2.0 ATR, закрытий над зелёной 1", "к красной: запас от 3.0 ATR, закрытий над зелёной 1"]


def fmt(a, b):
    return f"{a:+.0f}/{b:.0f}"


def main():
    d = pd.read_csv(OUT / "fam_i.csv")
    print("прогонов", len(d), "вариантов", d["вариант"].nunique())
    rows = []
    for lab in NAMED:
        r = {"вариант": lab}
        for lay, tag in (("постоянный", "п"), ("плюс", "+")):
            q = d[(d["вариант"] == lab) & (d["слой"] == lay)].iloc[0]
            for s in ("BTC", "ETH", "XRP", "Bitstamp"):
                r[f"{s}{tag}"] = fmt(q[f"{s}_итог"], q[f"{s}_просадка"])
            r[f"BTC25{tag}"] = round(q["BTC_с2025"])
            r[f"ETH25{tag}"] = round(q["ETH_с2025"])
            r[f"XRP25{tag}"] = round(q["XRP_с2025"])
            r[f"n{tag}"] = int(q["BTC_n"])
        rows.append(r)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "notes_table.csv", index=False)
    print("\n=== Постоянный размер")
    print(t[["вариант", "n п".replace(" ", ""), "BTCп", "BTC25п", "ETHп", "ETH25п", "XRPп", "XRP25п", "Bitstampп"]].to_string(index=False))
    print("\n=== Слой Простое+")
    print(t[["вариант", "n+", "BTC+", "BTC25+", "ETH+", "ETH25+", "XRP+", "XRP25+", "Bitstamp+"]].to_string(index=False))

    print("\n=== И8: шорт после N дней под синей, выход над синей (лонг как в базе)")
    q = d[d["вариант"].str.startswith("шорт после") & d["вариант"].str.contains("выход над B")]
    for lay in ("постоянный", "плюс"):
        g = q[q["слой"] == lay]
        print(lay)
        print(g[["вариант", "BTC_n", "BTC_итог", "BTC_просадка", "BTC_с2025", "ETH_итог", "ETH_просадка", "XRP_итог", "XRP_просадка", "Bitstamp_итог", "Bitstamp_просадка"]].to_string(index=False))

    print("\n=== Контроль на 20 монетах, сумма и сколько лучше сравниваемого")
    coins = {c: lc.load(c) for c in ld.COINS20}
    V = {v[1]: v[2] for v in fi.variants()}
    base = {c: lc.stats(S, cd.frozen(S)) for c, S in coins.items()}
    base0 = {c: lc.stats(S, lc.run(S)) for c, S in coins.items()}
    print("Простое+:", round(sum(x["итог"] for x in base.values())), "; база:", round(sum(x["итог"] for x in base0.values())))
    for lab in ("противовес under_y w0.5 отмена Y", "шорт кроме чистого", "выход лонга под жёлтой", "выход шорта над жёлтой", "выход шорта при построении вверх", "ось жёлтая k3", "всё вместе словами оператора"):
        for lay, ref in (("постоянный", base0), ("плюс", base)):
            st = {c: lc.stats(S, fi.legs_of(S, V[lab], lay)) for c, S in coins.items()}
            print(lab, lay, "сумма", round(sum(x["итог"] for x in st.values())), "лучше на", sum(st[c]["итог"] > ref[c]["итог"] for c in coins), "из 20; медианная просадка", round(float(np.median([x["просадка"] for x in st.values()]))), "; с 2025", round(sum(x["с2025"] for x in st.values())))

    print("\n=== Deflated Sharpe с учётом всех попыток (А–Ж, З, И)")
    for n in ("BTC", "ETH", "XRP"):
        S = lc.load(n)
        M1 = np.load(OUT / f"sweep_daily_{n}.npy").astype(np.float64)
        M2 = np.load(OUT / f"fam_z_daily_{n}.npy").astype(np.float64)
        M3 = np.load(OUT / f"fam_i_daily_{n}.npy").astype(np.float64)
        L = min(M1.shape[1], M2.shape[1], M3.shape[1])
        M = np.r_[M1[:, -L:], M2[:, -L:], M3[:, -L:]]
        M = M[M.std(axis=1) > 0]
        tr = ls_.sharpe(M)
        for lab, legs in (("база", lc.run(S)), ("Простое+", cd.frozen(S)), ("Простое+ с противовесом", w4.run(S, **w4.plus_layer(S), **w4.CS))):
            print(n, lab, {k: round(v, 3) for k, v in ls_.dsr(lc.daily_returns(S, legs).to_numpy(), tr).items()}, "попыток", len(tr))

    print("\n=== Скользящий выбор внутри семейства И, каждый год лучший по прошлому")
    for n in ("BTC", "ETH", "XRP"):
        M = np.load(OUT / f"fam_i_daily_{n}.npy").astype(np.float64)
        days = ls_.days_of(n)[-M.shape[1]:]
        for lay in ("постоянный", "плюс"):
            idx = np.flatnonzero((d["слой"] == lay).to_numpy())
            dd = d.iloc[idx].reset_index(drop=True)
            b0 = int(dd.index[dd["вариант"] == "база"][0])
            tt, a, b, da, db = ls_.walk(M[idx], days, dd, b0)
            print(n, lay, f"выбор {a:+.0f}/{da:.0f} против {b:+.0f}/{db:.0f};", tt["выбран"].tolist())

    print("\n=== Годы: Простое+ и с противовесом")
    for n in ("BTC", "ETH", "XRP", "Bitstamp"):
        S = lc.load(n)
        a, b = cd.frozen(S), w4.run(S, **w4.plus_layer(S), **w4.CS)
        ya = pd.Series(lc.nets(S, a)).groupby(pd.to_datetime(S.t[[x[0] for x in a]], unit="s").year).sum().round(1)
        yb = pd.Series(lc.nets(S, b)).groupby(pd.to_datetime(S.t[[x[0] for x in b]], unit="s").year).sum().round(1)
        print(n, pd.DataFrame({"плюс": ya, "новый": yb}).T.to_string())
        st = lc.stats(S, b)
        print("  ", {k: st[k] for k in ("n", "итог", "просадка", "с2025", "p1", "p2", "p3", "плюс%", "ди_низ")})

    print("\n=== Окна и дни из записок, Bybit, слой Простое+")
    S = lc.load("BybitBTC")
    rows = []
    for lab, kw in (("Простое+", {}), ("с противовесом", w4.CS), ("выход лонга под жёлтой", V["выход лонга под жёлтой"]), ("шорт кроме чистого", V["шорт кроме чистого"]), ("ось жёлтая k2", V["ось жёлтая k2"]), ("всё вместе", V["всё вместе словами оператора"])):
        legs = fi.legs_of(S, kw, "плюс")
        n, _ = nm.recall(S, legs)
        ws = nm.win_sums(S, legs)
        st = lc.stats(S, legs)
        rows.append({"вариант": lab, "дни": n, **{w[0]: v for w, v in zip(nm.WIN, ws)}, "сумма_окон": round(sum(ws), 1), "весь_Bybit": st["итог"], "дд": st["просадка"], "с25": st["с2025"]})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n=== Ожидаемо на графике: с противовесом, закрытые с 01.01.2025, без фандинга, с весом")
    for name, lab in (("BybitBTC", "BYBIT:BTCUSDT.P"), ("BTC", "BINANCE:BTCUSDT")):
        S = lc.load(name)
        legs = [x for x in w4.run(S, **w4.plus_layer(S), **w4.CS) if S.t[x[0]] >= lc.T("2025-01-01") and x[7] != "конец"]
        net = [x[5] * (x[4] * (x[3] / x[2] - 1) * 100 - 0.068 - 0.068 * x[3] / x[2]) for x in legs]
        cs = [v for v, x in zip(net, legs) if x[6] == "противовес"]
        print(lab, "сделок", len(legs), "итог", round(sum(net), 1), "из них противовес", len(cs), round(sum(cs), 1))


if __name__ == "__main__":
    main()
