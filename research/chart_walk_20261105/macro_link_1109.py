"""PREREG_trade_ext_1109.md, вопрос 1: есть ли связь BTC с S&P 500, золотом, индексом доллара — по годам.
Тот же день: корреляция дневных ходов (дни торгов рынка, ход BTC за тот же отрезок). Вчера → сегодня: ход рынка в день d
против хода BTC в следующие сутки (00:00→00:00 UTC), доля совпавших сторон. Binance 2018–26, Bitstamp 2014–17.
Запуск: python macro_link_1109.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import features_ext as fe  # noqa: E402
import state_card as sc  # noqa: E402
import words3_look as wl  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40)


def link(a, key):
    f = fe.macro_frame(a, key)
    b = fe.btc_daily(a)
    nxt = np.log(b.shift(-1) / b)
    f["rb_next"] = nxt.reindex(f.index).to_numpy()
    f["год"] = pd.to_datetime(f.index, unit="s").year
    return f.dropna(subset=["rx", "rb"])


def main():
    a, _, _ = sc.load_coin("BTC")
    bs = [x for x in wl.series() if x[0] == "Bitstamp"][0][1]
    rows = []
    for key, nm in fe.MACRO.items():
        f = pd.concat([link(bs, key).query("год <= 2017"), link(a, key).query("год >= 2018")])
        for yr, g in f.groupby("год"):
            g2 = g.dropna(subset=["rb_next"])
            hit = (np.sign(g2["rx"]) == np.sign(g2["rb_next"]))[g2["rx"] != 0].mean()
            rows.append({"рынок": nm, "год": yr, "дней": len(g), "тот же день": round(float(g["rx"].corr(g["rb"])), 2),
                         "вчера→сегодня": round(float(g2["rx"].corr(g2["rb_next"])), 2), "сторона угадана, %": round(float(hit * 100), 1)})
        for lab, m in (("2014–19", f["год"] <= 2019), ("2020–26", f["год"] >= 2020)):
            g = f[m]
            g2 = g.dropna(subset=["rb_next"])
            hit = (np.sign(g2["rx"]) == np.sign(g2["rb_next"]))[g2["rx"] != 0].mean()
            rows.append({"рынок": nm, "год": lab, "дней": len(g), "тот же день": round(float(g["rx"].corr(g["rb"])), 2),
                         "вчера→сегодня": round(float(g2["rx"].corr(g2["rb_next"])), 2), "сторона угадана, %": round(float(hit * 100), 1)})
    R = pd.DataFrame(rows)
    out = R.pivot_table(index="год", columns="рынок", values=["тот же день", "вчера→сегодня", "сторона угадана, %"], aggfunc="first")
    print(out.to_string(), flush=True)
    R.to_csv(Path(__file__).parent / "out" / "macro_link_1109.csv", index=False)


if __name__ == "__main__":
    main()
