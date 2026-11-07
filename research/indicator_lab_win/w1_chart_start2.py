"""То же, но линии 4ч тоже начинаются с начала часового графика (если request.security отдаёт историю только с этой даты). Запуск: python -X utf8 w1_chart_start2.py"""
import numpy as np, pandas as pd
import lab_core as lc, pine_mirror_plus as pm, w1_chart_start as w
raw = pd.read_csv(lc.ld.DATA / "bybit_BTCUSDT_1h.csv")
raw["ts"] = raw["ms"].to_numpy(np.int64) // 1000
fund = lc.load("BybitBTC").fund_rate
frm = lc.T("2025-01-01")
rows = []
for st in pd.date_range("2024-10-01", "2025-06-15", freq="1D"):
    X = lc.build("x", raw[raw["ts"] >= int(st.timestamp())], fund, st.strftime("%Y-%m-%d"))
    # у коротких рядов ранга нет, простому правилу он не нужен
    legs = [x for x in w_run(X) if X.t[x[0]] >= frm] if False else None
    r = w.closed_since(X, int(X.t[0]), frm)
    rows.append({"начало": st.strftime("%d.%m.%Y"), "сделок": r[0], "итог": r[1], "лонг": r[2], "шорт": r[3], "часов": (int(raw["ts"].iloc[-1]) - int(st.timestamp())) // 3600})
d = pd.DataFrame(rows)
d["откл"] = (d["итог"] - 1.1).abs() + (d["лонг"] + 7.5).abs() + (d["шорт"] - 8.6).abs() + (d["сделок"] - 120).abs()
print(d.sort_values("откл").head(8).drop(columns="откл").to_string(index=False))
