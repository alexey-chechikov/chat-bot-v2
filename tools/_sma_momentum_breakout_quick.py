"""Быстрая ВЕРНАЯ реализация ядра TZ-5M-SMA-MOMENTUM-BREAKOUT (не полный модуль — проверка edge до P2-стройки).
Look-ahead-free: сигнал на close[t], вход open[t+1]+slippage, SL/TP по high/low со stop_first, gap-обработка,
тейкер-комиссия обе стороны. Reference + свип, train/val/OOS. Данные backtests/frozen/BTCUSDT_1m_2y.csv."""
import numpy as np, pandas as pd, itertools, sys
from pathlib import Path

PX = Path("backtests/frozen/BTCUSDT_1m_2y.csv")
TAKER, SLIP, NOTION = 0.075, 0.02, 1000.0   # % на сторону; $ ноционал

def load_5m():
    df = pd.read_csv(PX)
    tcol = "ts" if "ts" in df.columns else df.columns[0]
    df[tcol] = pd.to_datetime(df[tcol], unit="ms" if np.issubdtype(df[tcol].dtype, np.number) else None, utc=True)
    df = df.set_index(tcol).sort_index()
    g = df.resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    g["count"] = df["close"].resample("5min", label="left", closed="left").count()
    return g[g["count"] == 5].drop(columns="count").dropna()

def atr_wilder(h, l, c, n=14):
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(1)
    return tr, tr.ewm(alpha=1 / n, adjust=False).mean()

def signals(d, fast, slow, L, mode, vmode, vthr):
    c, o, h, l = d["close"], d["open"], d["high"], d["low"]
    fs, ss = c.rolling(fast).mean(), c.rolling(slow).mean()
    tr, atr = atr_wilder(h, l, c)
    vr = tr / atr.shift(1)
    if mode == "rolling_extreme":
        up = c > c.shift(1).rolling(L).max(); dn = c < c.shift(1).rolling(L).min()
    else:  # lag_close
        up = c > c.shift(L); dn = c < c.shift(L)
    vok = pd.Series(True, index=d.index) if vmode == "none" else (vr >= vthr)
    longs = (fs > ss) & (c > o) & up & vok
    shorts = (fs < ss) & (c < o) & dn & vok
    return longs.fillna(False).to_numpy(), shorts.fillna(False).to_numpy()

def simulate(d, longs, shorts, sl_pct, tp_pct):
    o = d["open"].to_numpy(); h = d["high"].to_numpy(); l = d["low"].to_numpy(); c = d["close"].to_numpy()
    n = len(d); i = 0; trades = []
    while i < n - 1:
        side = 1 if longs[i] else (-1 if shorts[i] else 0)
        if side == 0:
            i += 1; continue
        e = i + 1                                   # вход на open[t+1]
        fill = o[e] * (1 + side * SLIP / 100)
        stop = fill * (1 - side * sl_pct / 100); tp = fill * (1 + side * tp_pct / 100)
        exit_fill = None
        j = e
        while j < n:
            oj, hj, lj = o[j], h[j], l[j]
            if side == 1:
                if oj <= stop: exit_fill = oj * (1 - SLIP / 100); break        # gap через стоп
                if oj >= tp:   exit_fill = tp; break
                hit_sl = lj <= stop; hit_tp = hj >= tp
                if hit_sl: exit_fill = stop * (1 - SLIP / 100); break          # stop_first
                if hit_tp: exit_fill = tp; break
            else:
                if oj >= stop: exit_fill = oj * (1 + SLIP / 100); break
                if oj <= tp:   exit_fill = tp; break
                hit_sl = hj >= stop; hit_tp = lj <= tp
                if hit_sl: exit_fill = stop * (1 + SLIP / 100); break
                if hit_tp: exit_fill = tp; break
            j += 1
        if exit_fill is None:
            exit_fill = c[-1] * (1 - side * SLIP / 100); j = n - 1
        ret = side * (exit_fill / fill - 1)
        gross = ret * NOTION
        fees = (NOTION * TAKER / 100) * 2
        trades.append((gross - fees, side, j - e))
        i = j + 1                                   # одна поза за раз
    return trades

