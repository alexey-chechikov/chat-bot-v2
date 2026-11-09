"""PREREG_top_breadth_1108.md, часть 2: ширина потока агрессора по монетам (грубая часовая версия радара из переписки,
разбор GPT 5d30f73) против системы BTC. Фильтры, плацебо и трети — функциями btc_onchain.py (тот же протокол)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_onchain as bo  # noqa: E402
import lab_core as lc  # noqa: E402
import top_fetch as tf  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 200)
OUT = Path(__file__).parent / "out"
MIN_COINS = 20


def breadth():
    D = {}
    for p in sorted(tf.DIR.glob("*USDT_1h.csv")):
        f = pd.read_csv(p, usecols=["ms", "quote", "tb_quote"]).set_index("ms")
        d = 2 * f["tb_quote"] - f["quote"]
        D[p.name.replace("USDT_1h.csv", "")] = d.where(f["quote"] > 0)
    M = pd.DataFrame(D).sort_index()
    M = M.reindex(np.arange(M.index[0], M.index[-1] + 1, 3600_000))
    hi = M.rolling(48, min_periods=48).max().shift(1)
    lo = M.rolling(48, min_periods=48).min().shift(1)
    valid = M.notna() & hi.notna()
    n = valid.sum(1)
    bp = ((M > hi) & valid).sum(1) / n
    bm = ((M < lo) & valid).sum(1) / n
    bp[n < MIN_COINS] = np.nan
    bm[n < MIN_COINS] = np.nan
    known = M.index.to_numpy(np.int64) // 1000 + 3600
    return known, bp, bm, n, M.shape[1]


def absorption(S, F, base):
    t0 = np.array([x[0] for x in base])
    j0 = S.j[t0]
    r = lc.nets(S, base)
    tag = np.array([x[6] for x in base])
    Rp, Rm = bo.yrank(F["ширина покупок 4ч"])[j0], bo.yrank(F["ширина продаж 4ч"])[j0]
    rows = []
    for nm, m_side, R in (("шорт под синей, встречные покупки", np.isin(tag, ["S", "S добор"]), Rp), ("лонг над синей, встречные продажи", np.isin(tag, ["L", "L добор"]), Rm), ("шорт под жёлтой, встречные покупки", tag == "cs", Rp)):
        ok = m_side & np.isfinite(R)
        mid = np.median(S.t[t0[ok]]) if ok.any() else 0
        row = {"сделки": nm}
        for half, hm in (("1", S.t[t0] < mid), ("2", S.t[t0] >= mid)):
            for lab, cond in (("всплеск ≥0.8", R >= 0.8), ("нет", R < 0.8)):
                with np.errstate(invalid="ignore"):
                    m = ok & hm & cond
                row[f"п{half} {lab}"] = f"{r[m].sum():+.0f}/{int(m.sum())}"
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    known, bp, bm, n, ncoins = breadth()
    yr = pd.to_datetime(known, unit="s").year
    print(f"монет в папке {ncoins}; исправных в час, медиана по годам:", pd.Series(n.to_numpy()).groupby(yr).median().to_dict(), flush=True)
    print("ширина часа, квантили 50/90/99%: покупки", np.nanquantile(bp, [.5, .9, .99]).round(3), "продажи", np.nanquantile(bm, [.5, .9, .99]).round(3), flush=True)
    S = lc.load("BTC")
    F = {"ширина покупок 4ч": bo.at(S, known, bp.rolling(4, min_periods=1).max().to_numpy()), "ширина продаж 4ч": bo.at(S, known, bm.rolling(4, min_periods=1).max().to_numpy())}
    base = bo.legs(S)
    st = lc.stats(S, base)
    print("система: сделок", st["n"], "итог", st["итог"], "просадка", st["просадка"], flush=True)
    real = bo.evaluate(S, None, F, {}, base, None)
    plac = bo.evaluate(S, None, F, {}, base, None, shift=2190)
    real.to_csv(OUT / "breadth_filters.csv", index=False)
    print(f"== фильтры: прошли {int(real['прошёл'].sum())} из {len(real)}; плацебо {int(plac['прошёл'].sum())} из {len(plac)}", flush=True)
    print(real.drop(columns="ΔBitstamp").to_string(index=False), flush=True)
    print("== трети ранга на входе: сумма/сделок по половинам", flush=True)
    print(bo.thirds(S, F, base).to_string(index=False), flush=True)
    print("== поглощение: встречный всплеск на входе", flush=True)
    print(absorption(S, F, base).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
