"""Прогон стратегий TradingView (strategies.py) на BTC/ETH 2017–2026 + DCA 3Commas и Vol-Target. Правила — в strategies.py.
Запуск: run.py <1m BTC 2017–2026.csv> <1m ETH 2017–2026.csv>  (nice 20, один процесс — живые сетки на том же маке)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import strategies as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SPLIT = pd.Timestamp("2022-03-05")                         # середина окна
FRESH = pd.Timestamp("2024-10-24")                         # последние 2 года
REPS = 200


def bars(path: str) -> dict[str, pd.DataFrame]:
    d = pd.read_csv(path, usecols=["ts", "open", "high", "low", "close"])
    d.index = pd.to_datetime(d["ts"], unit="ms")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return {tf: d.resample(rule).agg(agg).dropna() for tf, rule in (("1h", "1h"), ("4h", "4h"), ("1d", "1D"))}


def funding(sym: str) -> tuple[np.ndarray, np.ndarray]:
    f = pd.read_csv(ROOT / "backtests" / "frozen" / f"{sym}_funding_full.csv")
    t = pd.to_datetime(f["fundingTime"], unit="ms").to_numpy()
    return t, np.r_[0.0, np.cumsum(f["fundingRate"].to_numpy(float))]


def evaluate(df, trades, fund):
    t = df.index.to_numpy()
    ft, cs = fund
    rows = []
    for j, k, side, pin, pout, why in trades:
        if k <= j or j >= len(t):
            continue
        a, b = np.searchsorted(ft, t[j]), np.searchsorted(ft, t[min(k, len(t) - 1)])
        fsum = cs[b] - cs[a]
        gross = side * (pout / pin - 1)
        rows.append({"t": t[j], "side": side, "bars": k - j, "gross": gross,
                     "net": gross - 2 * S.COST - side * fsum, "why": why, "j": j})
    return pd.DataFrame(rows)


def random_control(df, tr, fund, seed=1):
    """Те же длительности и стороны, случайный вход: средний net % на сделку, REPS повторов."""
    o = df["open"].to_numpy()
    t = df.index.to_numpy()
    ft, cs = fund
    rng = np.random.default_rng(seed)
    lo = 300
    out = np.empty(REPS)
    durs, sides = tr["bars"].to_numpy(), tr["side"].to_numpy()
    for r in range(REPS):
        tot = 0.0
        for d, s in zip(durs, sides):
            j = int(rng.integers(lo, len(o) - d - 1))
            k = j + d
            fsum = cs[np.searchsorted(ft, t[k])] - cs[np.searchsorted(ft, t[j])]
            tot += s * (o[k] / o[j] - 1) - 2 * S.COST - s * fsum
        out[r] = tot / len(durs)
    return out


def ci(x):
    m = x.mean()
    se = x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else np.nan
    return m, m - 1.96 * se, m + 1.96 * se


def line(name, tf, sym, tr, ctl):
    if tr.empty:
        return f"{name:<32} {tf:>3} {sym[:3]} | сделок 0"
    m, lo, hi = ci(tr["net"].to_numpy())
    eq = tr["net"].cumsum().to_numpy()
    dd = float((eq - np.maximum.accumulate(eq)).min())
    h1, h2 = tr[tr["t"] < SPLIT]["net"], tr[tr["t"] >= SPLIT]["net"]
    fr = tr[tr["t"] >= FRESH]["net"]
    rank = (1 + int((ctl >= m).sum())) / (1 + REPS)
    return (f"{name:<32} {tf:>3} {sym[:3]} | n {len(tr):>5} win {100 * (tr['net'] > 0).mean():>3.0f}% | "
            f"net {100 * m:+.3f}% [{100 * lo:+.3f}…{100 * hi:+.3f}] до изд. {100 * tr['gross'].mean():+.3f}% | "
            f"Σ {100 * tr['net'].sum():+7.0f}% (½: {100 * h1.sum():+.0f} / {100 * h2.sum():+.0f}; 2г {100 * fr.sum():+.0f}, "
            f"n {len(fr)}) | просадка {100 * dd:+.0f}% | случ. медиана {100 * np.median(ctl):+.3f}% ранг {rank:.3f}")


def dca_3commas(df, fund, rsi_lvl=38.0):
    """3Commas BTC/ETH RSI DCA: вход $500 при RSI14 < 38 на закрытии бара; доливы лимитками −2/−5/−9.5/−16/−25% от
    цены входа размерами 900/1620/2916/5249/9448 $; тейк +5.5% от средней; стопа нет; издержки 0.068% за сторону."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = df.index.to_numpy()
    r = S.rsi(c, 14)
    ft, cs = fund
    lv, sz = [0.02, 0.05, 0.095, 0.16, 0.25], [900, 1620, 2916, 5249, 9448]
    eq = np.zeros(len(c))
    real, pos, deals, worst = 0.0, None, [], 0.0
    for i in range(len(c) - 1):
        if pos is not None:
            q, cost, base, k, t0 = pos
            while k < 5 and l[i] <= base * (1 - lv[k]):
                px = min(o[i], base * (1 - lv[k]))
                q += sz[k] / px
                cost += sz[k]
                real -= sz[k] * S.COST
                k += 1
            avg = cost / q
            if h[i] >= avg * 1.055:
                px = max(o[i], avg * 1.055)
                f = cs[np.searchsorted(ft, t[i])] - cs[np.searchsorted(ft, t0)]
                pnl = q * px - cost - q * px * S.COST - f * cost
                real += pnl + 0.0
                deals.append((t0, t[i], k, pnl, cost))
                pos = None
            else:
                pos = (q, cost, base, k, t0)
        if pos is None and r[i] < rsi_lvl and not np.isnan(r[i]):
            px = o[i + 1]
            pos = (500 / px, 500.0, px, 0, t[i + 1])
            real -= 500 * S.COST
        mtm = 0.0 if pos is None else pos[0] * c[i] - pos[1]
        worst = min(worst, mtm)
        eq[i] = real + mtm
    eq = eq[:-1]                                           # последний элемент не заполняется циклом (был ложный 0)
    dd = float((eq - np.maximum.accumulate(eq)).min())
    d = pd.DataFrame(deals, columns=["t0", "t1", "ao", "pnl", "cost"])
    fr = d[d["t0"] >= FRESH]
    return (f"сделок {len(d)}, закрыто ${d['pnl'].sum():+,.0f}, итог с открытой ${eq[-1]:+,.0f}, худшая открытая "
            f"${worst:+,.0f} (нужно капитала до $20,643), просадка ${dd:+,.0f}; все 5 доливов {int((d['ao'] == 5).sum())}; "
            f"2г: {len(fr)} сделок ${fr['pnl'].sum():+,.0f}; половины ${d[d['t0'] < SPLIT]['pnl'].sum():+,.0f} / "
            f"${d[d['t0'] >= SPLIT]['pnl'].sum():+,.0f}; открыта в конце: {'да' if pos else 'нет'}")


