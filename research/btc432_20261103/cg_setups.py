"""432 BTC на H4 и H1 (лонг и зеркальный шорт) в окне CoinGlass: признаки CoinGlass и «примеры поведения» оператора
K1–K6 (формулировки 02.11, cg_claims.py) в момент входа и выхода — какие сетапы отрабатывают лучше. Правила — PREREG.md.
Описательно: сделок единицы–десятки. Запуск: cg_setups.py --pk-btc=<bars_*.pkl BTC>"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "tv_lab_1025"))
sys.path.insert(0, str(ROOT / "research" / "market_regimes_20261102"))
import strategies as S  # noqa: E402
from cg_claims import CLAIMS, load_cg  # noqa: E402

OUT = HERE / "out"
COST = 0.00048 + 0.0002
T0 = int(pd.Timestamp("2026-05-01 17:00", tz="UTC").timestamp())
T1 = int(pd.Timestamp("2026-10-28 15:00", tz="UTC").timestamp())
RNG = np.random.default_rng(20261103)
FOR = {1: ("K1", "K4"), -1: ("K2", "K3", "K5")}          # «за» сторону сделки
AGAINST = {1: ("K2", "K3", "K5"), -1: ("K1", "K4")}


def trades(b: pd.DataFrame, fund: pd.Series, side: int, sec: int) -> list:
    o, h, l, c = (b[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = b.index.to_numpy()
    hi30 = pd.Series(h).shift(1).rolling(30).max().to_numpy()
    lo30 = pd.Series(l).shift(1).rolling(30).min().to_numpy()
    atr, e200, adx = S.atr(h, l, c, 14), S.ema(c, 200), S.dmi(h, l, c, 14, 14)[2]
    with np.errstate(invalid="ignore", divide="ignore"):
        if side == 1:
            ent = (c > hi30) & (adx >= 22) & (c > e200) & ((c - hi30) / atr >= 0.5)
        else:
            ent = (c < lo30) & (adx >= 22) & (c < e200) & ((lo30 - c) / atr >= 0.5)
    ent[:300] = False
    f = fund[~fund.index.duplicated(keep="last")]
    ft, cs = f.index.to_numpy(), np.r_[0.0, np.cumsum(f.to_numpy())]
    out, pos = [], None
    for i in range(len(c) - 1):
        if pos is not None:
            j, s = pos
            if (c[i] < lo30[i] if side == 1 else c[i] > hi30[i]) or i - s >= 20:
                k = i + 1
                fs = cs[np.searchsorted(ft, t[k])] - cs[np.searchsorted(ft, t[j])]
                out.append({"te": int(t[j]), "tx": int(t[k]), "side": side,
                            "net": side * (o[k] / o[j] - 1) - 2 * COST - side * fs,
                            "fwd20_after": side * (o[min(k + 20, len(o) - 1)] / o[k] - 1)})
                pos = None
                continue
        if pos is None and ent[i]:
            pos = (i + 1, i)
    return [x for x in out if T0 <= x["te"] < T1]


def main():
    OUT.mkdir(exist_ok=True)
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    del m
    print(f"кэш {pk.name}: sha256 {hashlib.sha256(pk.read_bytes()).hexdigest()[:16]}…", flush=True)
    F = load_cg("BTCUSDT")
    flags = pd.DataFrame({k: v[1](F).astype(float).where(F["c"].notna()) for k, v in CLAIMS.items()}, index=F.index)
    flags24 = flags.rolling(24, min_periods=1).max()                     # был ли флаг в последние 24 закрытых часа
    feats = pd.DataFrame(index=F.index)
    feats["поток24"] = F["tk24"]
    feats["ликв_лонгов_доля24"] = F["liqL24"] / (F["liqL24"] + F["liqS24"])
    feats["ΔOI24"] = F["doi"].rolling(24).sum()
    feats["фандинг"] = F["fr"]
    feats["стакан24"] = F["ba24"]
    feats["WI2"] = F["wi2"]
    feats["LS_акк"] = F["ls_acc"]
    feats["LS_топ"] = F["ls_top"]
    feats["ход24"] = F["ret24"]
    pct = feats.rank(pct=True)
    known = F.index.to_numpy() + 3600

    def at(T):
        i = int(np.searchsorted(known, T, side="right")) - 1
        return i if i >= 0 and T - known[i] <= 3600 else None

    rows = []
    for tf, b, sec in (("H4", h4, 14400), ("H1", h1, 3600)):
        for side in (1, -1):
            for x in trades(b, fund, side, sec):
                ie, ix = at(x["te"]), at(x["tx"])
                r = {"tf": tf, **x, "entry": str(pd.to_datetime(x["te"], unit="s")),
                     "exit": str(pd.to_datetime(x["tx"], unit="s"))}
                for pre, i in (("in", ie), ("out", ix)):
                    if i is None:
                        continue
                    for k in CLAIMS:
                        r[f"{pre}_{k}"] = flags24.iloc[i][k]
                    for k in feats.columns:
                        r[f"{pre}_{k}"] = feats.iloc[i][k]
                        r[f"{pre}_p_{k}"] = pct.iloc[i][k]
                if ie is not None:
                    r["за"] = int(any(r.get(f"in_{k}") == 1 for k in FOR[side]))
                    r["против"] = int(any(r.get(f"in_{k}") == 1 for k in AGAINST[side]))
                    r["флет_K6"] = int(r.get("in_K6") == 1)
                rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "cg_setups_trades.csv", index=False)

    res = {}
    print("\n| ТФ | Сторона | Сделок | Сумма net % | Плюсовых | С чтением «за»: n · ср. net % | Без: n · ср. % | "
          "С чтением «против»: n · ср. % | Без: n · ср. % | K6 «флет»: n · ср. % |")
    print("|---|---|---:|---:|---:|---|---|---|---|---|")
    for (tf, side), g in df.groupby(["tf", "side"]):
        g = g.dropna(subset=["за"])

        def cell(m):
            x = g.loc[m, "net"]
            return f"{len(x)} · {100 * x.mean():+.2f}" if len(x) else "0 · —"
        print(f"| {tf} | {'лонг' if side == 1 else 'шорт'} | {len(g)} | {100 * g['net'].sum():+.1f} | "
              f"{int((g['net'] > 0).sum())} | {cell(g['за'] == 1)} | {cell(g['за'] == 0)} | {cell(g['против'] == 1)} | "
              f"{cell(g['против'] == 0)} | {cell(g['флет_K6'] == 1)} |")
        per_k = {}
        for k in CLAIMS:
            m = g[f"in_{k}"] == 1
            per_k[k] = {"n": int(m.sum()), "mean_pct": float(100 * g.loc[m, "net"].mean()) if m.any() else None,
                        "rest_mean_pct": float(100 * g.loc[~m, "net"].mean()) if (~m).any() else None}
        med = {}
        for k in feats.columns:
            w, lo = g[g["net"] > 0][f"in_p_{k}"], g[g["net"] <= 0][f"in_p_{k}"]
            med[k] = (round(float(w.median()), 2) if len(w) else None, round(float(lo.median()), 2) if len(lo) else None)
        res[f"{tf}_{side}"] = {"n": len(g), "sum_pct": float(100 * g["net"].sum()), "per_claim": per_k,
                               "entry_pct_win_vs_loss": med}
    (OUT / "cg_setups.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    for key, r in res.items():
        print(f"\n{key}: n {r['n']}, сумма {r['sum_pct']:+.1f}%")
        print("  по чтениям K (n · ср. net с флагом / без):",
              "; ".join(f"{k} {v['n']} · {v['mean_pct'] if v['mean_pct'] is None else round(v['mean_pct'], 2)} / "
                        f"{v['rest_mean_pct'] if v['rest_mean_pct'] is None else round(v['rest_mean_pct'], 2)}"
                        for k, v in r["per_claim"].items()))
        print("  перцентили на входе, медиана плюсовых / минусовых:",
              "; ".join(f"{k} {a}/{b}" for k, (a, b) in r["entry_pct_win_vs_loss"].items()))


if __name__ == "__main__":
    main()
