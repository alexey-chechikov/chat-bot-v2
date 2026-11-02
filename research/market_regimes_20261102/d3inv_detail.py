"""Разбор единственного правила, прошедшего 4 ворот из 5: D3-inv (PREREG: перевёрнутое D3) — ЛОНГ-сетка 0.6/1.4,
пока 4H зона v11 = −1 и 1H зона ≠ +1; закрыть остаток по рынку, когда 4H зона ушла из −1 или 1H стала +1.
По годам, лучшие/худшие эпизоды, эпизоды периода C, издержки ×2 (ворота издержек), без фандинга.
Это описание уже прогнанного правила, НЕ новый подбор: параметры те же."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import gridk  # noqa: E402
import mr_data as md  # noqa: E402
import regime_rules as rr  # noqa: E402


def main():
    m, h1, h4, d1, fund = md.build()
    t_end = int(m["ts"].iloc[-1]) + 60
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    E, _ = rr.build_episodes(h1, h4, d1, t_end)
    eps = [e for e in E["D3-inv"] if e[0] >= rr.PERIODS["A"][0]]
    a = np.array([e[0] for e in eps]); b = np.array([e[1] for e in eps])
    res = mk.run(mk.idx(a), mk.idx(b), 1, cap=rr.CAP1)
    res2 = mk.run(mk.idx(a), mk.idx(b), 1, cap=rr.CAP1, mk=2 * gridk.MAKER, tk=2 * gridk.TAKER, sl=2 * gridk.SLIP)
    df = pd.DataFrame(res, columns=gridk.COLS)
    df["start"] = pd.to_datetime(a, unit="s")
    df["hours"] = (b - a) / 3600
    df["px0"] = mk.o[mk.idx(a)]
    df["px1"] = mk.o[np.minimum(mk.idx(b), mk.n - 1)]
    df["move_%"] = (df["px1"] / df["px0"] - 1) * 100
    df["net_x2cost"] = res2[:, 0]
    df["year"] = df["start"].dt.year
    by = df.groupby("year").agg(n=("net", "size"), net=("net", "sum"), net_x2=("net_x2cost", "sum"),
                                hours=("hours", "sum"), worst=("net", "min"))
    print(by.round(1).to_string())
    print("доля плюсовых эпизодов:", round((df["net"] > 0).mean(), 3), " медиана эпизода:", round(df["net"].median(), 2),
          " длительность медиана ч:", round(df["hours"].median(), 1))
    print("ход цены за эпизод, медиана %:", round(df["move_%"].median(), 2), " среднее:", round(df["move_%"].mean(), 2))
    cols = ["start", "hours", "move_%", "net", "tp_gross", "exit_pnl", "fills", "lots_exit"]
    print("худшие 5:\n", df.nsmallest(5, "net")[cols].round(1).to_string())
    print("лучшие 5:\n", df.nlargest(5, "net")[cols].round(1).to_string())
    c = df[df["start"] >= pd.Timestamp("2026-05-01")]
    print("период C:\n", c[cols].round(1).to_string())
    top10 = df.nlargest(10, "net")["net"].sum()
    out = {"по_годам": by.round(1).reset_index().to_dict("records"),
           "итог": round(float(df["net"].sum()), 1), "итог_издержки_x2": round(float(df["net_x2cost"].sum()), 1),
           "без_10_лучших": round(float(df["net"].sum() - top10), 1),
           "доля_плюсовых": round(float((df["net"] > 0).mean()), 3),
           "C": c[cols].round(1).astype({"start": str}).to_dict("records")}
    print("итог", out["итог"], "издержки ×2", out["итог_издержки_x2"], "без 10 лучших эпизодов", out["без_10_лучших"])
    (HERE / "out" / "d3inv_detail.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
