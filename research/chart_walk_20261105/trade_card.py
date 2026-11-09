"""Карточка сделки: все признаки одного входа и где каждый стоит среди сделок того же типа (перцентиль, медианы лучших
и худших 20%), с ярусом из trade_scan (держится ли связь на других годах). Источник — история out/trade_table_btc.pkl
или живой журнал службы state/btc_signals_features.jsonl.
  python trade_card.py --last                 последний живой вход
  python trade_card.py --at "2025-11-13 08:00" вход из истории (Binance, время закрытия 4ч UTC)
  python trade_card.py --live-csv             живой журнал → out/trade_table_live.csv (Excel)"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "out"
FEAT_LIVE = Path("/Users/alexeychechikov/code/bot7/state/btc_signals_features.jsonl")
sys.path.insert(0, str(HERE))
import trade_scan as ts  # noqa: E402

pd.set_option("display.width", 220, "display.max_rows", 300, "display.max_colwidth", 40)


def live_rows() -> list[dict]:
    if not FEAT_LIVE.exists():
        return []
    return [json.loads(x) for x in FEAT_LIVE.read_text().splitlines() if x.strip()]


def live_table() -> pd.DataFrame:
    rows = live_rows()
    ent = {r["key"].split("|", 1)[1]: r for r in rows if r["kind"] == "вход"}
    out = []
    for r in rows:
        if r["kind"] != "вход":
            continue
        d = {"ряд": "живой", "стратегия": r["strategy"], "тип": f"{'лонг' if r['side'] == 1 else 'шорт'} {r['tag']}", "вход UTC": r["utc"], "цена входа": r["px"],
             "балл M2 (тень)": r.get("m2_score"), "ошибка": r.get("error")}
        ex = next((x for x in rows if x["kind"] == "выход" and x.get("entry_t") == r["t"] and x["tag"] == r["tag"]), None)
        if ex:
            d.update({"выход UTC": ex["utc"], "цена выхода": ex["px"], "итог, % базы": ex.get("res"), "причина выхода": ex.get("why")})
            d.update(ex.get("path") or {})
        d.update(r.get("features") or {})
        out.append(d)
    _ = ent
    return pd.DataFrame(out)


def card(x: pd.Series, D: pd.DataFrame, S: pd.DataFrame | None) -> pd.DataFrame:
    typ = x["тип"]
    d = D[D["тип"] == typ]
    y = d["итог, % базы"].to_numpy(float)
    best, worst = d[y >= np.quantile(y, 0.8)], d[y <= np.quantile(y, 0.2)]
    feats = [c for c in d.columns if c not in ts.OUTCOME and not c.startswith("_") and pd.api.types.is_numeric_dtype(d[c]) and c in x.index]
    rows = []
    for ft in feats:
        v = x[ft]
        col = d[ft].to_numpy(float)
        col = col[np.isfinite(col)]
        if v is None or not np.isfinite(float(v)) or not len(col):
            continue
        tier = ""
        if S is not None:
            s = S[(S["тип"] == typ) & (S["признак"] == ft) & (S["ярус"] >= 1)]
            tier = ", ".join(f"{r['цель'].split(',')[0]}: ярус {r['ярус']} ({'+' if r['r открытие'] > 0 else '−'})" for _, r in s.iterrows())
        rows.append({"признак": ft, "значение": round(float(v), 3), "перцентиль в типе": round(float((col < float(v)).mean() * 100)),
                     "медиана лучших 20%": round(float(best[ft].median()), 3), "медиана худших 20%": round(float(worst[ft].median()), 3), "связь держится": tier})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at")
    ap.add_argument("--last", action="store_true")
    ap.add_argument("--live-csv", action="store_true")
    args = ap.parse_args()
    D = pd.read_pickle(OUT / "trade_table_btc.pkl")
    S = pd.read_csv(OUT / "trade_scan_all.csv", sep=";", decimal=",") if (OUT / "trade_scan_all.csv").exists() else None
    if args.live_csv:
        L = live_table()
        L.to_csv(OUT / "trade_table_live.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig", float_format="%.4f")
        print(f"живых входов {len(L)} → {OUT / 'trade_table_live.csv'}")
        return
    if args.last:
        L = live_table()
        if L.empty:
            print("живых входов в журнале признаков пока нет")
            return
        x = L.iloc[-1]
    else:
        m = D[(D["ряд"] == "Binance") & (D["вход UTC"] == args.at)]
        if m.empty:
            print("нет входа в это время; ближайшие:", D[D["ряд"] == "Binance"]["вход UTC"].iloc[-5:].tolist())
            return
        x = m.iloc[0]
    print(f"{x['тип']} — вход {x['вход UTC']} по {x['цена входа']:.0f}" + (f", итог {x['итог, % базы']:+.2f}% базы" if pd.notna(x.get("итог, % базы")) else ", открыта"))
    C = card(x, D, S)
    print(C.to_string(index=False))
    C.to_csv(OUT / "trade_card_last.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
