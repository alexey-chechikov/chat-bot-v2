"""Правила оператора (возврат к каналу / отбой от голубой EMA200, лонг и шорт) на BTC H1 и H4: перебор 1 944 вариантов,
отбор A → B → C, контроль случайным входом и соседи. Правила — PREREG.md (записаны до запуска).
Запуск: sweep.py --pk-btc=<bars_*.pkl BTC из mr_data.build>   (nice 20)."""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "tv_lab_1025"))
import strategies as S  # noqa: E402

OUT = HERE / "out"
COST_T, COST_M = 0.00048 + 0.0002, 0.00016
TOL, MIN_TP = 0.0015, 0.002
PER = {"A": ("2018-01-01", "2022-01-01"), "B": ("2022-01-01", "2024-08-01"), "C": ("2024-08-01", "2030-01-01")}
FAMS, NS, KS, XS, HOLDS, FLATS = ("канал", "отбой", "любое"), (1, 2, 3), (3, 5), (0.015, 0.03, None), (20, 40, None), (False, True)
RNG = np.random.default_rng(20261103)


def ts(s):
    return int(pd.Timestamp(s, tz="UTC").timestamp())


def runlen(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.int64)
    cs = np.cumsum(x)
    return cs - np.maximum.accumulate(np.where(x == 0, cs, 0))


def nxt(a: np.ndarray) -> np.ndarray:
    n = len(a)
    idx = np.where(a, np.arange(n), n)
    return np.minimum.accumulate(idx[::-1])[::-1]


def roll5(a: np.ndarray) -> np.ndarray:
    return pd.Series(a.astype(float)).rolling(5, min_periods=1).max().to_numpy() > 0


