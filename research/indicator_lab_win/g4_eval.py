"""G4: внешние данные как фильтр лонга или шорта простого правила, не как прогноз направления. Полный поток.
Каждый показатель переводится в ранг за прошлый год (нет заглядывания, порог не зависит от уровня). Сетка: лонг или шорт × ранг ≥0.5, ≤0.5, ≤0.8, ≥0.2.
Сравнение с базой только на периоде, где показатель есть, отдельно в двух половинах этого периода. Плацебо: тот же показатель, сдвинутый на год назад (та же инерция, связи с текущим рынком нет).
Запуск: python -X utf8 g4_eval.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc
import lab_data as ld
import lab_feat as lf

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 300, "display.max_colwidth", 40)
D = ld.DATA
DAY = 86400
YEAR4 = 365 * 6


def ser_at(S, known, vals):
    return lf.asof_h4(S, np.asarray(known, np.int64), np.asarray(vals, float))


def factors(S, coin):
    F = {}
    c4 = S.h4["c"]
    # фандинг: последняя выплата уже известна
    fr = S.fund_rate
    if len(fr) > 2:
        F["фандинг средний 3д"] = ser_at(S, fr.index.to_numpy(), pd.Series(fr.to_numpy()).rolling(9).mean().to_numpy())
    # OI, L/S, тейкеры: архив Binance, строки на закрытии 4ч
    p = D / f"g4_metrics_{coin}USDT.csv"
    if p.exists():
        m = pd.read_csv(p)
        k = m["ts"].to_numpy(np.int64)
        oi = m["sum_open_interest_value"].to_numpy(float)
        F["OI изменение 1д"] = ser_at(S, k, oi / np.r_[np.full(6, np.nan), oi[:-6]] - 1)
        F["OI изменение 7д"] = ser_at(S, k, oi / np.r_[np.full(42, np.nan), oi[:-42]] - 1)
        for col, lab in (("count_long_short_ratio", "толпа L/S"), ("sum_toptrader_long_short_ratio", "топы L/S объём"), ("count_toptrader_long_short_ratio", "топы L/S счета"), ("sum_taker_long_short_vol_ratio", "тейкеры L/S")):
            F[lab] = ser_at(S, k, m[col].to_numpy(float))
    # опционы
    p = D / f"g4_dvol_{coin}.csv"
    if p.exists():
        v = pd.read_csv(p)
        k = v["ms"].to_numpy(np.int64) // 1000 + 3600
        x = v["close"].to_numpy(float)
        F["DVOL уровень"] = ser_at(S, k, x)
        F["DVOL изменение 7д"] = ser_at(S, k, x - np.r_[np.full(168, np.nan), x[:-168]])
        ret = np.diff(np.log(c4), prepend=np.log(c4[0]))
        rv = pd.Series(ret).rolling(84).std().to_numpy() * np.sqrt(6 * 365) * 100
        F["DVOL минус реализованная 14д"] = F["DVOL уровень"] - rv
    # ончейн: день D доступен с 00:00 D+2
    p = D / f"g4_cm_{coin.lower()}.csv"
    if p.exists():
        m = pd.read_csv(p).sort_values("day")
        k = m["day"].to_numpy(np.int64) + 2 * DAY
        if "CapMVRVCur" in m:
            x = m["CapMVRVCur"].to_numpy(float)
            F["MVRV уровень"] = ser_at(S, k, x)
            F["MVRV изменение 30д"] = ser_at(S, k, x / np.r_[np.full(30, np.nan), x[:-30]] - 1)
        if "AdrActCnt" in m:
            x = pd.Series(m["AdrActCnt"].to_numpy(float))
            F["активные адреса 30д/180д"] = ser_at(S, k, (x.rolling(30).mean() / x.rolling(180).mean()).to_numpy())
        if "TxCnt" in m:
            x = pd.Series(m["TxCnt"].to_numpy(float))
            F["транзакции 30д/180д"] = ser_at(S, k, (x.rolling(30).mean() / x.rolling(180).mean()).to_numpy())
    if coin == "BTC":
        h = pd.read_csv(D / "g4_hash.csv").sort_values("day")
        x = pd.Series(h["hash"].to_numpy(float))
        F["хешрейт 30д/60д"] = ser_at(S, h["day"].to_numpy(np.int64) + 2 * DAY, (x.rolling(30).mean() / x.rolling(60).mean()).to_numpy())
    st = pd.read_csv(D / "g4_stable.csv").sort_values("day")
    x = pd.Series(st["usd"].to_numpy(float))
    F["стейблы рост 30д"] = ser_at(S, st["day"].to_numpy(np.int64) + 2 * DAY, (x / x.shift(30) - 1).to_numpy())
    # макро: день D доступен с 00:00 D+1
    mc = pd.read_csv(D / "g4_macro.csv").sort_values("day")
    k = mc["day"].to_numpy(np.int64) + DAY
    for col, lab in (("spx", "SPX 20д"), ("ndx", "NDX 20д"), ("dxy", "DXY 20д"), ("gold", "золото 20д")):
        x = pd.Series(mc[col].to_numpy(float)).ffill()
        F[lab] = ser_at(S, k, (x / x.shift(20) - 1).to_numpy())
    x = pd.Series(mc["spx"].to_numpy(float)).ffill()
    F["SPX к SMA50"] = ser_at(S, k, (x / x.rolling(50).mean() - 1).to_numpy())
    x = pd.Series(mc["tnx"].to_numpy(float)).ffill()
    F["10 лет изменение 20д"] = ser_at(S, k, (x - x.shift(20)).to_numpy())
    F["VIX"] = ser_at(S, k, pd.Series(mc["vix"].to_numpy(float)).ffill().to_numpy())
    return F


def yrank(x):
    return pd.Series(x).rolling(YEAR4, min_periods=1080).rank(pct=True).to_numpy()


def window_sum(S, legs, a, b):
    t0 = S.t[[x[0] for x in legs]]
    r = lc.nets(S, legs)
    m = (t0 >= a) & (t0 < b)
    return float(r[m].sum()), int(m.sum())


def evaluate(S, coin, shift_days=0):
    F = factors(S, coin)
    base = lc.run(S)
    known = S.h4["known"]
    rows = []
    for lab, x in F.items():
        R = yrank(x)
        if shift_days:
            b = shift_days * 6
            R = np.r_[np.full(b, np.nan), R[:-b]]
        ok = np.flatnonzero(np.isfinite(R) & (known >= S.t[S.i0]))
        if len(ok) < 1500:
            continue
        a0, a2 = int(known[ok[0]]), int(known[-1]) + 1
        a1 = (a0 + a2) // 2
        b1, _ = window_sum(S, base, a0, a1)
        b2, _ = window_sum(S, base, a1, a2)
        for sd in ("лонг", "шорт"):
            for op, th in ((">=", 0.5), ("<=", 0.5), ("<=", 0.8), (">=", 0.2)):
                with np.errstate(invalid="ignore"):
                    cond = (R >= th) if op == ">=" else (R <= th)
                cond = cond | ~np.isfinite(R)
                kw = {"Lok": cond} if sd == "лонг" else {"Sok": cond}
                legs = lc.run(S, **kw)
                s1, n1 = window_sum(S, legs, a0, a1)
                s2, n2 = window_sum(S, legs, a1, a2)
                rows.append({"монета": coin, "показатель": lab, "сторона": sd, "условие": f"ранг{op}{th}", "с": pd.Timestamp(a0, unit="s").strftime("%Y-%m"), "база_1": round(b1, 1), "база_2": round(b2, 1), "итог_1": round(s1, 1), "итог_2": round(s2, 1), "Δ_1": round(s1 - b1, 1), "Δ_2": round(s2 - b2, 1), "Δ": round(s1 + s2 - b1 - b2, 1), "n": n1 + n2})
    return pd.DataFrame(rows)


def main():
    all_ = []
    plc = []
    for coin in ("BTC", "ETH", "XRP"):
        S = lc.load(coin)
        d = evaluate(S, coin)
        all_.append(d)
        plc.append(evaluate(S, coin, shift_days=365))
        print(coin, "факторов", d["показатель"].nunique(), "вариантов", len(d), flush=True)
    d = pd.concat(all_)
    p = pd.concat(plc)
    d.to_csv(OUT / "g4_eval.csv", index=False)
    p.to_csv(OUT / "g4_placebo.csv", index=False)
    print("\nИсточники и глубина:", d.groupby("показатель")["с"].min().to_dict())
    for lab, q in (("настоящие", d), ("плацебо, сдвиг на год", p)):
        both = q[(q["Δ_1"] > 0) & (q["Δ_2"] > 0)]
        print(f"{lab}: вариантов {len(q)}, плюс в обеих половинах {len(both)} ({len(both) / len(q) * 100:.0f}%), средний Δ {q['Δ'].mean():.1f}, 90-й перцентиль Δ {q['Δ'].quantile(.9):.1f}")
    keys = ["показатель", "сторона", "условие"]
    w = d.pivot_table(index=keys, columns="монета", values=["Δ", "Δ_1", "Δ_2"])
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    w = w.reset_index()
    for c in ("BTC", "ETH"):
        w[f"ok_{c}"] = (w[f"Δ_1_{c}"] > 0) & (w[f"Δ_2_{c}"] > 0)
    w["на_BTC_и_ETH"] = w["ok_BTC"] & w["ok_ETH"]
    q = w[w["на_BTC_и_ETH"]].copy()
    q["сумма"] = q[["Δ_BTC", "Δ_ETH"]].sum(axis=1)
    print("\nПлюс в обеих половинах и на BTC, и на ETH:", len(q), "из", len(w))
    print(q.sort_values("сумма", ascending=False).head(25)[keys + ["Δ_BTC", "Δ_1_BTC", "Δ_2_BTC", "Δ_ETH", "Δ_1_ETH", "Δ_2_ETH", "Δ_XRP"]].round(1).to_string(index=False))
    pw = p.pivot_table(index=keys, columns="монета", values=["Δ_1", "Δ_2"])
    pw.columns = [f"{a}_{b}" for a, b in pw.columns]
    n_p = int(((pw["Δ_1_BTC"] > 0) & (pw["Δ_2_BTC"] > 0) & (pw["Δ_1_ETH"] > 0) & (pw["Δ_2_ETH"] > 0)).sum())
    print(f"то же у плацебо: {n_p} из {len(pw)}")
    print("\nЛучшие на BTC по одной монете:")
    print(d[d["монета"] == "BTC"].sort_values("Δ", ascending=False).head(12)[keys + ["с", "Δ", "Δ_1", "Δ_2", "n"]].to_string(index=False))


if __name__ == "__main__":
    main()