def vol_target(df, target=45.0):
    """Vol-Target Trend Engine: дневки; доля = min(1, цель 45% / реализованная волатильность 20 дн., годовая) при
    close > SMA200, иначе 0; ребаланс, если доля ушла дальше 10% от цели; издержки на оборот. Сравнение: та же SMA200
    без таргетирования (доля 1) и купить-держать."""
    c = df["close"].to_numpy()
    ret = np.r_[0.0, c[1:] / c[:-1] - 1]
    vol = pd.Series(ret).rolling(20).std(ddof=0).to_numpy() * np.sqrt(365) * 100
    s200 = S.sma(c, 200)
    res = {}
    for name, use_vt in (("vol-target", True), ("SMA200 без таргета", False)):
        eq, w, curve = 1.0, 0.0, []
        for i in range(1, len(c)):
            eq *= 1 + w * ret[i]
            want = (min(1.0, target / vol[i - 1]) if use_vt else 1.0) if (c[i - 1] > s200[i - 1]) and not np.isnan(vol[i - 1]) else 0.0
            if (want == 0 and w > 0) or (want > 0 and (w == 0 or abs(want - w) > 0.1 * want)):
                eq *= 1 - abs(want - w) * S.COST
                w = want
            curve.append(eq)
        curve = np.array(curve)
        res[name] = curve
    bh = c[1:] / c[1]
    res["купить-держать"] = bh
    out = []
    idx = df.index[1:]
    for k, cur in res.items():
        dd = float((cur / np.maximum.accumulate(cur) - 1).min())
        fr = cur[idx >= FRESH]
        out.append(f"{k}: ×{cur[-1] / cur[200]:.1f} с прогрева, просадка {100 * dd:.0f}%, 2г ×{fr[-1] / fr[0]:.2f}")
    return "; ".join(out)


def main():
    for sym, path in (("BTCUSDT", sys.argv[1]), ("ETHUSDT", sys.argv[2])):
        bb = bars(path)
        fund = funding(sym)
        print(f"== {sym}: {bb['1h'].index[0]} … {bb['1h'].index[-1]}", flush=True)
        for name, (fn, tfs) in S.STRATS.items():
            for tf in tfs:
                df = bb[tf]
                tr = evaluate(df, fn(tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))), fund)
                ctl = random_control(df, tr, fund) if not tr.empty else np.zeros(REPS)
                print(line(name, tf, sym, tr, ctl), flush=True)
        for tf in ("1h", "4h"):
            print(f"3Commas RSI DCA {tf} {sym[:3]}: " + dca_3commas(bb[tf], fund), flush=True)
        print(f"Vol-Target {sym[:3]}: " + vol_target(bb["1d"]), flush=True)


if __name__ == "__main__":
    main()
