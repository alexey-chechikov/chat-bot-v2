"""PREREG_alts_vs_btc_1108.md: альты против BTC по системе — независимость, противовес, сдвиг, проверка вне выборки."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import top_fetch as tf  # noqa: E402
import top_run as tr  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 100)
CACHE = tf.DIR / "alts_vs_btc.pkl"
MID = pd.Timestamp("2023-09-01")


def series(a, f, legs):
    eq = pl.curve(a, f, legs)
    b = a["i0"]
    idx = pd.to_datetime(a["t"][b:], unit="s")
    pnl = pd.Series(eq[b:] - eq[b], index=idx).resample("1D").last().ffill().diff().dropna()
    pos = np.zeros(len(a["t"]))
    for x in legs:
        pos[x[0]:x[1]] += x[4] * x[7]
    side = pd.Series(np.sign(pos[b:]), index=idx).resample("4h").last()
    return pnl, side


def build():
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    out = {}
    a, f, _ = sc.load_coin("BTC")
    out["BTC"] = series(a, f, tr.system(a))
    for c in tf.TOP[1:]:
        a, f = tr.load(c + "USDT")
        out[c] = series(a, f, tr.system(a))
        print(c, "готово", flush=True)
    CACHE.write_bytes(pickle.dumps(out))
    return out


def dd(x):
    x = np.cumsum(np.asarray(x, float))
    return float((x - np.maximum.accumulate(np.r_[0.0, x])[1:]).min())


def main():
    S = build()
    btc_p, btc_s = S["BTC"]
    alts = [c for c in tf.TOP[1:]]
    rows = []
    bm = btc_p.resample("ME").sum()
    for c in alts:
        p, s = S[c]
        d = pd.concat([p, btc_p], axis=1, keys=["a", "b"]).dropna()
        h1, h2 = d[d.index < MID], d[d.index >= MID]
        m = pd.concat([p.resample("ME").sum(), bm], axis=1, keys=["a", "b"]).dropna()
        neg = m[m["b"] < 0]
        n1, n2 = neg[neg.index < MID], neg[neg.index >= MID]
        ss = pd.concat([s, btc_s], axis=1, keys=["a", "b"]).dropna()
        lag = {k: ss["a"].corr(ss["b"].shift(k)) for k in range(-12, 31)}
        kbest = max(lag, key=lambda k: lag[k])
        rows.append({
            "монета": c, "итог": round(float(p.sum())), "п1": round(float(h1["a"].sum())), "п2": round(float(h2["a"].sum())),
            "связь": round(float(d["a"].corr(d["b"])), 2), "связь п1": round(float(h1["a"].corr(h1["b"])), 2) if len(h1) > 60 else np.nan, "связь п2": round(float(h2["a"].corr(h2["b"])), 2),
            "BTC− мес": len(neg), "альт в эти мес": round(float(neg["a"].sum())), "п1 в BTC−": round(float(n1["a"].sum())), "п2 в BTC−": round(float(n2["a"].sum())),
            "доля + в BTC−": round(float((neg["a"] > 0).mean()), 2),
            "позиция k=0": round(float(lag[0]), 2), "лучший k (4ч)": kbest, "связь при k": round(float(lag[kbest]), 2),
            "мес +1": round(float(m["a"].corr(m["b"].shift(1))), 2), "мес +2": round(float(m["a"].corr(m["b"].shift(2))), 2),
        })
    d = pd.DataFrame(rows).sort_values("связь")
    d.to_csv(Path(__file__).parent / "out" / "alts_vs_btc.csv", index=False)
    print(d.to_string(index=False), flush=True)
    both = d.dropna(subset=["связь п1"])
    print("ранговая связь порядка «связи с BTC» между половинами:", round(float(both["связь п1"].rank().corr(both["связь п2"].rank())), 2), "монет", len(both), flush=True)
    print("ранговая связь «альт в месяцы BTC−» между половинами:", round(float(both["п1 в BTC−"].rank().corr(both["п2 в BTC−"].rank())), 2), flush=True)
    print("месяцев BTC в минусе:", int((bm < 0).sum()), "из", len(bm), "сумма BTC в них", round(float(bm[bm < 0].sum())), flush=True)

    # вне выборки: выбор по первой половине, проверка на второй
    pick = both[(both["п1"] > 0)].nsmallest(5, "связь п1")["монета"].tolist()
    pool = both["монета"].tolist()
    P = pd.DataFrame({c: S[c][0] for c in ["BTC"] + pool}).fillna(0.0)
    P2 = P[P.index >= MID]

    def score(cols):
        x = P2[["BTC"] + list(cols)].sum(1)
        return float(x.sum()), dd(x)

    tot, dmax = score(pick)
    rng = np.random.default_rng(20261108)
    ctl = []
    for _ in range(999):
        t2, d2 = score(rng.choice(pool, 5, replace=False))
        ctl.append((t2, d2, t2 / abs(d2)))
    ctl = np.array(ctl)
    b_tot, b_dd = float(P2["BTC"].sum()), dd(P2["BTC"])
    print(f"выбор по первой половине (итог > 0, меньше всех связаны с BTC): {pick}", flush=True)
    print(f"вторая половина: BTC один {b_tot:+.0f} / {b_dd:.0f} (отн {b_tot / abs(b_dd):.2f}); BTC + выбранные {tot:+.0f} / {dmax:.0f} (отн {tot / abs(dmax):.2f})", flush=True)
    print(f"BTC + 5 случайных: медиана {np.median(ctl[:, 0]):+.0f} / {np.median(ctl[:, 1]):.0f} (отн {np.median(ctl[:, 2]):.2f}); выбранные лучше случайных по итогу в {(ctl[:, 0] < tot).mean() * 100:.1f}%, по отношению в {(ctl[:, 2] < tot / abs(dmax)).mean() * 100:.1f}%", flush=True)
    for c in pick:
        r = d.set_index("монета").loc[c]
        print(f"  {c}: связь п1 {r['связь п1']}, п2 {r['связь п2']}; итог п1 {r['п1']:+}, п2 {r['п2']:+}", flush=True)


if __name__ == "__main__":
    main()