class TF:
    def __init__(self, name: str, b: pd.DataFrame, h4: pd.DataFrame, fund: pd.Series):
        self.name = name
        self.o, self.h, self.l, self.c = (b[k].to_numpy() for k in ("open", "high", "low", "close"))
        self.t = b.index.to_numpy()
        self.n = len(self.c)
        self.hi = pd.Series(self.h).shift(1).rolling(30).max().to_numpy()
        self.lo = pd.Series(self.l).shift(1).rolling(30).min().to_numpy()
        e = S.ema(self.c, 200)
        flat_e = np.abs(e / np.r_[np.full(5, np.nan), e[:-5]] - 1) <= 0.0015
        self.B, self.flat = {"свой": e}, {"свой": flat_e}
        if name == "H1":
            e4 = S.ema(h4["close"].to_numpy(), 200)
            f4 = np.abs(e4 / np.r_[np.full(5, np.nan), e4[:-5]] - 1) <= 0.0015
            j = np.searchsorted(h4["known"].to_numpy(), b["known"].to_numpy(), side="right") - 1
            ok = j >= 0
            self.B["H4"] = np.where(ok, e4[np.maximum(j, 0)], np.nan)
            self.flat["H4"] = np.where(ok, f4[np.maximum(j, 0)], False)
        f = fund[~fund.index.duplicated(keep="last")]
        self.ft, self.fcs = f.index.to_numpy(), np.r_[0.0, np.cumsum(f.to_numpy())]
        self.per = np.full(self.n, "", dtype=object)
        for p, (a, z) in PER.items():
            self.per[(self.t >= ts(a)) & (self.t < ts(z))] = p
        self._cut = {}

    def side_ok(self, side, blue):
        B = self.B[blue]
        with np.errstate(invalid="ignore"):
            return (self.c > B) if side == 1 else (self.c < B)

    def signal(self, side, blue, fam, N, flatf):
        B, c, h, l, hi, lo = self.B[blue], self.c, self.h, self.l, self.hi, self.lo
        with np.errstate(invalid="ignore"):
            if side == 1:
                t_ch, ch_ok, t_b = l <= lo * (1 + TOL), c > lo, l <= B * (1 + TOL)
            else:
                t_ch, ch_ok, t_b = h >= hi * (1 - TOL), c < hi, h >= B * (1 - TOL)
        conf = runlen(self.side_ok(side, blue)) >= N
        chan = roll5(t_ch) & conf & ch_ok
        bounce = roll5(t_b) & conf
        cond = chan if fam == "канал" else bounce if fam == "отбой" else (chan | bounce)
        if flatf:
            cond &= ~self.flat[blue].astype(bool)
        cond &= np.isfinite(hi) & np.isfinite(lo) & np.isfinite(B)
        sig = cond & ~np.r_[False, cond[:-1]]
        sig[:300] = False
        return sig

    def next_cut(self, side, blue, K, x):
        key = (side, blue, K, x)
        if key not in self._cut:
            B, c, o = self.B[blue], self.c, self.o
            with np.errstate(invalid="ignore"):
                opp = (c < B) if side == 1 else (c > B)
            cut = runlen(opp) >= K
            if x is not None:
                c5 = np.r_[np.full(5, np.nan), c[:-5]]
                with np.errstate(invalid="ignore"):
                    cut |= (side * (c / o - 1) <= -x) | (side * (c / c5 - 1) <= -x)
            self._cut[key] = nxt(cut)
        return self._cut[key]

    def trade(self, side, i, ncut, hold):
        """Сделка по сигналу на закрытии бара i → (вход, выход, net, причина) или None (цель слишком близко)."""
        o, h, l, n = self.o, self.h, self.l, self.n
        e = i + 1
        if e >= n:
            return None
        px = o[e]
        tp = self.hi[i] if side == 1 else self.lo[i]
        if side * (tp / px - 1) < MIN_TP:
            return None
        jc = ncut[e]
        x_cut = jc + 1 if jc < n - 1 else n
        x_time = e + hold if hold else n
        end = min(x_cut, x_time, n)
        seg = (h[e:end] >= tp * 1.0001) if side == 1 else (l[e:end] <= tp * 0.9999)
        if seg.any():
            j = e + int(np.argmax(seg))
            out = o[j] if side * (o[j] - tp) >= 0 else tp
            fee, xb, why = COST_M, j, "цель"
        elif end < n:
            out, fee, xb, why = o[end], COST_T, end, ("выход" if end == x_cut else "время")
        else:
            out, fee, xb, why = self.c[-1], COST_T, n - 1, "конец"
        fs = self.fcs[np.searchsorted(self.ft, self.t[xb])] - self.fcs[np.searchsorted(self.ft, self.t[e])]
        return e, xb, side * (out / px - 1) - COST_T - fee - side * fs, why

    def run(self, side, sig, ncut, hold):
        rows, free = [], 0
        for i in np.flatnonzero(sig):
            if i < free:
                continue
            r = self.trade(side, i, ncut, hold)
            if r is None:
                continue
            rows.append(r)
            free = r[1]
        return rows


def summarize(tf: TF, rows) -> dict:
    if not rows:
        return {p: {"n": 0, "sum": 0.0} for p in list(PER) + ["всё"]}
    e = np.array([r[0] for r in rows])
    net = np.array([r[2] for r in rows])
    per = tf.per[e]
    out = {}
    for p in PER:
        m = per == p
        out[p] = {"n": int(m.sum()), "sum": 100 * float(net[m].sum()), "mean": 100 * float(net[m].mean()) if m.any() else None,
                  "win": 100 * float((net[m] > 0).mean()) if m.any() else None}
    m = per != ""
    out["всё"] = {"n": int(m.sum()), "sum": 100 * float(net[m].sum()), "mean": 100 * float(net[m].mean()) if m.any() else None}
    return out


def boot_ci(x, reps=5000):
    m = RNG.choice(x, (reps, len(x))).mean(axis=1)
    return 100 * float(np.quantile(m, 0.025)), 100 * float(np.quantile(m, 0.975))


