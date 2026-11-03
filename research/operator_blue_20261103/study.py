"""Голубая линия: тренд (вход у голубой, удержание) и флет (две сетки до большого выхода). Правила — PREREG.md.
Обучение 01.04–02.11.2026, проверка 15.05.2024–31.03.2026, 2018–05.2024 — строкой.
Запуск: study.py --pk-btc=<bars_*.pkl BTC из mr_data.build>   (nice 20)."""
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
sys.path.insert(0, str(ROOT / "research" / "market_regimes_20261102"))
import gridk  # noqa: E402
import strategies as S  # noqa: E402

COST_T, COST_M = 0.00048 + 0.0002, 0.00016
MIN_RISK = 0.0068
RNG = np.random.default_rng(20261103)
TS = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp())  # noqa: E731
WIN = {"обучение": ("2026-04-01", "2026-11-03"), "проверка": ("2024-05-15", "2026-04-01"),
       "2018–05.2024": ("2018-01-01", "2024-05-15")}
THETAS, DS, EXITS = (0.002, 0.004, 0.008), (0.005, 0.015, 0.03), ("X0", "X1", "X2", "X3", "X4")


def runlen(x):
    x = x.astype(np.int64)
    cs = np.cumsum(x)
    return cs - np.maximum.accumulate(np.where(x == 0, cs, 0))


