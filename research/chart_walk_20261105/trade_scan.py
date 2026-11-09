"""PREREG_trade_table_1109.md, слои 1–3: какие признаки отличают лучшие сделки от худших — с проверкой на других годах,
на Bitstamp и против перестановок. Читает out/trade_table_btc.pkl (trade_table.py). Запуск: python trade_scan.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
OUT = Path(__file__).parent / "out"
REF = Path("/Users/alexeychechikov/code/bot7/services/btc_signals/feature_ref.json")
LIVE = OUT / "live_features.json"  # признаки, которые считает живая служба (features.py), — пишет trade_table.py
CUT, CUT25 = 1672531200, 1735689600  # 2023-01-01, 2025-01-01
NPERM = 500
RNG = np.random.default_rng(1109)
TYPES = ["лонг над синей", "шорт под синей", "шорт под жёлтой", "лонг 432"]
TARGETS = ["итог, % базы", "в лучших 20%", "отдача, ATR", "MFE, ATR"]
LATE_FROM = 1546300800  # 2019-01-01: признаки, у которых история позже, — разрез по половинам их сделок
OUTCOME = {"в лучших 20%", "ряд", "стратегия", "тип", "сторона", "вход UTC", "выход UTC", "цена входа", "цена выхода", "вес", "добор", "цена добора", "причина выхода", "итог, % базы", "ход, %",
           "MFE, %", "MAE, %", "MFE, ATR", "MAE, ATR", "часов до MFE", "часов до MAE", "отдача, ATR", "отдача, доля MFE", "сначала +1 ATR или −1 ATR", "часов в сделке",
           "ход через 24ч, %", "ход через 72ч, %", "ход через 7д, %", "фаза", "порядок линий"}
OUTCOME.update({"добор UTC", "MFE lower, ATR", "MFE upper, ATR", "MAE lower, ATR", "MAE upper, ATR",
                "MFE lower, %", "MFE upper, %", "MAE lower, %", "MAE upper, %",
                "качество пути", "разрешение выхода", "причина качества пути", "качество порядка ±1 ATR"})
OUTCOME.update({"часов до MFE lower", "часов до MFE upper", "часов до MAE lower", "часов до MAE upper",
                "семантика времени экстремумов"})
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 400, "display.max_colwidth", 46)


def rankcorr(x, Y):
    """Спирмен x с каждым столбцом Y (n × k) на строках, где x конечен. → (r: k, n)."""
    m = np.isfinite(x)
    n = int(m.sum())
    if n < 25 or np.nanstd(x[m]) == 0:
        return np.full(Y.shape[1], np.nan), n
    rx = stats.rankdata(x[m])
    rx = (rx - rx.mean()) / rx.std()
    ry = np.apply_along_axis(stats.rankdata, 0, Y[m])
    ry = (ry - ry.mean(0)) / ry.std(0)
    return (rx @ ry) / n, n


def pval(r, n, one_sided_sign=None):
    with np.errstate(invalid="ignore", divide="ignore"):
        t = r * np.sqrt((n - 2) / np.maximum(1 - r ** 2, 1e-12))
    if one_sided_sign is None:
        return 2 * stats.t.sf(np.abs(t), n - 2)
    return stats.t.sf(t * one_sided_sign, n - 2)


def tiers(rd, nd, r1, n1, r2, n2):
    """Ярус по PREREG для массивов корреляций (последняя ось — перестановки или одна реальная)."""
    pd_ = pval(rd, nd)
    sg = np.sign(rd)
    p1 = pval(r1, n1, sg)
    has2 = n2 >= 25
    p2 = pval(r2, n2, sg) if has2 else np.ones_like(rd)
    same1, same2 = np.sign(r1) == sg, (np.sign(r2) == sg) if has2 else np.ones_like(rd, bool)
    if has2:
        t1 = (pd_ < 0.01) & same1 & (p1 < 0.10) & same2 & (p2 < 0.10)
    else:
        t1 = (pd_ < 0.01) & same1 & (p1 < 0.05)
    t2 = (pd_ < 0.05) & same1 & same2
    return t1, t2, pd_, p1, p2


def periods(D, typ):
    d = D[D["тип"] == typ]
    b = d[d["ряд"] == "Binance"]
    return {"открытие 2018–22": b[b["_t0"] < CUT], "проверка 2023–26": b[b["_t0"] >= CUT], "Bitstamp 2014–17": d[d["ряд"] == "Bitstamp"]}


def scan(D, feats):
    rows, null_t1, null_t2 = [], np.zeros(NPERM), np.zeros(NPERM)
    for typ in TYPES:
        P = periods(D, typ)
        for tg in TARGETS:
            Ys = {}
            for k, d in P.items():
                y = d[tg].to_numpy(float)
                y = np.where(np.isfinite(y), y, np.nanmedian(y) if np.isfinite(y).any() else 0.0)
                perm = np.column_stack([y] + [RNG.permutation(y) for _ in range(NPERM)])
                Ys[k] = perm
            names = list(P)
            for ft in feats:
                R, N = [], []
                for k in names:
                    r, n = rankcorr(P[k][ft].to_numpy(float), Ys[k])
                    R.append(r)
                    N.append(n)
                if not np.isfinite(R[0][0]) or N[0] < 25 or N[1] < 25:
                    continue
                r2 = R[2] if N[2] >= 25 and np.isfinite(R[2][0]) else np.zeros_like(R[0])
                t1, t2, pd_, p1, p2 = tiers(R[0], N[0], R[1], N[1], r2, N[2] if np.isfinite(R[2][0]) else 0)
                null_t1 += t1[1:]
                null_t2 += t2[1:]
                d0 = P[names[0]]
                y0 = d0[tg].to_numpy(float)
                hi, lo = np.nanquantile(y0, 0.8), np.nanquantile(y0, 0.2)
                xb, xw = d0.loc[y0 >= hi, ft], d0.loc[y0 <= lo, ft]
                rows.append({"тип": typ, "цель": tg, "признак": ft, "ярус": 1 if t1[0] else (2 if t2[0] else 0), "только Binance": N[2] < 25 or not np.isfinite(R[2][0]),
                             "r открытие": round(float(R[0][0]), 3), "p открытие": float(pd_[0]), "n": N[0], "r 2023–26": round(float(R[1][0]), 3), "p 2023–26": float(p1[0]), "n2": N[1],
                             "r Bitstamp": round(float(r2[0]), 3) if N[2] >= 25 else None, "p Bitstamp": float(p2[0]) if N[2] >= 25 else None, "n3": N[2],
                             "медиана у лучших 20%": round(float(xb.median()), 3) if xb.notna().any() else None, "медиана у худших 20%": round(float(xw.median()), 3) if xw.notna().any() else None})
    return pd.DataFrame(rows), null_t1, null_t2


def add_best(D):
    """«в лучших 20%»: итог не ниже 80-го перцентиля своего типа в своём отрезке."""
    D["в лучших 20%"] = np.nan
    for typ in TYPES:
        for k, d in periods(D, typ).items():
            y = d["итог, % базы"].to_numpy(float)
            D.loc[d.index, "в лучших 20%"] = (y >= np.quantile(y, 0.8)).astype(float)
    return D


def late_feats(D, feats):
    b = D[D["ряд"] == "Binance"]
    out = []
    for ft in feats:
        m = b[ft].notna()
        if m.any() and b.loc[m, "_t0"].min() > LATE_FROM:
            out.append(ft)
    return out


def scan_late(D, feats):
    """Признаки с поздней историей: сделки Binance с признаком, по времени — первая половина открытие, вторая проверка."""
    rows, null_t1, null_t2 = [], np.zeros(NPERM), np.zeros(NPERM)
    for typ in TYPES:
        b = D[(D["тип"] == typ) & (D["ряд"] == "Binance")].sort_values("_t0")
        for tg in TARGETS:
            for ft in feats:
                d = b[b[ft].notna()]
                if len(d) < 50:
                    continue
                h = len(d) // 2
                R, N = [], []
                for part in (d.iloc[:h], d.iloc[h:]):
                    y = part[tg].to_numpy(float)
                    y = np.where(np.isfinite(y), y, np.nanmedian(y))
                    Y = np.column_stack([y] + [RNG.permutation(y) for _ in range(NPERM)])
                    r, n = rankcorr(part[ft].to_numpy(float), Y)
                    R.append(r)
                    N.append(n)
                if not np.isfinite(R[0][0]) or not np.isfinite(R[1][0]):
                    continue
                pd_ = pval(R[0], N[0])
                sg = np.sign(R[0])
                p1 = pval(R[1], N[1], sg)
                t1 = (pd_ < 0.01) & (np.sign(R[1]) == sg) & (p1 < 0.05)
                t2 = (pd_ < 0.05) & (np.sign(R[1]) == sg)
                null_t1 += t1[1:]
                null_t2 += t2[1:]
                rows.append({"тип": typ, "цель": tg, "признак": ft, "ярус": 1 if t1[0] else (2 if t2[0] else 0), "только Binance": True, "поздние данные": True,
                             "с": pd.Timestamp(int(d["_t0"].iloc[0]), unit="s").strftime("%Y-%m"), "граница": pd.Timestamp(int(d["_t0"].iloc[h]), unit="s").strftime("%Y-%m"),
                             "r открытие": round(float(R[0][0]), 3), "p открытие": float(pd_[0]), "n": N[0], "r 2023–26": round(float(R[1][0]), 3), "p 2023–26": float(p1[0]), "n2": N[1],
                             "r Bitstamp": None, "p Bitstamp": None, "n3": 0})
    return pd.DataFrame(rows), null_t1, null_t2


def improve(D, S):
    """Слой 2: признаки яруса 1 для итога — пропуск худшей пятой части и размер по пятым, границы с открытия."""
    out = []
    for _, z in S[(S["ярус"] == 1) & (S["цель"] == "итог, % базы")].iterrows():
        P = periods(D, z["тип"])
        x0 = P["открытие 2018–22"][z["признак"]].to_numpy(float)
        edges = np.nanquantile(x0, [0.2, 0.4, 0.6, 0.8])
        sg = np.sign(z["r открытие"])
        row = {"тип": z["тип"], "признак": z["признак"], "знак": "+" if sg > 0 else "−"}
        for k, d in P.items():
            x, y = d[z["признак"]].to_numpy(float), d["итог, % базы"].to_numpy(float)
            q = np.searchsorted(edges, x) if sg > 0 else 4 - np.searchsorted(edges, x)
            q = np.where(np.isfinite(x), q, 2)
            mult = np.array([0.5, 0.75, 1.0, 1.25, 1.5])[q]
            row[f"{k}: база"] = round(float(y.sum()), 1)
            row[f"{k}: без худшей пятой"] = round(float(y[q > 0].sum()), 1)
            row[f"{k}: размер 0.5–1.5"] = round(float((y * mult).sum()), 1)
        out.append(row)
    return pd.DataFrame(out)


def portrait(D, feats, typ, top=12):
    d = periods(D, typ)["открытие 2018–22"]
    y = d["итог, % базы"].to_numpy(float)
    best, worst = d[y >= np.quantile(y, 0.8)], d[y <= np.quantile(y, 0.2)]
    rows = []
    for ft in feats:
        x = d[ft].to_numpy(float)
        sd = np.nanstd(x)
        if not np.isfinite(sd) or sd == 0:
            continue
        rows.append({"признак": ft, "лучшие 20%": round(float(best[ft].median()), 2), "худшие 20%": round(float(worst[ft].median()), 2),
                     "разница в σ": round(float((best[ft].mean() - worst[ft].mean()) / sd), 2)})
    return pd.DataFrame(rows).reindex(columns=["признак", "лучшие 20%", "худшие 20%", "разница в σ"]).sort_values("разница в σ", key=np.abs, ascending=False).head(top)


FILL = ["от синей, %", "ADX 4ч", "ход 7д, %", "ранг ATR100 за год", "часов после пересечения З/Ж", "RSI 4ч"]
NOTE = {("MFE, ATR", 1): "ход обычно больше", ("MFE, ATR", -1): "ход обычно меньше", ("отдача, ATR", 1): "отдаёт больше", ("отдача, ATR", -1): "отдаёт меньше",
        ("итог, % базы", 1): "итог обычно лучше", ("итог, % базы", -1): "итог обычно хуже",
        ("в лучших 20%", 1): "чаще в лучших", ("в лучших 20%", -1): "реже в лучших"}


def export_ref(D, S, path):
    """Справка для сообщения о входе (services/btc_signals/feature_ref.json): по типу — 5 признаков с самой сильной
    подтверждённой (ярус 1) связью с ходом/отдачей, без дублей «%»/«ATR» и сильно связанных между собой; не хватает —
    описательные из FILL. Для каждого — 101 перцентиль по всем сделкам типа (Binance + Bitstamp) и пометка связи."""
    import json
    live = set(json.loads(LIVE.read_text())) if LIVE.exists() else None
    ref = {}
    for typ in TYPES:
        d = D[D["тип"] == typ]
        s = S[(S["тип"] == typ) & (S["ярус"] == 1)].copy()
        if live is not None:
            s = s[s["признак"].isin(live)]
        s["сила"] = s[["r открытие", "r 2023–26"]].abs().mean(axis=1)
        picked = []
        for ft in list(s.sort_values("сила", ascending=False)["признак"].drop_duplicates()) + FILL:
            if len(picked) >= 5:
                break
            if ft in picked or ft not in d or d[ft].notna().sum() < 50:
                continue
            base = ft.replace(", %", "").replace(", ATR", "")
            if any(base == p.replace(", %", "").replace(", ATR", "") for p in picked):
                continue
            x = d[ft].astype(float)
            if any(abs(x.corr(d[p].astype(float), method="spearman")) > 0.8 for p in picked):
                continue
            picked.append(ft)
        items = []
        for ft in picked:
            x = d[ft].astype(float).dropna().to_numpy()
            notes = [NOTE[(r["цель"], int(np.sign(r["r открытие"])))] for _, r in s[s["признак"] == ft].iterrows()]
            items.append({"feat": ft, "q": np.quantile(x, np.linspace(0, 1, 101)).round(6).tolist(), "n": int(len(x)),
                          "note": ("выше значение — " + ", ".join(notes)) if notes else ""})
        ref[typ] = items
    path.write_text(json.dumps({"what": "trade_scan.export_ref: перцентили признаков входа по сделкам 2014–26 и подтверждённые связи (ярус 1). Описание, не прогноз.",
                                "types": ref}, ensure_ascii=False, indent=1))
    return ref


def main():
    D = add_best(pd.read_pickle(OUT / "trade_table_btc.pkl"))
    feats_all = [c for c in D.columns if c not in OUTCOME and not c.startswith("_") and pd.api.types.is_numeric_dtype(D[c])]
    late = late_feats(D, feats_all)
    feats = [f for f in feats_all if f not in late]
    print(f"сделок {len(D)}, признаков: с полной историей {len(feats)}, с поздней {len(late)}; типов {len(TYPES)}, целей {len(TARGETS)}", flush=True)
    print("поздние:", late, flush=True)
    for typ in TYPES:
        P = periods(D, typ)
        print(typ, {k: (len(v), round(float(v['итог, % базы'].sum()), 1)) for k, v in P.items()}, flush=True)
    if "--ref-only" in sys.argv:
        S = pd.read_csv(OUT / "trade_scan_all.csv", sep=";", decimal=",")
        ref = export_ref(D, S, REF)
        for typ, items in ref.items():
            print(typ, [(x["feat"], x["note"]) for x in items], flush=True)
        return
    S, n1, n2 = scan(D, feats)
    L, l1, l2 = scan_late(D, late)
    S["поздние данные"] = False
    print(f"\nполная история: проверок {len(S)}; ярус 1: {int((S['ярус'] == 1).sum())} (шум: в среднем {n1.mean():.1f}, 95% {np.quantile(n1, 0.95):.0f}); "
          f"ярус 1–2: {int((S['ярус'] >= 1).sum())} (шум: {n2.mean():.1f}, 95% {np.quantile(n2, 0.95):.0f})", flush=True)
    print(f"поздние данные: проверок {len(L)}; ярус 1: {int((L['ярус'] == 1).sum()) if len(L) else 0} (шум: {l1.mean():.1f}, 95% {np.quantile(l1, 0.95):.0f}); "
          f"ярус 1–2: {int((L['ярус'] >= 1).sum()) if len(L) else 0} (шум: {l2.mean():.1f}, 95% {np.quantile(l2, 0.95):.0f})", flush=True)
    for tg in TARGETS:
        s, ll = S[S["цель"] == tg], L[L["цель"] == tg] if len(L) else L
        print(f"  {tg}: полная ярус 1 — {int((s['ярус'] == 1).sum())}, 1–2 — {int((s['ярус'] >= 1).sum())} из {len(s)}; "
              f"поздние ярус 1 — {int((ll['ярус'] == 1).sum()) if len(ll) else 0}, 1–2 — {int((ll['ярус'] >= 1).sum()) if len(ll) else 0} из {len(ll)}", flush=True)
    if len(L):
        print("\n== поздние данные: ярус 1–2 ==", flush=True)
        print(L[L["ярус"] >= 1][["тип", "цель", "признак", "ярус", "с", "граница", "r открытие", "p открытие", "n", "r 2023–26", "p 2023–26", "n2"]].round(4).to_string(index=False), flush=True)
    S = pd.concat([S, L], ignore_index=True)
    S.to_csv(OUT / "trade_scan_all.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")
    export_ref(D, S[~S["поздние данные"].astype(bool)], REF)
    for tg in TARGETS:
        s = S[S["цель"] == tg]
        print(f"  {tg}: ярус 1 — {int((s['ярус'] == 1).sum())}, ярус 1–2 — {int((s['ярус'] >= 1).sum())} из {len(s)}", flush=True)
    show = ["тип", "цель", "признак", "ярус", "только Binance", "r открытие", "p открытие", "r 2023–26", "p 2023–26", "r Bitstamp", "p Bitstamp", "медиана у лучших 20%", "медиана у худших 20%"]
    print("\n== ярус 1 ==", flush=True)
    print(S[S["ярус"] == 1][show].round(4).to_string(index=False), flush=True)
    print("\n== ярус 2 (кандидаты) ==", flush=True)
    print(S[S["ярус"] == 2][show].round(4).to_string(index=False), flush=True)
    I = improve(D, S)
    if len(I):
        I.to_csv(OUT / "trade_scan_improve.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")
        print("\n== слой 2: улучшение по признакам яруса 1 ==", flush=True)
        print(I.to_string(index=False), flush=True)
    for typ in TYPES:
        print(f"\n== портрет: {typ}, открытие 2018–22, лучшие 20% против худших 20% (описание, не проверка) ==", flush=True)
        print(portrait(D, feats, typ).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
