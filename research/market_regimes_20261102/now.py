"""Где рынок сейчас (последняя закрытая минута снимка) и что бывало дальше из ТАКОГО ЖЕ состояния в истории BTC
2018–2026. Это частоты прошлого, не прогноз направления (прогноз опровергнут многократно — память
project_direction_refuted). Состояние сейчас определяется теми же правилами, что в PREREG (IND-1, зоны, уровни).

Похожее состояние «S»: 4H close ниже EMA200 4H, EMA200 4H падает за 6 баров, дневной close выше SMA100 (режим ещё
вверх). Точки S берутся на закрытии 4H, не чаще раза в 7 суток (первая в серии). Исходы через 14/30 суток:
дневной close ниже SMA100×0.98 (режим сменился бы вниз и с полосой), 4H close снова выше EMA200, максимальная
просадка и рост от точки; рядом — то же для всех 4H баров с дневным режимом вверх (база)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import mr_data as md  # noqa: E402

DAY = 86400


def main():
    m, h1, h4, d1, fund = md.build()
    last = h4.iloc[-1] if h4["nmin"].iloc[-1] == 240 else h4.iloc[-2]
    lh1 = h1.iloc[-1] if h1["nmin"].iloc[-1] == 60 else h1.iloc[-2]
    dd = d1[d1["nmin"] == 1440]
    sma = dd["sma100"].iloc[-1]
    px = float(m["close"].iloc[-1])
    b4 = h4["B"].to_numpy()
    now = {"время": str(pd.to_datetime(int(m["ts"].iloc[-1]), unit="s")), "цена": px,
           "4H": {"зона": int(last["zone"]), "TEMA50": round(last["G"]), "TEMA100": round(last["Y"]),
                  "TEMA200": round(last["R"]), "EMA200": round(last["B"]), "spread_%": round(last["spread"], 2),
                  "EMA200_наклон_6баров": round(float(b4[-1] - b4[-7]))},
           "1H": {"зона": int(lh1["zone"]), "TEMA100": round(lh1["Y"]), "TEMA200": round(lh1["R"]),
                  "EMA200": round(lh1["B"])},
           "SMA100_дн": round(sma), "SMA100×0.98": round(sma * 0.98), "SMA100×1.02": round(sma * 1.02),
           "IND-1": ("лонг-сетка" if last["zone"] == 1 else "шорт-сетка" if last["zone"] == -1 else
                     "две сетки" if last["spread"] < 0.6 else "ожидание")}
    print(json.dumps(now, ensure_ascii=False))
    # исторические частоты из похожего состояния
    k4, C4, B4 = h4["known"].to_numpy(), h4["close"].to_numpy(), h4["B"].to_numpy()
    slope = B4 - np.r_[np.full(6, np.nan), B4[:-6]]
    reg = d1["reg0"]
    up = np.array([reg.get(t // DAY * DAY, np.nan) == 1.0 for t in k4])
    t_lo = pd.Timestamp("2018-01-01", tz="UTC").timestamp()
    t_hi = k4[-1] - 30 * DAY
    S = (C4 < B4) & (slope < 0) & up & (k4 >= t_lo) & (k4 <= t_hi)
    base = up & (k4 >= t_lo) & (k4 <= t_hi)
    dclose = dd["close"]
    dsma = dd["sma100"]
    mins = m.set_index("ts")[["high", "low", "close"]]

    def outcomes(mask, gap):
        idx, lastt = [], -10 ** 12
        for t in k4[mask]:
            if t - lastt >= gap:
                idx.append(int(t))
                lastt = t
        res = []
        for t in idx:
            p0 = float(mins["close"].asof(t - 60))
            o = {"t": t}
            for hz in (14, 30):
                w = mins.loc[t:t + hz * DAY]
                o[f"min{hz}"] = w["low"].min() / p0 - 1
                o[f"max{hz}"] = w["high"].max() / p0 - 1
                o[f"ret{hz}"] = float(w["close"].iloc[-1]) / p0 - 1
                dw = dclose[(dclose.index >= t) & (dclose.index < t + hz * DAY)]
                sw = dsma.reindex(dw.index)
                o[f"below_sma98_{hz}"] = bool((dw < sw * 0.98).any())
                j = np.searchsorted(k4, t, side="right")
                jj = np.searchsorted(k4, t + hz * DAY, side="right")
                o[f"reclaim_{hz}"] = bool((C4[j:jj] > B4[j:jj]).any())
            res.append(o)
        return pd.DataFrame(res)

    s, b = outcomes(S, 7 * DAY), outcomes(base, 7 * DAY)
    summ = {}
    for nm, df in (("похожее_S", s), ("база_режим_вверх", b)):
        r = {"n": len(df)}
        for hz in (14, 30):
            r[f"{hz}д_закрытие_ниже_SMA×0.98_%"] = round(df[f"below_sma98_{hz}"].mean() * 100, 1)
            r[f"{hz}д_возврат_над_EMA200_4H_%"] = round(df[f"reclaim_{hz}"].mean() * 100, 1)
            r[f"{hz}д_доходность_медиана_%"] = round(df[f"ret{hz}"].median() * 100, 2)
            r[f"{hz}д_доходность_10/90_%"] = [round(df[f"ret{hz}"].quantile(q) * 100, 1) for q in (0.1, 0.9)]
            r[f"{hz}д_мин_от_точки_медиана_%"] = round(df[f"min{hz}"].median() * 100, 2)
            r[f"{hz}д_макс_от_точки_медиана_%"] = round(df[f"max{hz}"].median() * 100, 2)
        summ[nm] = r
        print(nm, json.dumps(r, ensure_ascii=False))
    # половины для S — устойчивость частот
    cut = pd.Timestamp("2022-06-01", tz="UTC").timestamp()
    for nm, q in (("S_до_06.2022", s[s["t"] < cut]), ("S_после", s[s["t"] >= cut])):
        summ[nm] = {"n": len(q), "30д_ниже_SMA×0.98_%": round(q["below_sma98_30"].mean() * 100, 1),
                    "30д_возврат_над_EMA200_%": round(q["reclaim_30"].mean() * 100, 1),
                    "30д_медиана_%": round(q["ret30"].median() * 100, 2)}
        print(nm, summ[nm])
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    (out / "now_result.json").write_text(json.dumps({"now": now, "history": summ}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