def control(tf: TF, v: dict, rows, reps=999) -> dict:
    """Случайный вход там, где выполнено условие стороны (и флет-фильтр варианта), те же выходы; ранг за C и за всё."""
    side, blue = v["side"], v["blue"]
    ok = tf.side_ok(side, blue) & np.isfinite(tf.hi) & np.isfinite(tf.lo)
    if v["flat"]:
        ok &= ~tf.flat[blue].astype(bool)
    ok[:300] = False
    ncut = tf.next_cut(side, blue, v["K"], v["x"])
    real = np.array([r[2] for r in rows])
    per = tf.per[np.array([r[0] for r in rows])]
    res = {}
    for scope, mask_p in (("C", per == "C"), ("всё", per != "")):
        k = int(mask_p.sum())
        if k < 5:
            continue
        pool = np.flatnonzero(ok & ((tf.per == "C") if scope == "C" else (tf.per != "")))
        pool = pool[pool < tf.n - 2]
        ctl = np.empty(reps)
        for r_ in range(reps):
            vals = []
            while len(vals) < k:
                tr = tf.trade(side, int(RNG.choice(pool)), ncut, v["hold"])
                if tr is not None:
                    vals.append(tr[2])
            ctl[r_] = np.mean(vals)
        rm = float(real[mask_p].mean())
        res[scope] = {"real_mean_pct": 100 * rm, "ctl_median_pct": 100 * float(np.median(ctl)),
                      "rank": float((1 + (ctl >= rm).sum()) / (reps + 1))}
    return res


def ref432(tf: TF, side):
    o, h, l, c = tf.o, tf.h, tf.l, tf.c
    atr, e200, adx = S.atr(h, l, c, 14), tf.B["свой"], S.dmi(h, l, c, 14, 14)[2]
    with np.errstate(invalid="ignore", divide="ignore"):
        ent = ((c > tf.hi) & (c > e200) & ((c - tf.hi) / atr >= 0.5)) if side == 1 else \
            ((c < tf.lo) & (c < e200) & ((tf.lo - c) / atr >= 0.5))
    ent &= adx >= 22
    ent[:300] = False
    rows, pos = [], None
    for i in range(tf.n - 1):
        if pos is not None:
            j, s = pos
            if (c[i] < tf.lo[i] if side == 1 else c[i] > tf.hi[i]) or i - s >= 20:
                k = i + 1
                fs = tf.fcs[np.searchsorted(tf.ft, tf.t[k])] - tf.fcs[np.searchsorted(tf.ft, tf.t[j])]
                rows.append((j, k, side * (o[k] / o[j] - 1) - 2 * COST_T - side * fs, "432"))
                pos = None
                continue
        if pos is None and ent[i]:
            pos = (i + 1, i)
    return rows