def metrics(trades, eq0=15000):
    if not trades:
        return dict(n=0, net=0, pf=0, wr=0, exp_r=0, dd=0, dd_pct=0)
    pnl = np.array([t[0] for t in trades])
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    eqcurve = eq0 + np.cumsum(pnl)
    dd = float((np.maximum.accumulate(eqcurve) - eqcurve).max())
    risk = NOTION * 0.015                          # 1R ≈ SL 1.5% notional (для exp_r ориентир)
    return dict(n=len(pnl), net=float(pnl.sum()), pf=(gp / gl if gl > 0 else np.inf),
                wr=float((pnl > 0).mean()) * 100, exp_r=float(pnl.mean() / risk),
                dd=dd, dd_pct=dd / eq0 * 100)

def run_cfg(d, cfg):
    lo, sh = signals(d, *cfg[:6])
    return metrics(simulate(d, lo, sh, cfg[6], cfg[7]))

def seg(d, a, b): return d.iloc[int(len(d) * a):int(len(d) * b)]

def main():
    d = load_5m()
    print(f"5m баров: {len(d)}  период {d.index[0]:%Y-%m-%d} → {d.index[-1]:%Y-%m-%d}")
    REF = (20, 50, 20, "rolling_extreme", "none", 1.5, 1.5, 3.0)
    tr, va, oos = seg(d, 0, .6), seg(d, .6, .8), seg(d, .8, 1.0)
    print(f"\n=== REFERENCE (20/50, 20-bar rolling_extreme, no-vol, SL1.5/TP3.0) ===")
    for nm, s in [("train", tr), ("val", va), ("OOS", oos), ("FULL", d)]:
        m = run_cfg(s, REF)
        print(f"  {nm:5} n={m['n']:>4} net ${m['net']:>+8.0f} PF {m['pf']:>4.2f} win {m['wr']:>4.1f}% "
              f"expR {m['exp_r']:>+5.2f} DD ${m['dd']:>6.0f} ({m['dd_pct']:.1f}%)")
    # свип на train, выбор по val, прогон OOS
    pairs = [(10, 50), (20, 50), (20, 100), (50, 100)]
    rows = []
    for (f, s), L, mode, (vm, vt), (sl, tp) in itertools.product(
            pairs, [10, 20, 30], ["rolling_extreme", "lag_close"],
            [("none", 0), ("tr_atr", 1.0), ("tr_atr", 1.25), ("tr_atr", 1.5)], [(1.0, 2.0), (1.5, 3.0), (2.0, 4.0)]):
        cfg = (f, s, L, mode, vm, vt, sl, tp)
        mt = run_cfg(tr, cfg)
        if mt["n"] >= 50 and mt["net"] > 0 and mt["pf"] > 1.0:
            score = min(mt["pf"], 3.0) * np.sign(mt["net"]) * np.sqrt(max(mt["n"], 1)) / max(mt["dd"], 1)
            rows.append((score, cfg, mt))
    rows.sort(key=lambda r: -r[0])
    print(f"\n=== СВИП: {len(rows)} конфигов прошли train-фильтр (n≥50, net>0, PF>1) из 288 ===")
    if not rows:
        print("  НИ ОДИН конфиг не прошёл даже train-фильтр (net>0 на train).")
    else:
        # топ-10 train → лучший по val → OOS
        val_ranked = []
        for score, cfg, mt in rows[:10]:
            mv = run_cfg(va, cfg)
            vs = min(mv["pf"], 3.0) * np.sign(mv["net"]) * np.sqrt(max(mv["n"], 1)) / max(mv["dd"], 1)
            val_ranked.append((vs, cfg, mt, mv))
        val_ranked.sort(key=lambda r: -r[0])
        print("  топ-3 по VALIDATION → финальный OOS:")
        for vs, cfg, mt, mv in val_ranked[:3]:
            mo = run_cfg(oos, cfg)
            print(f"  cfg {cfg}")
            print(f"     train net ${mt['net']:>+7.0f} PF{mt['pf']:.2f} | val ${mv['net']:>+7.0f} PF{mv['pf']:.2f} "
                  f"| OOS n={mo['n']} net ${mo['net']:>+7.0f} PF{mo['pf']:.2f} win{mo['wr']:.0f}% expR{mo['exp_r']:+.2f} DD{mo['dd_pct']:.1f}%")

if __name__ == "__main__":
    main()