class TFD:
    def __init__(self, name, b, h4, fund):
        self.name = name
        self.o, self.h, self.l, self.c = (b[k].to_numpy() for k in ("open", "high", "low", "close"))
        self.t = b.index.to_numpy()
        self.n = len(self.c)
        L = 24 if name == "H1" else 6
        self.B = S.ema(self.c, 200)
        self.atr = S.atr(self.h, self.l, self.c, 14)
        self.hi = pd.Series(self.h).shift(1).rolling(30).max().to_numpy()
        self.lo = pd.Series(self.l).shift(1).rolling(30).min().to_numpy()
        self.slope = self.B / np.r_[np.full(L, np.nan), self.B[:-L]] - 1
        self.reg = {}
        for th in THETAS:
            with np.errstate(invalid="ignore"):
                self.reg[th] = np.where(self.slope > th, 1, np.where(self.slope < -th, -1, 0))
        if name == "H1":
            e4 = S.ema(h4["close"].to_numpy(), 200)
            j = np.searchsorted(h4["known"].to_numpy(), b["known"].to_numpy(), side="right") - 1
            B4 = np.where(j >= 0, e4[np.maximum(j, 0)], np.nan)
            with np.errstate(invalid="ignore"):
                self.reg["две голубые"] = np.where((self.B > B4) & (self.slope > 0), 1,
                                                   np.where((self.B < B4) & (self.slope < 0), -1, 0))
        f = fund[~fund.index.duplicated(keep="last")]
        self.ft, self.fcs = f.index.to_numpy(), np.r_[0.0, np.cumsum(f.to_numpy())]
        c5 = np.r_[np.full(5, np.nan), self.c[:-5]]
        with np.errstate(invalid="ignore"):
            self.imp = {1: (self.c / self.o - 1 <= -0.015) | (self.c / c5 - 1 <= -0.015),
                        -1: (self.c / self.o - 1 >= 0.015) | (self.c / c5 - 1 >= 0.015)}
            self.opp5 = {1: runlen(self.c < self.B) >= 5, -1: runlen(self.c > self.B) >= 5}

    def fund(self, a, b):
        return self.fcs[np.searchsorted(self.ft, self.t[b], side="right")] - self.fcs[np.searchsorted(self.ft, self.t[a], side="right")]

    def signal(self, side, reg_key, d):
        B, c, h, l = self.B, self.c, self.h, self.l
        with np.errstate(invalid="ignore"):
            near = (l <= B * (1 + d)) & (c > B) if side == 1 else (h >= B * (1 - d)) & (c < B)
        cond = near & (self.reg[reg_key] == side) & np.isfinite(self.atr) & np.isfinite(self.hi)
        sig = cond & ~np.r_[False, cond[:-1]]
        sig[:400] = False
        return sig

    def signal_now(self, side):
        """Индикатор как сейчас: «Любое» (касание низа канала или голубой за 5 баров), N 2, без режима."""
        B, c, h, l, hi, lo = self.B, self.c, self.h, self.l, self.hi, self.lo
        with np.errstate(invalid="ignore"):
            if side == 1:
                t_ch, ch_ok, t_b, on = l <= lo * 1.0015, c > lo, l <= B * 1.0015, c > B
            else:
                t_ch, ch_ok, t_b, on = h >= hi * 0.9985, c < hi, h >= B * 0.9985, c < B
        r5 = lambda a: pd.Series(a.astype(float)).rolling(5, min_periods=1).max().to_numpy() > 0  # noqa: E731
        cond = ((r5(t_ch) & ch_ok) | r5(t_b)) & (runlen(on) >= 2) & np.isfinite(hi) & np.isfinite(B)
        sig = cond & ~np.r_[False, cond[:-1]]
        sig[:400] = False
        return sig

    def trade(self, side, i, ex):
        o, h, l, c, n = self.o, self.h, self.l, self.c, self.n
        e = i + 1
        if e >= n - 1:
            return None
        px = o[e]
        tgt, stop = None, None
        if ex == "X0":
            tgt = self.hi[i] if side == 1 else self.lo[i]
            if side * (tgt / px - 1) < 0.002:
                return None
        else:
            lo5, hi5 = l[max(0, i - 4):i + 1].min(), h[max(0, i - 4):i + 1].max()
            stop = (min(lo5, self.B[i]) - 0.5 * self.atr[i]) if side == 1 else (max(hi5, self.B[i]) + 0.5 * self.atr[i])
            if side * (px - stop) / px < MIN_RISK:
                stop = px * (1 - side * MIN_RISK)
            R = side * (px - stop)
            if ex == "X1":
                tgt = px + side * 3 * R
            elif ex == "X4":
                tgt = px + side * 2 * R
        peak = px
        for j in range(e, n):
            if stop is not None and (l[j] <= stop if side == 1 else h[j] >= stop):
                out = min(o[j], stop) if side == 1 else max(o[j], stop)
                return self._close(side, e, j, px, out, COST_T, "стоп")
            if tgt is not None and (h[j] >= tgt * 1.0001 if side == 1 else l[j] <= tgt * 0.9999):
                out = max(o[j], tgt) if side == 1 else min(o[j], tgt)
                return self._close(side, e, j, px, out, COST_M, "цель")
            if j >= n - 1:
                return self._close(side, e, n - 1, px, c[-1], COST_T, "конец")
            peak = max(peak, h[j]) if side == 1 else min(peak, l[j])
            why = None
            if ex == "X0" and (self.opp5[side][j] or self.imp[side][j]):
                why = "стоп K/имп"
            elif ex == "X2" and side * (c[j] / self.B[j] - 1) < -0.01:
                why = "слом"
            elif ex == "X3" and side * (c[j] - (peak - side * 3 * self.atr[i])) < 0:
                why = "трейлинг"
            if why:
                return self._close(side, e, j + 1, px, o[j + 1], COST_T, why)
        return None

    def _close(self, side, e, xb, px, out, fee, why):
        return e, xb, side * (out / px - 1) - COST_T - fee - side * self.fund(e, xb), why

    def run(self, side, sig, ex, lo=0, hi=None):
        hi = self.n if hi is None else hi
        rows, free = [], 0
        for i in np.flatnonzero(sig[lo:hi]) + lo:
            if i < free:
                continue
            r = self.trade(side, i, ex)
            if r is None:
                continue
            rows.append(r)
            free = r[1]
        return rows