def main():
    OUT.mkdir(exist_ok=True)
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    del m
    print(f"кэш {pk.name}: sha256 {hashlib.sha256(pk.read_bytes()).hexdigest()[:16]}…; H1 {len(h1)}, H4 {len(h4)} баров", flush=True)
    TFS = {"H1": TF("H1", h1, h4, fund), "H4": TF("H4", h4, h4, fund)}
    variants = []
    for tfn, tf in TFS.items():
        for blue in tf.B:
            for side, fam, N, flat in itertools.product((1, -1), FAMS, NS, FLATS):
                sig = tf.signal(side, blue, fam, N, flat)
                for K, x, hold in itertools.product(KS, XS, HOLDS):
                    rows = tf.run(side, sig, tf.next_cut(side, blue, K, x), hold)
                    v = {"tf": tfn, "blue": blue, "side": side, "fam": fam, "N": N, "flat": flat, "K": K, "x": x, "hold": hold}
                    v.update(summarize(tf, rows))
                    variants.append(v)
        print(f"{tfn}: готово, вариантов всего {len(variants)}", flush=True)
    pd.DataFrame([{**{k: v[k] for k in ("tf", "blue", "side", "fam", "N", "flat", "K", "x", "hold")},
                   **{f"{p}_{q}": v[p].get(q) for p in list(PER) + ["всё"] for q in ("n", "sum", "mean")}}
                  for v in variants]).to_csv(OUT / "variants.csv", index=False)

    report = {"total": len(variants)}
    key = ("tf", "blue", "side", "fam", "N", "flat", "K", "x", "hold")
    idx = {tuple(v[k] for k in key): v for v in variants}
    for side in (1, -1):
        sv = [v for v in variants if v["side"] == side]
        posA = [v for v in sv if v["A"]["sum"] > 0]
        posAB = [v for v in posA if v["B"]["sum"] > 0]
        posABC = [v for v in posAB if v["C"]["sum"] > 0]
        allC = [v for v in sv if v["C"]["sum"] > 0]
        fam = {"variants": len(sv), "plus_A": len(posA), "plus_AB": len(posAB), "plus_ABC": len(posABC),
               "share_C_plus_all": len(allC) / len(sv), "share_C_plus_given_AB": (len(posABC) / len(posAB)) if posAB else None}
        top = sorted([v for v in sv if v["A"]["n"] >= 20], key=lambda v: -v["A"]["sum"])[:20]
        val = [v for v in top if v["B"]["sum"] > 0 and v["B"]["n"] >= 15]
        work = [v for v in val if v["C"]["sum"] > 0 and v["C"]["n"] >= 15]
        cand = []
        for v in work:
            tf = TFS[v["tf"]]
            rows = tf.run(side, tf.signal(side, v["blue"], v["fam"], v["N"], v["flat"]),
                          tf.next_cut(side, v["blue"], v["K"], v["x"]), v["hold"])
            net = np.array([r[2] for r in rows if tf.per[r[0]] != ""])
            ci = boot_ci(net)
            ctl = control(tf, v, [r for r in rows if tf.per[r[0]] != ""])
            nb = []
            for p, vals in (("N", NS), ("K", KS), ("x", XS), ("hold", HOLDS)):
                i = vals.index(v[p])
                for d in (-1, 1):
                    if 0 <= i + d < len(vals):
                        kk = dict(zip(key, (v[k] for k in key)))
                        kk[p] = vals[i + d]
                        w = idx[tuple(kk[k] for k in key)]
                        nb.append({"param": p, "value": vals[i + d], "B": w["B"]["sum"], "C": w["C"]["sum"]})
            cand.append({"variant": {k: v[k] for k in key}, "A": v["A"], "B": v["B"], "C": v["C"], "all": v["всё"],
                         "ci_all": ci, "control": ctl, "neighbors": nb,
                         "neighbors_all_plus_BC": all(x_["B"] > 0 and x_["C"] > 0 for x_ in nb)})
        report["лонг" if side == 1 else "шорт"] = {"family": fam,
                                                    "top20_by_A": [{**{k: v[k] for k in key}, "A": v["A"]["sum"], "nA": v["A"]["n"],
                                                                    "B": v["B"]["sum"], "nB": v["B"]["n"], "C": v["C"]["sum"],
                                                                    "nC": v["C"]["n"]} for v in top],
                                                    "passed_B": len(val), "passed_C": len(work), "candidates": cand}
    for tfn, tf in TFS.items():
        for side in (1, -1):
            report[f"432_{tfn}_{'лонг' if side == 1 else 'шорт'}"] = summarize(tf, ref432(tf, side))
    (OUT / "sweep_result.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: (v if k.startswith("432") or k == "total" else {"family": v["family"], "passed_B": v["passed_B"],
                                                                          "passed_C": v["passed_C"]})
                      for k, v in report.items()}, ensure_ascii=False, indent=1, default=str))
    for sd in ("лонг", "шорт"):
        print(f"\n== {sd}: 20 лучших по A")
        print(pd.DataFrame(report[sd]["top20_by_A"]).round(1).to_string())
        for cnd in report[sd]["candidates"]:
            print(json.dumps(cnd, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
