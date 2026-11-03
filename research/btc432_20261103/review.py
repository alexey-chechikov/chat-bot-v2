"""432 только на BTC: разбор каждой сделки (лонг и зеркальный шорт) и заранее записанные варианты. Правила — PREREG.md.
Запуск: review.py --pk-btc=<bars_*.pkl BTC из mr_data.build>   (nice 20)."""
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
import strategies as S  # noqa: E402
from validate_432 import s432  # noqa: E402

OUT = HERE / "out"
COST = 0.00048 + 0.0002
H4 = 14400
PERIODS = {"A 2017–2021": ("2017-01-01", "2022-01-01"), "B 2022–07.2024": ("2022-01-01", "2024-08-01"),
           "C 08.2024–2026": ("2024-08-01", "2030-01-01")}
RNG = np.random.default_rng(20261103)


def ts(s):
    return int(pd.Timestamp(s, tz="UTC").timestamp())


class Data:
    def __init__(self, pk: Path):
        m, h1, h4, d1, fund = pd.read_pickle(pk)
        del m, h1
        print(f"кэш {pk.name}: sha256 {hashlib.sha256(pk.read_bytes()).hexdigest()[:16]}…, H4 {len(h4)} "
              f"{pd.to_datetime(h4.index[0], unit='s')} → {pd.to_datetime(h4.index[-1], unit='s')}", flush=True)
        self.o, self.h, self.l, self.c = (h4[k].to_numpy() for k in ("open", "high", "low", "close"))
        self.t = h4.index.to_numpy()
        o, h, l, c = self.o, self.h, self.l, self.c
        self.hi30 = pd.Series(h).shift(1).rolling(30).max().to_numpy()
        self.lo30 = pd.Series(l).shift(1).rolling(30).min().to_numpy()
        self.atr = S.atr(h, l, c, 14)
        self.e200 = S.ema(c, 200)
        self.adx = S.dmi(h, l, c, 14, 14)[2]
        with np.errstate(invalid="ignore", divide="ignore"):
            magL = np.where((c > self.hi30) & (self.atr > 0), (c - self.hi30) / self.atr, 0.0)
            magS = np.where((c < self.lo30) & (self.atr > 0), (self.lo30 - c) / self.atr, 0.0)
        self.mag = {1: magL, -1: magS}
        self.ent = {1: (c > self.hi30) & (self.adx >= 22) & (c > self.e200) & (magL >= 0.5),
                    -1: (c < self.lo30) & (self.adx >= 22) & (c < self.e200) & (magS >= 0.5)}
        for v in self.ent.values():
            v[:300] = False
        day = ((self.t + H4) // 86400) * 86400                     # день, к которому относится момент решения
        self.reg = {}
        for band, col in ((0, "reg0"), (2, "reg2")):
            r = d1[col].reindex(day).to_numpy()
            self.reg[band] = r                                      # 1 вверх, 0 вниз, nan неизвестно
        f = fund[~fund.index.duplicated(keep="last")]
        self.ft, self.fcs = f.index.to_numpy(), np.r_[0.0, np.cumsum(f.to_numpy())]

    def fsum(self, a, b):
        return self.fcs[np.searchsorted(self.ft, self.t[b])] - self.fcs[np.searchsorted(self.ft, self.t[a])]


def run(D: Data, side=1, H=20, restart=False, cap=None, units=1, stop_k=None, tstop=None, reg=None):
    """→ список единиц: вход j (open), выход k (open), цена, причина, сигнал, новых сигналов внутри."""
    o, c, n = D.o, D.c, len(D.c)
    ent = D.ent[side]
    pos, out = [], []

    def ok(i):
        if reg is None:
            return True
        r = D.reg[reg][i]
        return r == r and int(r) == (1 if side == 1 else 0)

    for i in range(n - 1):
        if pos:
            chan = c[i] < D.lo30[i] if side == 1 else c[i] > D.hi30[i]
            exited = False
            for u in list(pos):
                why = None
                if chan:
                    why = "канал"
                elif stop_k is not None and side * (c[i] - u["px"]) < -stop_k * u["atr"]:
                    why = "стоп"
                elif tstop is not None and i - u["j"] + 1 == tstop and side * (c[i] - u["px"]) < 0:
                    why = "не пошла"
                elif i - u["sig"] >= H:
                    why = "время"
                elif cap is not None and i - u["first"] >= cap:
                    why = "предел"
                if why:
                    u.update(k=i + 1, pout=o[i + 1], why=why)
                    out.append(u)
                    pos.remove(u)
                    exited = True
            if exited:
                continue
            if ent[i] and ok(i):
                for u in pos:
                    u["new_sigs"] += 1
                if restart:
                    for u in pos:
                        u["sig"] = i
                elif len(pos) < units:
                    pos.append({"j": i + 1, "sig": i, "first": i, "px": o[i + 1], "atr": D.atr[i], "new_sigs": 0,
                                "unit": len(pos) + 1})
            continue
        if ent[i] and ok(i):
            pos.append({"j": i + 1, "sig": i, "first": i, "px": o[i + 1], "atr": D.atr[i], "new_sigs": 0, "unit": 1})
    for u in pos:
        u.update(k=n - 1, pout=c[-1], why="конец")
        out.append(u)
    for u in out:
        u["side"] = side
        u["gross"] = side * (u["pout"] / u["px"] - 1)
        u["net"] = u["gross"] - 2 * COST - side * D.fsum(u["j"], u["k"])
        u["t_in"] = int(D.t[u["j"]])
    return sorted(out, key=lambda u: (u["j"], u["unit"]))


def equity(D: Data, units: list) -> np.ndarray:
    eq = np.zeros(len(D.c))
    for u in units:
        j, k, s = u["j"], u["k"], u["side"]
        eq[j:k] += s * (D.c[j:k] / u["px"] - 1) - COST
        eq[k:] += u["net"]
    return eq


def boot_ci(x, reps=5000):
    if len(x) < 2:
        return (np.nan, np.nan)
    m = RNG.choice(x, (reps, len(x))).mean(axis=1)
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def stats(D: Data, units: list) -> dict:
    eq = equity(D, units)
    res = {}
    for name, (a, b) in list(PERIODS.items()) + [("всё", ("2017-01-01", "2030-01-01"))]:
        ta, tb = ts(a), ts(b)
        us = [u for u in units if ta <= u["t_in"] < tb]
        x = np.array([u["net"] for u in us])
        m = (D.t >= ta) & (D.t < tb)
        e = eq[m]
        dd = float(np.max(np.maximum.accumulate(e) - e)) if len(e) else 0.0
        lo, hi = boot_ci(x)
        res[name] = {"n": len(x), "sum": 100 * float(x.sum()) if len(x) else 0.0,
                     "mean": 100 * float(x.mean()) if len(x) else np.nan, "win": 100 * float((x > 0).mean()) if len(x) else np.nan,
                     "dd": 100 * dd, "ci": (100 * lo, 100 * hi)}
    # максимальная одновременная экспозиция
    ev = np.zeros(len(D.c))
    for u in units:
        ev[u["j"]:u["k"]] += 1
    res["max_units"] = int(ev.max()) if len(units) else 0
    res["time_in_market"] = float((ev > 0).mean())
    return res


def diag(D: Data, units: list) -> pd.DataFrame:
    rows = []
    o, h, l, c = D.o, D.h, D.l, D.c
    for u in units:
        j, k, s, px, i = u["j"], u["k"], u["side"], u["px"], u["sig"] if u["new_sigs"] == 0 else u["first"]
        i = u["first"]
        hh, ll = h[j:k], l[j:k]
        if s == 1:
            mfe, mae = hh.max() / px - 1, ll.min() / px - 1
            b_mfe = int(np.argmax(hh))
        else:
            mfe, mae = 1 - ll.min() / px, 1 - hh.max() / px
            b_mfe = int(np.argmin(ll))
        r = {"entry": str(pd.to_datetime(D.t[j], unit="s")), "exit": str(pd.to_datetime(D.t[k], unit="s")),
             "side": s, "why": u["why"], "bars": k - j, "net": u["net"], "mfe": mfe, "mae": mae, "bar_mfe": b_mfe,
             "giveback": mfe - u["gross"], "new_sigs": u["new_sigs"]}
        for b in (1, 3, 5):
            r[f"r{b}"] = s * (c[j + b - 1] / px - 1) if j + b - 1 < k else np.nan
        r["mag"] = D.mag[s][i]
        r["adx"] = D.adx[i]
        r["dEMA"] = s * (c[i] / D.e200[i] - 1)
        r["atr_pct"] = D.atr[i] / c[i]
        r["chan_w"] = (D.hi30[i] - D.lo30[i]) / c[i]
        r["ema_slope30"] = s * (D.e200[i] / D.e200[i - 30] - 1)
        r["body"] = s * (c[i] / o[i] - 1)
        r["hour"] = int(((D.t[i] + H4) % 86400) // 3600)
        r["reg0"] = D.reg[0][i]
        r["fwd20_after"] = s * (o[k + 20] / o[k] - 1) if k + 20 < len(o) else np.nan
        r["period"] = next(nm for nm, (a, b) in PERIODS.items() if ts(a) <= D.t[j] < ts(b))
        rows.append(r)
    return pd.DataFrame(rows)


def short_control(D: Data, units: list, reg=None, reps=2000) -> dict:
    o, c = D.o, D.c
    okb = (c < D.e200)
    if reg is not None:
        okb &= (D.reg[reg] == 0)
    idx = np.flatnonzero(okb)
    idx = idx[(idx > 300) & (idx < len(o) - 40)]
    durs = np.array([u["k"] - u["j"] for u in units])
    mean = np.mean([u["net"] for u in units])
    res = np.empty(reps)
    for r in range(reps):
        js = RNG.choice(idx, len(durs)) + 1
        ks = np.minimum(js + durs, len(o) - 1)
        g = -(o[ks] / o[js] - 1)
        f = np.array([D.fsum(a, b) for a, b in zip(js, ks)])
        res[r] = float(np.mean(g - 2 * COST + f))
    return {"mean_pct": 100 * float(mean), "ctl_median_pct": 100 * float(np.median(res)),
            "rank": float((1 + (res >= mean).sum()) / (reps + 1))}


def main():
    OUT.mkdir(exist_ok=True)
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    D = Data(pk)
    # 1) движок повторяет s432
    base = run(D, 1)
    ref = s432((D.o, D.h, D.l, D.c))
    same = [(u["j"], u["k"]) for u in base] == [(j, k) for j, k, *_r in ref]
    print(f"движок = s432: {same} ({len(base)} против {len(ref)})", flush=True)
    if not same:
        sys.exit("движок не повторяет s432 — отказ")

    V = {
        "L0 исходная": dict(side=1),
        "L1 продление, предел 40": dict(side=1, restart=True, cap=40),
        "L1 продление, предел 60": dict(side=1, restart=True, cap=60),
        "L1 продление, без предела": dict(side=1, restart=True),
        "L2 докупка, до 2 единиц": dict(side=1, units=2),
        "L2 докупка, до 3 единиц": dict(side=1, units=3),
        "L3 стоп 1.5 ATR": dict(side=1, stop_k=1.5),
        "L3 стоп 2 ATR": dict(side=1, stop_k=2.0),
        "L3 стоп 3 ATR": dict(side=1, stop_k=3.0),
        "L4 не пошла за 3 бара": dict(side=1, tstop=3),
        "L4 не пошла за 5 баров": dict(side=1, tstop=5),
        "L4 не пошла за 8 баров": dict(side=1, tstop=8),
        "L5 режим SMA100 без полосы": dict(side=1, reg=0),
        "L5 режим SMA100 полоса 2%": dict(side=1, reg=2),
        "S0 зеркальный шорт": dict(side=-1),
        "S1 шорт 10 баров": dict(side=-1, H=10),
        "S1 шорт 30 баров": dict(side=-1, H=30),
        "S2 шорт + режим вниз без полосы": dict(side=-1, reg=0),
        "S2 шорт + режим вниз полоса 2%": dict(side=-1, reg=2),
    }
    results, trades = {}, {}
    for name, kw in V.items():
        u = run(D, **kw)
        trades[name] = u
        results[name] = stats(D, u)
    # лонг + шорт вместе (хедж-режим: стороны не мешают друг другу)
    for nm, sn in (("L0 + S0", "S0 зеркальный шорт"), ("L0 + S2 режим без полосы", "S2 шорт + режим вниз без полосы")):
        results[nm] = stats(D, trades["L0 исходная"] + trades[sn])
    # парные разницы для вариантов выхода с теми же входами
    b = {u["j"]: u["net"] for u in trades["L0 исходная"]}
    paired = {}
    for name in [n for n in V if n.startswith(("L3", "L4"))]:
        d = np.array([u["net"] - b[u["j"]] for u in trades[name] if u["j"] in b])
        lo, hi = boot_ci(d)
        paired[name] = {"n_common": len(d), "diff_sum_pct": 100 * float(d.sum()), "ci_mean_pct": (100 * lo, 100 * hi)}
    ctl = {"S0": short_control(D, trades["S0 зеркальный шорт"]),
           "S2_reg0": short_control(D, trades["S2 шорт + режим вниз без полосы"], reg=0)}
    dl, ds = diag(D, trades["L0 исходная"]), diag(D, trades["S0 зеркальный шорт"])
    dl.to_csv(OUT / "trades_long_L0.csv", index=False)
    ds.to_csv(OUT / "trades_short_S0.csv", index=False)
    (OUT / "variants.json").write_text(json.dumps({"results": results, "paired": paired, "short_control": ctl},
                                                  ensure_ascii=False, indent=1, default=float))

    print("\n| Вариант | " + " | ".join(f"{p}: n · сумма % · просадка %" for p in PERIODS) + " | Всё: n · сумма % · ср. % [ДИ] · просадка % | max ед. |")
    print("|---|" + "---|" * (len(PERIODS) + 2))
    for name, r in results.items():
        cells = [f"{r[p]['n']} · {r[p]['sum']:+.1f} · {r[p]['dd']:.1f}" for p in PERIODS]
        a = r["всё"]
        cells.append(f"{a['n']} · {a['sum']:+.1f} · {a['mean']:+.2f} [{a['ci'][0]:+.2f}…{a['ci'][1]:+.2f}] · {a['dd']:.1f}")
        print(f"| {name} | " + " | ".join(cells) + f" | {r['max_units']} |")
    print("\nпарные разницы:", json.dumps(paired, ensure_ascii=False))
    print("контроль шорта:", json.dumps(ctl, ensure_ascii=False))

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    for nm, d in (("ЛОНГ L0", dl), ("ШОРТ S0", ds)):
        d = d.copy()
        d["res"] = np.where(d["net"] > 0, "плюс", "минус")
        cols = ["net", "mfe", "mae", "bar_mfe", "giveback", "r1", "r3", "r5", "new_sigs", "mag", "adx", "dEMA", "atr_pct",
                "chan_w", "ema_slope30", "body", "fwd20_after"]
        print(f"\n== {nm}: медианы плюс/минус по периодам")
        g = d.groupby(["period", "res"])[cols].median()
        g.insert(0, "n", d.groupby(["period", "res"]).size())
        print(g.round(4).to_string())
        print(f"{nm}: причины выхода", d["why"].value_counts().to_dict())
        top = d.sort_values("net", ascending=False)
        print(f"{nm}: доля 5 лучших в сумме {100 * top['net'].head(5).sum() / d['net'].sum():.0f}%, "
              f"сумма без 5 лучших {100 * (d['net'].sum() - top['net'].head(5).sum()):+.1f}%")


if __name__ == "__main__":
    main()