def summ(rows, tf: TFD, a, b):
    rs = [r for r in rows if TS(a) <= tf.t[r[0]] < TS(b)]
    x = np.array([r[2] for r in rs])
    if not len(x):
        return {"n": 0, "sum": 0.0, "mean": None, "win": None, "worst_run": 0.0}
    eq = np.cumsum(x)
    return {"n": len(x), "sum": 100 * float(x.sum()), "mean": 100 * float(x.mean()), "win": 100 * float((x > 0).mean()),
            "worst_run": 100 * float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]))}


def control(tf: TFD, side, reg_key, ex, real_rows, a, b, reps=999):
    rs = [r for r in real_rows if TS(a) <= tf.t[r[0]] < TS(b)]
    k = len(rs)
    if k < 5:
        return None
    with np.errstate(invalid="ignore"):
        ok = (tf.reg[reg_key] == side) & ((tf.c > tf.B) if side == 1 else (tf.c < tf.B)) & np.isfinite(tf.atr) & np.isfinite(tf.hi)
    pool = np.flatnonzero(ok & (tf.t >= TS(a)) & (tf.t < TS(b)))
    pool = pool[pool < tf.n - 2]
    real = np.mean([r[2] for r in rs])
    ctl = np.empty(reps)
    for q in range(reps):
        vals = []
        while len(vals) < k:
            r = tf.trade(side, int(RNG.choice(pool)), ex)
            if r is not None:
                vals.append(r[2])
        ctl[q] = np.mean(vals)
    return {"real_mean_pct": 100 * real, "ctl_median_pct": 100 * float(np.median(ctl)),
            "rank": float((1 + (ctl >= real).sum()) / (reps + 1))}


def grids(m, h4, d1, fund, out):
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    c4, k4 = h4["close"].to_numpy(), h4["known"].to_numpy()
    B4 = S.ema(c4, 200)
    sl = B4 / np.r_[np.full(6, np.nan), B4[:-6]] - 1
    end_ts = int(m["ts"].iloc[-1]) + 60
    res = {}

    def run_eps(eps, side, a, b):
        ta, tb = TS(a), TS(b)
        cl = [(max(x, ta), min(y, tb)) for x, y in eps if y > ta and x < tb]
        if not cl:
            return 0.0, 0.0, 0
        r = mk.run(mk.idx([x for x, _ in cl]), mk.idx([y for _, y in cl]), side, cap=3000.0)
        return float(r[:, 0].sum()), float(r[:, 6].max()), len(cl)

    for th, X in itertools.product(THETAS, (0.02, 0.03, 0.05)):
        with np.errstate(invalid="ignore"):
            arm = (np.abs(sl) <= th) & (np.abs(c4 / B4 - 1) <= X)
            kill = {1: c4 < B4 * (1 - X), -1: c4 > B4 * (1 + X)}
        eps = {}
        for side in (1, -1):
            on, start, ep = False, 0, []
            for i in range(400, len(c4)):
                if on and kill[side][i]:
                    ep.append((start, int(k4[i])))
                    on = False
                elif not on and arm[i]:
                    on, start = True, int(k4[i])
            if on:
                ep.append((start, end_ts))
            eps[side] = ep
        row = {}
        for w, (a, b) in WIN.items():
            L_, ddl, nl = run_eps(eps[1], 1, a, b)
            S_, dds, ns = run_eps(eps[-1], -1, a, b)
            row[w] = {"long": L_, "short": S_, "total": L_ + S_, "eps_long": nl, "eps_short": ns}
        res[f"θ {100 * th:g}% · X {100 * X:g}%"] = row
    base = {}
    for w, (a, b) in WIN.items():
        ta, tb = TS(a), TS(b)
        i0, i1 = mk.idx([ta]), mk.idx([min(tb, end_ts)])
        both = float(mk.run(i0, i1, 1, cap=3000.0)[0, 0] + mk.run(i0, i1, -1, cap=3000.0)[0, 0])
        dd = d1[(d1.index >= ta) & (d1.index < tb)]["reg0"]
        on = (dd == 1).to_numpy()
        days = dd.index.to_numpy()
        eps, s0 = [], None
        for d_, o_ in zip(days, on):
            if o_ and s0 is None:
                s0 = int(d_)
            elif not o_ and s0 is not None:
                eps.append((s0, int(d_)))
                s0 = None
        if s0 is not None:
            eps.append((s0, min(tb, end_ts)))
        lsma = float(mk.run(mk.idx([x for x, _ in eps]), mk.idx([y for _, y in eps]), 1, cap=6000.0)[:, 0].sum()) if eps else 0.0
        base[w] = {"обе всегда": both, "лонг по SMA100": lsma}
    out["grids"] = res
    out["grids_base"] = base
    print("\n== ФЛЕТ: две сетки 0.6/1.4, $100, по $3 000 на сторону; итог $ полного капитала (лонг / шорт / вместе)")
    print("| Вариант | " + " | ".join(WIN) + " |")
    print("|---|" + "---|" * len(WIN))
    for nm, row in res.items():
        print(f"| {nm} | " + " | ".join(f"{row[w]['long']:+.0f} / {row[w]['short']:+.0f} / **{row[w]['total']:+.0f}** "
                                         f"({row[w]['eps_long']}/{row[w]['eps_short']} эп.)" for w in WIN) + " |")
    for nm in ("обе всегда", "лонг по SMA100"):
        print(f"| {nm} | " + " | ".join(f"{base[w][nm]:+.0f}" for w in WIN) + " |")


