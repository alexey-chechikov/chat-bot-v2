"""Поток тейкеров, OI и фандинг на входах 432 BTC (H1 — проверка, H4 — описательно). Правила — PREREG.md (дописка до запуска).
Запуск: flow_oi.py --pk-btc=<pkl> --um=<BTCUSDT_UM_1m.csv> --oi=<BTCUSDT_oi_5min.csv>"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "research" / "operator_rules_20261103"))
from sweep import TF, ref432  # noqa: E402

RNG = np.random.default_rng(20261103)
SPLIT = int(pd.Timestamp("2025-07-01", tz="UTC").timestamp())


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main():
    a = dict(x.lstrip("-").split("=", 1) for x in sys.argv[1:])
    pk, um, oi = Path(a["pk-btc"]), Path(a["um"]), Path(a["oi"])
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    del m
    u = pd.read_csv(um, usecols=["ts", "close", "volume", "taker_buy"])
    o = pd.read_csv(oi)
    print(f"UM 1m {um.name}: {len(u)} строк sha {sha(um)}…, {pd.to_datetime(u.ts.iloc[0], unit='ms')} → "
          f"{pd.to_datetime(u.ts.iloc[-1], unit='ms')}; OI {oi.name}: {len(o)} строк sha {sha(oi)}…, "
          f"→ {pd.to_datetime(o.ts.iloc[-1], unit='ms')}", flush=True)
    ut = u["ts"].to_numpy() // 1000
    cv, cb = np.r_[0.0, np.cumsum(u["volume"].to_numpy())], np.r_[0.0, np.cumsum(u["taker_buy"].to_numpy())]
    uc = u["close"].to_numpy()
    ot, ov = o["ts"].to_numpy() // 1000, o["open_interest"].to_numpy(float)
    f = fund[~fund.index.duplicated(keep="last")]
    ft, fr = f.index.to_numpy(), f.to_numpy()

    def flow(T, hours):
        a_, b_ = np.searchsorted(ut, T - hours * 3600), np.searchsorted(ut, T)    # минуты [T−h, T)
        vol = cv[b_] - cv[a_]
        return (2 * (cb[b_] - cb[a_]) - vol) / vol if vol > 0 and b_ - a_ >= hours * 50 else np.nan

    def doi(T, hours):
        i1, i0 = np.searchsorted(ot, T, side="right") - 1, np.searchsorted(ot, T - hours * 3600, side="right") - 1
        if i1 < 0 or i0 < 0 or T - ot[i1] > 900 or (T - hours * 3600) - ot[i0] > 900:
            return np.nan
        return ov[i1] / ov[i0] - 1

    def ret24(T):
        i1, i0 = np.searchsorted(ut, T) - 1, np.searchsorted(ut, T - 86400) - 1
        return uc[i1] / uc[i0] - 1 if i1 >= 0 and i0 >= 0 else np.nan

    res = {}
    for tfn, b in (("H1", h1), ("H4", h4)):
        tf = TF(tfn, b, h4, fund)
        rows = [r for r in ref432(tf, 1) if ut[0] + 86400 <= tf.t[r[0]] <= ut[-1]]
        recs = []
        for j, k, net, _w in rows:
            T = int(tf.t[j])
            fi = np.searchsorted(ft, T, side="right") - 1
            tk24, r24 = flow(T, 24), ret24(T)
            recs.append({"T": T, "net": net, "поток6": flow(T, 6), "поток24": tk24, "ΔOI6": doi(T, 6), "ΔOI24": doi(T, 24),
                         "фандинг": fr[fi] if fi >= 0 else np.nan, "K2": float(r24 >= 0.02 and tk24 < 0) if np.isfinite(tk24) else np.nan})
        df = pd.DataFrame(recs)
        df.to_csv(HERE / "out" / f"flow_oi_{tfn}.csv", index=False)
        fmed = df["фандинг"].median()
        tests = {"поток6 > 0": df["поток6"] > 0, "поток24 > 0": df["поток24"] > 0, "ΔOI6 > 0": df["ΔOI6"] > 0,
                 "ΔOI24 > 0": df["ΔOI24"] > 0, "фандинг выше медианы": df["фандинг"] > fmed, "K2 продажи на росте": df["K2"] == 1}
        cols = {"поток6 > 0": "поток6", "поток24 > 0": "поток24", "ΔOI6 > 0": "ΔOI6", "ΔOI24 > 0": "ΔOI24",
                "фандинг выше медианы": "фандинг", "K2 продажи на росте": "K2"}
        out = {"n": len(df), "sum_pct": 100 * float(df["net"].sum()), "mean_pct": 100 * float(df["net"].mean())}
        print(f"\n== 432 {tfn} лонг, сделок {len(df)}, сумма {out['sum_pct']:+.1f}%, среднее {out['mean_pct']:+.2f}%")
        print("| Признак на входе | да: n · ср. net % | нет: n · ср. % | разница п.п. | p | 1-я половина | 2-я половина |")
        print("|---|---|---|---:|---:|---:|---:|")
        for nm, g in tests.items():
            ok = df[cols[nm]].notna().to_numpy()
            y, gg = df["net"].to_numpy()[ok], g.to_numpy()[ok].astype(bool)
            h = df["T"].to_numpy()[ok] >= SPLIT
            if gg.sum() < 3 or (~gg).sum() < 3:
                print(f"| {nm} | {int(gg.sum())} | {int((~gg).sum())} | — | — | — | — |")
                continue
            d = y[gg].mean() - y[~gg].mean()
            p = None
            if gg.sum() >= 10 and (~gg).sum() >= 10:
                cnt = sum(abs(y[q].mean() - y[~q].mean()) >= abs(d) - 1e-15 for q in (RNG.permutation(gg) for _ in range(9999)))
                p = (cnt + 1) / 10000
            hs = []
            for m_ in (~h, h):
                a1, a0 = y[m_ & gg], y[m_ & ~gg]
                hs.append(100 * (a1.mean() - a0.mean()) if len(a1) >= 3 and len(a0) >= 3 else np.nan)
            out[nm] = {"n_yes": int(gg.sum()), "n_no": int((~gg).sum()), "diff_pct": 100 * d, "p": p, "halves": hs}
            print(f"| {nm} | {int(gg.sum())} · {100 * y[gg].mean():+.2f} | {int((~gg).sum())} · {100 * y[~gg].mean():+.2f} | "
                  f"{100 * d:+.2f} | {'—' if p is None else f'{p:.3f}'} | {hs[0]:+.2f} | {hs[1]:+.2f} |")
        res[tfn] = out
    (HERE / "out" / "flow_oi.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
