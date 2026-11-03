"""Критерий перспективной проверки H4-432 + ADX3 на истории: сколько ждать и различает ли он. Правила — PREREG.md.
Запуск: criterion_power.py --pk-btc=<bars_*.pkl BTC из mr_data.build>   (nice 20)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "tv_lab_1025"))
sys.path.insert(0, str(ROOT / "research" / "btc432_20261103"))
from review import COST, H4, Data, run  # noqa: E402

RNG = np.random.default_rng(20261103)
NMASK = 300
BIG = 0.05                       # крупный выигрыш: net ≥ 5 USDT на 100 USDT номинала
DAY = 86400


class Sim:
    def __init__(self, D: Data):
        self.D = D
        n = len(D.c)
        self.n = n
        chan = np.nan_to_num(D.c < D.lo30, nan=False).astype(bool)
        self.nextchan = self._next(chan)
        self.base = D.ent[1].copy()
        self.base[-1] = False
        adx3 = np.zeros(n, bool)
        adx3[3:] = D.adx[3:] > D.adx[:-3]
        self.adx3 = self.base & adx3
        self.fc = D.fcum(D.t + H4)                    # накопленный фандинг на закрытии бара
        self.fo = D.fcum(D.t)                         # … на открытии бара

    def _next(self, m):
        idx = np.where(m, np.arange(self.n), self.n)
        return np.minimum.accumulate(idx[::-1])[::-1]

    def trades(self, nextsig, s0):
        """Сделки политики со старта без позиции на баре s0 (первое решение — на закрытии s0): (сигнал, вход j, выход k)."""
        out, i, n = [], s0, self.n
        while i < n - 1:
            s = nextsig[i]
            if s >= n - 1:
                break
            j = s + 1
            q = min(self.nextchan[j] if j < n else n, s + 20)
            k = q + 1
            out.append((s, j, k))
            i = q + 1
        return out

    def net(self, j, k):
        D = self.D
        k = min(k, self.n - 1)
        return D.o[k] / D.o[j] - 1 - 2 * COST - (self.fo[k] - self.fo[j])

    def window(self, tr, s0, E):
        """Итог и просадка на [s0, E]: переоценка закрытий H4 с фандингом; открытое на E — модельное закрытие по open E."""
        D = self.D
        L = E - s0
        eq = np.zeros(L + 1)                         # eq[0] = 0 (старт); eq[x] — после закрытия бара s0+x−1
        done, model, nets = 0.0, 0.0, []
        for s, j, k in tr:
            if j >= E:
                break
            px = D.o[j]
            b = np.arange(j, min(k, E))
            eq[b - s0 + 1] += D.c[b] / px - 1 - COST - (self.fc[b] - self.fo[j])
            if k <= E:
                v = self.net(j, k)
                eq[k - s0 + 1:] += v                 # закрыта на open k: с закрытия бара k — в итоге
                done += v
                nets.append((s, j, k, v, True))
            else:
                v = D.o[E] / px - 1 - 2 * COST - (self.fo[E] - self.fo[j])
                model += v
                nets.append((s, j, k, v, False))
        eq[L] = done + model                         # точка E: закрытое + модельное закрытие открытого по open E
        dd = float(np.max(np.maximum.accumulate(eq) - eq))
        return done + model, dd, nets, model


def episodes(tb, tf):
    """Эпизоды расхождения: объединение интервалов [вход, выход) сделок, которые есть только у одной политики."""
    sb, sf = {(j, k) for _s, j, k, *_ in tb}, {(j, k) for _s, j, k, *_ in tf}
    iv = sorted([(j, k) for j, k in sb ^ sf])
    eps = []
    for j, k in iv:
        if eps and j < eps[-1][1]:
            eps[-1][1] = max(eps[-1][1], k)
        else:
            eps.append([j, k])
    return eps


def evaluate(S: Sim, nb, nf, s0, E):
    vb, ddb, tb, mb = S.window(nb, s0, E)
    vf, ddf, tf, mf = S.window(nf, s0, E)
    ent_f = {j for _s, j, _k, _v, _c in tf}
    big = [(j, k, v) for _s, j, k, v, closed in tb if closed and v >= BIG]
    ok_core = (vf > 0) and (vf > vb) and (ddf <= ddb)
    res = {"vb": vb, "vf": vf, "ddb": ddb, "ddf": ddf, "nbig": len(big), "core": ok_core,
           "n_b": sum(1 for *_x, c in tb if c), "n_f": sum(1 for *_x, c in tf if c),
           "direct_rej": sum(1 for _s, j, *_r in tb if j not in ent_f)}   # входы только базы (отказ + занятость)
    if not big:
        for key in "abc":
            res[key] = ok_core
        res.update(ret_a=np.nan, ret_b=np.nan, ret_c=np.nan)
        return res
    tot = sum(v for *_x, v in big)
    taken = [(j, k, v) for j, k, v in big if j in ent_f]
    ret_a = 1.0 if taken else np.nan                           # «по совпавшим входам» — у совпавших net одинаков
    ret_b = sum(v for *_x, v in taken) / tot
    eps = episodes(tb, tf)
    num_c = sum(v for j, _k, v in taken)
    for a, b in eps:
        if any(a <= j < b for j, _k, _v in big if j not in ent_f):
            num_c += sum(v for _s, j, _k, v, _c in tf if a <= j < b)
    ret_c = num_c / tot
    res.update(ret_a=ret_a, ret_b=ret_b, ret_c=ret_c,
               a=ok_core and (np.isnan(ret_a) or ret_a >= 0.8), b=ok_core and ret_b >= 0.8, c=ok_core and ret_c >= 0.8)
    return res


def main():
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    D = Data(pk)
    S = Sim(D)
    ref = [(u["j"], u["k"]) for u in run(D, 1)]
    mine = [(j, min(k, S.n - 1)) for _s, j, k in S.trades(S._next(S.base), 0)]
    print(f"движок = review.run: {mine == ref} ({len(mine)} против {len(ref)})", flush=True)
    if mine != ref:
        sys.exit("движок не повторяет review.run — отказ")

    nb_all = S.trades(S._next(S.base), 0)
    p = float(np.mean([not S.adx3[s] for s, _j, _k in nb_all]))
    print(f"доля сигналов сделок базы с ADX[t] ≤ ADX[t−3]: {p:.3f} ({len(nb_all)} сделок)", flush=True)

    t = D.t
    months = pd.date_range("2018-01-01", "2026-11-01", freq="MS", tz="UTC")
    nb_next, nf_next = S._next(S.base), S._next(S.adx3)
    masks = [S._next(S.base & (RNG.random(S.n) >= p)) for _ in range(NMASK)]

    rows = []
    for m0 in months:
        s0 = int(np.searchsorted(t, m0.timestamp()))
        tb = S.trades(nb_next, s0)
        ks = [k for _s, _j, k in tb if k <= S.n - 1]
        if len(ks) < 20:
            break
        E = max(ks[19], int(np.searchsorted(t, t[s0] + 90 * DAY)))
        if E >= S.n - 1:
            break
        r = evaluate(S, tb, S.trades(nf_next, s0), s0, E)
        r.update(start=str(m0.date()), months=(t[E] - t[s0]) / DAY / 30.44)
        nul = [evaluate(S, tb, S.trades(mk, s0), s0, E) for mk in masks]
        dv = np.array([x["vf"] - x["vb"] for x in nul])
        r["rank_dnet"] = float((1 + np.sum(dv >= r["vf"] - r["vb"])) / (NMASK + 1))
        for key in ("core", "a", "b", "c"):
            r[f"null_{key}"] = float(np.mean([x[key] for x in nul]))
        r["null_dd_le"] = float(np.mean([x["ddf"] <= x["ddb"] for x in nul]))
        r["null_net_gt"] = float(np.mean([x["vf"] > x["vb"] for x in nul]))
        r["null_direct_rej"] = float(np.mean([x["direct_rej"] for x in nul]))
        rows.append(r)
        print(f"{r['start']}: {r['months']:.1f} мес, база {100 * r['vb']:+.1f}/DD {100 * r['ddb']:.1f}, ADX3 "
              f"{100 * r['vf']:+.1f}/DD {100 * r['ddf']:.1f}, отказов {r['direct_rej']}, крупных {r['nbig']}, "
              f"b {r['ret_b']:.2f} c {r['ret_c']:.2f} → a/b/c {int(r['a'])}{int(r['b'])}{int(r['c'])}; "
              f"случайный a/b/c {r['null_a']:.2f}/{r['null_b']:.2f}/{r['null_c']:.2f}; ранг Δnet {r['rank_dnet']:.2f}",
              flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "out_windows.csv", index=False)
    df["year"] = df["start"].str[:4]
    summ = {
        "windows": len(df), "p_reject": p,
        "months_to_eval": {"median": float(df["months"].median()), "min": float(df["months"].min()), "max": float(df["months"].max())},
        "adx3": {k: float(df[k].mean()) for k in ("core", "a", "b", "c")},
        "null": {k: float(df[f"null_{k}"].mean()) for k in ("core", "a", "b", "c")},
        "adx3_dd_le": float((df["ddf"] <= df["ddb"]).mean()), "null_dd_le": float(df["null_dd_le"].mean()),
        "adx3_net_gt": float((df["vf"] > df["vb"]).mean()), "null_net_gt": float(df["null_net_gt"].mean()),
        "rank_le_010": float((df["rank_dnet"] <= 0.10).mean()), "rank_median": float(df["rank_dnet"].median()),
        "direct_rej_median": float(df["direct_rej"].median()), "nbig_median": float(df["nbig"].median()),
        "by_year": {y: {"n": int(len(g)), "adx3_b": float(g["b"].mean()), "null_b": float(g["null_b"].mean()),
                        "adx3_c": float(g["c"].mean()), "null_c": float(g["null_c"].mean()),
                        "rank_med": float(g["rank_dnet"].median())} for y, g in df.groupby("year")},
    }
    (HERE / "out_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1))
    print(json.dumps(summ, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