def main():
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    print(f"кэш {pk.name}: sha256 {hashlib.sha256(pk.read_bytes()).hexdigest()[:16]}…; H1 {len(h1)}, H4 {len(h4)}; "
          f"до {pd.to_datetime(h1.index[-1], unit='s')}", flush=True)
    out = {}
    TFS = {"H4": TFD("H4", h4, h4, fund), "H1": TFD("H1", h1, h4, fund)}

    # режимы за 7 месяцев (описание)
    tf = TFS["H4"]
    a, b = WIN["обучение"]
    msk = (tf.t >= TS(a)) & (tf.t < TS(b))
    print("\n== Режимы голубой 4ч, обучение (θ 0.4%): доля времени, ход цены внутри")
    for r_, nm in ((1, "вверх"), (0, "горизонталь"), (-1, "вниз")):
        mm = msk & (tf.reg[0.004] == r_)
        rets = np.diff(np.log(tf.c))[mm[1:]]
        print(f"{nm}: {100 * mm.sum() / msk.sum():.0f}% времени, суммарный ход {100 * (np.exp(rets.sum()) - 1):+.1f}%")

    allv = []
    for (tfn, tf), side in itertools.product(TFS.items(), (1, -1)):
        regs = list(tf.reg)
        for rk, d, ex in itertools.product(regs, DS, EXITS):
            rows = tf.run(side, tf.signal(side, rk, d), ex)
            v = {"tf": tfn, "side": side, "reg": rk, "d": d, "ex": ex}
            for w, (a, b) in WIN.items():
                v[w] = summ(rows, tf, a, b)
            allv.append(v)
        rows = tf.run(side, tf.signal_now(side), "X0")
        v = {"tf": tfn, "side": side, "reg": "нет", "d": None, "ex": "индикатор сейчас"}
        for w, (a, b) in WIN.items():
            v[w] = summ(rows, tf, a, b)
        allv.append(v)
        print(f"{tfn} {'лонг' if side == 1 else 'шорт'}: готово", flush=True)
    pd.DataFrame([{**{k: v[k] for k in ("tf", "side", "reg", "d", "ex")},
                   **{f"{w}_{q}": v[w][q] for w in WIN for q in ("n", "sum", "mean", "win", "worst_run")}} for v in allv]
                 ).to_csv(HERE / "out_variants.csv", index=False)

    out["best"] = {}
    for tfn, side in itertools.product(TFS, (1, -1)):
        nmin = 6 if tfn == "H4" else 10
        sv = [v for v in allv if v["tf"] == tfn and v["side"] == side and v["ex"] != "индикатор сейчас"]
        cand = [v for v in sv if v["обучение"]["n"] >= nmin]
        trp = [v for v in sv if v["обучение"]["sum"] > 0 and v["обучение"]["n"] >= nmin]
        stab = sum(1 for v in trp if v["проверка"]["sum"] > 0)
        now = next(v for v in allv if v["tf"] == tfn and v["side"] == side and v["ex"] == "индикатор сейчас")
        sd = "лонг" if side == 1 else "шорт"
        print(f"\n== {tfn} {sd}: вариантов {len(sv)}, с n ≥ {nmin} в обучении {len(cand)}, плюсовых в обучении {len(trp)}, "
              f"из них плюсовых и в проверке {stab}")
        print(f"индикатор сейчас: обучение {now['обучение']['n']} · {now['обучение']['sum']:+.1f}%, проверка "
              f"{now['проверка']['n']} · {now['проверка']['sum']:+.1f}%")
        if not cand:
            continue
        best = max(cand, key=lambda v: v["обучение"]["sum"])
        x0 = next(v for v in sv if v["reg"] == best["reg"] and v["d"] == best["d"] and v["ex"] == "X0")
        tf = TFS[tfn]
        rows = tf.run(side, tf.signal(side, best["reg"], best["d"]), best["ex"])
        ctl = control(tf, side, best["reg"], best["ex"], rows, *WIN["проверка"])
        out["best"][f"{tfn} {sd}"] = {"variant": {k: best[k] for k in ("reg", "d", "ex")}, **{w: best[w] for w in WIN},
                                       "X0_same_entry": {w: x0[w] for w in WIN}, "control_check": ctl}
        print(f"лучший в обучении: режим {best['reg']}, d {100 * best['d']:g}%, выход {best['ex']}")
        for w in WIN:
            s, z = best[w], x0[w]
            print(f"  {w}: {s['n']} сделок · {s['sum']:+.1f}% · ср. {s['mean'] if s['mean'] is None else round(s['mean'], 2)}% · "
                  f"плюс {s['win'] if s['win'] is None else round(s['win'])}% · худшая серия {s['worst_run']:.1f}%  |  "
                  f"тот же вход, выход X0: {z['n']} · {z['sum']:+.1f}%")
        print(f"  контроль в проверке: {ctl}")
        print("  сделки обучения:")
        for e, xb, net, why in rows:
            if TS(WIN["обучение"][0]) <= tf.t[e] < TS(WIN["обучение"][1]):
                print(f"    {pd.to_datetime(tf.t[e], unit='s')} → {pd.to_datetime(tf.t[min(xb, tf.n - 1)], unit='s')} "
                      f"{why:9s} {100 * net:+6.2f}%  вход {tf.o[e]:.0f}, голубая {tf.B[e - 1]:.0f} "
                      f"({100 * (tf.o[e] / tf.B[e - 1] - 1):+.1f}%)")
    # по выходам: средняя сумма в обучении и проверке по всем вариантам семейства
    print("\n== По типу выхода (все варианты, сумма % — медиана по вариантам): обучение / проверка")
    for tfn, side in itertools.product(TFS, (1, -1)):
        cells = []
        for ex in EXITS:
            vs = [v for v in allv if v["tf"] == tfn and v["side"] == side and v["ex"] == ex]
            cells.append(f"{ex} {np.median([v['обучение']['sum'] for v in vs]):+.1f} / {np.median([v['проверка']['sum'] for v in vs]):+.1f}")
        print(f"{tfn} {'лонг' if side == 1 else 'шорт'}: " + " · ".join(cells))
    grids(m, h4, d1, fund, out)
    (HERE / "out_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
