"""Ончейн и деривативы против текущей системы BTC (Простое+, шорт под жёлтой, добор), только биткоин. Записано до прогона:
  показатели: ончейн CoinMetrics (MVRV уровень и изменение 30д, активные адреса и транзакции 30д/180д), хешрейт 30д/60д, стейблы рост 30д; деривативы Binance (OI изменение 1д и 7д, толпа L/S, топы L/S, тейкеры L/S, фандинг 3д) и DVOL;
  момент известности: дневной ончейн с 00:00 дня D+2, метрики Binance по времени строки, DVOL по концу часа, фандинг по выплате; каждый показатель переводится в ранг за прошлый год;
  проверка: основной лонг или основной шорт разрешён только при ранге ≥0.5, ≤0.5, ≥0.2 или ≤0.8, полный поток; разница итога с системой без фильтра в двух половинах периода, где показатель есть, и на Bitstamp 2014–17 для ончейна;
  прошёл = обе половины в плюсе, и Bitstamp, если показатель там есть; плацебо — тот же показатель, сдвинутый на год назад;
  описание: итог сделок системы по третям ранга показателя на входе, по половинам;
  CoinGlass: 182 дня часовых данных, только описание сделок этого времени."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WIN = Path("/private/tmp/claude-501/-Users-alexeychechikov/279942d8-034f-4a29-bc43-ed7d07642e98/scratchpad/win/research/indicator_lab_win")
os.environ["LAB_DATA"] = str(WIN.parent.parent / "data")
sys.path.insert(0, str(WIN))
sys.path.insert(0, str(Path(__file__).parent))
import btc_combo as bcm  # noqa: E402
import lab_core as lc  # noqa: E402
import lab_data as ld  # noqa: E402
import lab_feat as lf  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 200, "display.max_colwidth", 40)
OUT = Path(__file__).parent / "out"
D = ld.DATA
DAY = 86400
SYS = dict(reg=("E", 200), klx=2, sx=lc.G, ksx=2, cs=True, fund=None)


def at(S, known, vals):
    return lf.asof_h4(S, np.asarray(known, np.int64), np.asarray(vals, float))


def features(S, btc=True):
    F = {}
    m = pd.read_csv(D / "g4_cm_btc.csv").sort_values("day")
    k = m["day"].to_numpy(np.int64) + 2 * DAY
    x = m["CapMVRVCur"].to_numpy(float)
    F["MVRV уровень"] = at(S, k, x)
    F["MVRV изменение 30д"] = at(S, k, x / np.r_[np.full(30, np.nan), x[:-30]] - 1)
    for col, lab in (("AdrActCnt", "активные адреса 30д/180д"), ("TxCnt", "транзакции 30д/180д")):
        if col in m:
            y = pd.Series(m[col].to_numpy(float))
            F[lab] = at(S, k, (y.rolling(30).mean() / y.rolling(180).mean()).to_numpy())
    h = pd.read_csv(D / "g4_hash.csv").sort_values("day")
    y = pd.Series(h["hash"].to_numpy(float))
    F["хешрейт 30д/60д"] = at(S, h["day"].to_numpy(np.int64) + 2 * DAY, (y.rolling(30).mean() / y.rolling(60).mean()).to_numpy())
    st = pd.read_csv(D / "g4_stable.csv").sort_values("day")
    y = pd.Series(st["usd"].to_numpy(float))
    F["стейблы рост 30д"] = at(S, st["day"].to_numpy(np.int64) + 2 * DAY, (y / y.shift(30) - 1).to_numpy())
    if not btc:
        return F
    fr = S.fund_rate
    F["фандинг 3д"] = at(S, fr.index.to_numpy(), pd.Series(fr.to_numpy()).rolling(9).mean().to_numpy())
    mt = pd.read_csv(D / "g4_metrics_BTCUSDT.csv")
    k = mt["ts"].to_numpy(np.int64)
    oi = mt["sum_open_interest_value"].to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        F["OI изменение 1д"] = at(S, k, oi / np.r_[np.full(6, np.nan), oi[:-6]] - 1)
        F["OI изменение 7д"] = at(S, k, oi / np.r_[np.full(42, np.nan), oi[:-42]] - 1)
    for col, lab in (("count_long_short_ratio", "толпа L/S"), ("sum_toptrader_long_short_ratio", "топы L/S"), ("sum_taker_long_short_vol_ratio", "тейкеры L/S")):
        F[lab] = at(S, k, mt[col].to_numpy(float))
    v = pd.read_csv(D / "g4_dvol_BTC.csv")
    F["DVOL уровень"] = at(S, v["ms"].to_numpy(np.int64) // 1000 + 3600, v["close"].to_numpy(float))
    return F


def yrank(x, shift=0):
    r = pd.Series(x).rolling(2190, min_periods=1080).rank(pct=True).to_numpy()
    if shift:
        r = np.r_[np.full(shift, np.nan), r[:-shift]]
    return r


def legs(S, lok=None, sok=None):
    return bcm.pyramid(S, bcm.run(S, **SYS, lok=lok, sok=sok))


def wsum(S, lg, a, b):
    t0 = S.t[[x[0] for x in lg]]
    r = lc.nets(S, lg)
    return float(r[(t0 >= a) & (t0 < b)].sum())


COND = ((">=", 0.5), ("<=", 0.5), (">=", 0.2), ("<=", 0.8))


def evaluate(S, Bs, F, FB, base, baseB, shift=0):
    known = S.h4["known"]
    rows = []
    for lab, x in F.items():
        R = yrank(x, shift)
        ok = np.flatnonzero(np.isfinite(R) & (known >= S.t[S.i0]))
        if len(ok) < 1500:
            continue
        a0, a2 = int(known[ok[0]]), int(S.t[-1]) + 1
        a1 = (a0 + a2) // 2
        b1, b2 = wsum(S, base, a0, a1), wsum(S, base, a1, a2)
        RB = yrank(FB[lab], shift) if lab in FB else None
        for sd in ("лонг", "шорт"):
            for op, th in COND:
                with np.errstate(invalid="ignore"):
                    m = (R >= th if op == ">=" else R <= th) | ~np.isfinite(R)
                lg = legs(S, lok=m if sd == "лонг" else None, sok=m if sd == "шорт" else None)
                d1, d2 = wsum(S, lg, a0, a1) - b1, wsum(S, lg, a1, a2) - b2
                dB = np.nan
                if RB is not None and np.isfinite(RB).sum() > 1500:
                    with np.errstate(invalid="ignore"):
                        mb = (RB >= th if op == ">=" else RB <= th) | ~np.isfinite(RB)
                    lb = legs(Bs, lok=mb if sd == "лонг" else None, sok=mb if sd == "шорт" else None)
                    dB = float(lc.nets(Bs, lb).sum() - lc.nets(Bs, baseB).sum())
                passed = d1 > 0 and d2 > 0 and (np.isnan(dB) or dB > 0)
                rows.append({"показатель": lab, "с": pd.Timestamp(a0, unit="s").strftime("%Y-%m"), "сторона": sd, "условие": f"ранг{op}{th}", "Δ1": round(d1, 1), "Δ2": round(d2, 1), "ΔBitstamp": round(dB, 1) if np.isfinite(dB) else None, "прошёл": passed})
    return pd.DataFrame(rows)


def thirds(S, F, base):
    t0 = np.array([x[0] for x in base])
    j0 = S.j[t0]
    r = lc.nets(S, base)
    s = np.array([x[4] for x in base])
    rows = []
    for lab, x in F.items():
        R = yrank(x)[j0]
        ok = np.isfinite(R)
        if ok.sum() < 60:
            continue
        mid = np.median(S.t[t0[ok]])
        for sd, nm in ((1, "лонг"), (-1, "шорт")):
            row = {"показатель": lab, "сторона": nm}
            for half, hm in (("1", S.t[t0] < mid), ("2", S.t[t0] >= mid)):
                for k, (lo, hi) in enumerate(((0, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 1.01))):
                    m = ok & hm & (s == sd) & (R >= lo) & (R < hi)
                    row[f"п{half}_{['низ', 'сер', 'верх'][k]}"] = f"{r[m].sum():+.0f}/{int(m.sum())}"
            rows.append(row)
    return pd.DataFrame(rows)


def coinglass(S, base):
    f = pd.read_csv(Path(__file__).parents[1] / "coinglass_compare/data/BTCUSDT_1h.csv")
    f["ts"] = pd.to_datetime(f["bar_utc"], utc=True).astype("int64") // 10 ** 9 + 3600
    f = f.sort_values("ts").reset_index(drop=True)
    roll = lambda c: f[c].rolling(24, min_periods=1).sum()
    f["ликв_лонгов_24ч"], f["ликв_шортов_24ч"], f["тейкеры_24ч"] = roll("liq_all_long"), roll("liq_all_short"), roll("taker_delta")
    f["OI_24ч_%"] = (f["oi_coins"] / f["oi_coins"].shift(24) - 1) * 100
    r = lc.nets(S, base)
    rows = []
    for x, v in zip(base, r):
        t = S.t[x[0]]
        k = int(np.searchsorted(f["ts"].to_numpy(), t, side="right")) - 1
        if k < 24 or t > f["ts"].iloc[-1] + 3600:
            continue
        q = f.iloc[k]
        rows.append({"вход": pd.Timestamp(int(t), unit="s").strftime("%d.%m %H:%M"), "сделка": x[6], "итог": round(float(v), 2), "киты WI2": round(q["wi2"], 2), "толпа L/S": round(q["ls_acc"], 2), "топы": round(q["ls_top_pos"], 2), "фандинг %": round(q["fr_pct"], 4), "OI 24ч %": round(q["OI_24ч_%"], 1), "ликв L/S 24ч": f"{q['ликв_лонгов_24ч'] / 1e6:.0f}/{q['ликв_шортов_24ч'] / 1e6:.0f}", "тейкеры 24ч": f"{q['тейкеры_24ч'] / 1e6:+.0f}"})
    return pd.DataFrame(rows)


def main():
    S, Bs = lc.load("BTC"), lc.load("Bitstamp")
    F, FB = features(S), features(Bs, btc=False)
    base, baseB = legs(S), legs(Bs)
    st = lc.stats(S, base)
    print("система: сделок", st["n"], "итог", st["итог"], "просадка", st["просадка"], flush=True)
    real = evaluate(S, Bs, F, FB, base, baseB)
    plac = evaluate(S, Bs, F, FB, base, baseB, shift=2190)
    real.to_csv(OUT / "btc_onchain.csv", index=False)
    plac.to_csv(OUT / "btc_onchain_placebo.csv", index=False)
    print(f"== фильтры: прошли {int(real['прошёл'].sum())} из {len(real)}; плацебо со сдвигом на год {int(plac['прошёл'].sum())} из {len(plac)}", flush=True)
    print(real[real["прошёл"]].sort_values("Δ2", ascending=False).to_string(index=False), flush=True)
    print("== по показателям: прошло настоящих / плацебо", flush=True)
    g = pd.DataFrame({"настоящие": real.groupby("показатель")["прошёл"].sum(), "плацебо": plac.groupby("показатель")["прошёл"].sum(), "с": real.groupby("показатель")["с"].first()})
    print(g.to_string(), flush=True)
    t = thirds(S, F, base)
    t.to_csv(OUT / "btc_onchain_thirds.csv", index=False)
    print("== итог сделок системы по третям ранга на входе: сумма/сделок, половины 1 и 2", flush=True)
    print(t.to_string(index=False), flush=True)
    cg = coinglass(S, base)
    cg.to_csv(OUT / "btc_coinglass_trades.csv", index=False)
    print(f"== CoinGlass: сделок за 182 дня {len(cg)}, сумма {cg['итог'].sum():+.1f}", flush=True)
    print(cg.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
