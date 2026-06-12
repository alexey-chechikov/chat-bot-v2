"""MA-cross lab, phase 1: mass sweep of 2-MA crossover combos (stop-and-reverse).
Per operator TZ 2026-06-12: periods incl. 7/12/13/14/34/77, methods SMA/EMA/SMMA/LWMA (+TEMA,
our v11 indicator uses it), applied price close/open/hl2/hlc3/ohlc4, TFs 1h/4h/1d, BTC/ETH/SOL.
Robustness: net return reported per half of the 2y sample; sort favors both-halves-positive.
Fee 0.05%/side (0.1% per reversal). Data: data/ma_lab/*_1h.csv (BitMEX)."""
import numpy as np, pandas as pd, itertools, sys

FEE = 0.0005          # per side, per unit turnover
PERIODS = [5, 7, 9, 12, 13, 14, 21, 34, 50, 77, 100, 144, 200]
METHODS = ["SMA", "EMA", "SMMA", "LWMA", "TEMA"]
PRICES = ["close", "open", "hl2", "hlc3", "ohlc4"]
MIN_RATIO = 1.5       # slow/fast — closer pairs just hug each other (TZ: «линии сливаются»)

def load(sym, tf):
    d = pd.read_csv(f"data/ma_lab/{sym}_1h.csv", index_col=0, parse_dates=True)
    if tf != "1h":
        tf = tf.upper().replace("H", "h")  # old pandas wants 1D not 1d
        d = d.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"}).dropna()
    return d

def applied(d, p):
    if p == "close": return d["close"]
    if p == "open":  return d["open"]
    if p == "hl2":   return (d["high"] + d["low"]) / 2
    if p == "hlc3":  return (d["high"] + d["low"] + d["close"]) / 3
    return (d["open"] + d["high"] + d["low"] + d["close"]) / 4

def ma(s, n, method):
    if method == "SMA":  return s.rolling(n).mean()
    if method == "EMA":  return s.ewm(span=n, adjust=False).mean()
    if method == "SMMA": return s.ewm(alpha=1 / n, adjust=False).mean()
    if method == "LWMA":
        w = np.arange(1, n + 1, dtype=float)
        return s.rolling(n).apply(lambda x: (x * w).sum() / w.sum(), raw=True)
    e1 = s.ewm(span=n, adjust=False).mean()
    e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3   # TEMA

def evaluate(close, fast, slow):
    """Stop-and-reverse on sign(fast-slow). Returns dict of metrics (log-return based)."""
    pos = np.sign((fast - slow).to_numpy())
    lr = np.log(close).diff().to_numpy()
    valid = ~np.isnan(pos)
    pos[~valid] = 0.0
    p = pd.Series(pos, index=close.index).shift(1).fillna(0.0).to_numpy()
    strat = p * lr
    fees = np.abs(np.diff(p, prepend=0.0)) * FEE
    net = strat - fees
    # trade segmentation
    chg = np.flatnonzero(np.diff(p) != 0)
    seg = np.split(np.arange(len(p)), chg + 1)
    trades = []
    for s_idx in seg:
        if len(s_idx) == 0 or p[s_idx[0]] == 0:
            continue
        r = np.nansum(strat[s_idx]) - 2 * FEE
        trades.append((r, len(s_idx), p[s_idx[0]]))
    if len(trades) < 6:
        return None
    tr = np.array([t[0] for t in trades]); ln = np.array([t[1] for t in trades])
    side = np.array([t[2] for t in trades])
    half = len(p) // 2
    gp, gl = tr[tr > 0].sum(), -tr[tr < 0].sum()
    eq = np.nancumsum(net)
    dd = float((np.maximum.accumulate(eq) - eq).max()) * 100
    return dict(n=len(tr), net=float(np.nansum(net)) * 100,
                h1=float(np.nansum(net[:half])) * 100, h2=float(np.nansum(net[half:])) * 100,
                pf=gp / gl if gl > 0 else np.inf, wr=float((tr > 0).mean()) * 100,
                whip=float((ln <= 3).mean()) * 100, mdd=dd,
                netL=float(tr[side > 0].sum()) * 100, netS=float(tr[side < 0].sum()) * 100)

def sweep(sym, tf):
    d = load(sym, tf)
    close = d["close"]
    bh = float(np.log(close.iloc[-1] / close.iloc[0])) * 100
    cache = {}
    for meth, pr in itertools.product(METHODS, PRICES):
        s = applied(d, pr)
        for n in PERIODS:
            cache[(meth, pr, n)] = ma(s, n, meth)
    rows = []
    for meth, pr in itertools.product(METHODS, PRICES):
        for f, s in itertools.combinations(PERIODS, 2):
            if s / f < MIN_RATIO:
                continue
            m = evaluate(close, cache[(meth, pr, f)], cache[(meth, pr, s)])
            if m:
                rows.append(dict(meth=meth, price=pr, fast=f, slow=s, **m))
    df = pd.DataFrame(rows)
    df["minh"] = df[["h1", "h2"]].min(axis=1)
    df["robust"] = (df["h1"] > 0) & (df["h2"] > 0)
    return df, bh, len(close)

def show(df, bh, nbars, sym, tf, top=12):
    print(f"\n=== {sym} {tf}  ({nbars} bars, buy&hold {bh:+.0f}% log) ===")
    best = df.sort_values(["robust", "minh"], ascending=False).head(top)
    print(f"{'meth':5}{'price':6}{'f/s':>8}{'n':>5}{'net%':>7}{'h1%':>7}{'h2%':>7}"
          f"{'PF':>6}{'win%':>6}{'whip%':>6}{'DD%':>6}{'L%':>7}{'S%':>7}")
    for _, r in best.iterrows():
        print(f"{r.meth:5}{r.price:6}{f'{r.fast}/{r.slow}':>8}{r.n:>5}{r.net:>7.0f}{r.h1:>7.0f}"
              f"{r.h2:>7.0f}{r.pf:>6.2f}{r.wr:>6.0f}{r.whip:>6.0f}{r.mdd:>6.0f}{r.netL:>7.0f}{r.netS:>7.0f}")
    nrob = int(df["robust"].sum())
    print(f"robust(оба полугода+): {nrob}/{len(df)} комбо; медиана net {df['net'].median():+.0f}%")

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT", "SOLUSDT"]
    tfs = sys.argv[2].split(",") if len(sys.argv) > 2 else ["1h", "4h", "1d"]
    store = {}
    for sym in syms:
        for tf in tfs:
            df, bh, nb = sweep(sym, tf)
            store[(sym, tf)] = df
            show(df, bh, nb, sym, tf)
            df.to_csv(f"data/ma_lab/sweep_{sym}_{tf}.csv", index=False)
    # reference: our v11 lines (TEMA close 50/100/200 pairs) on BTC 4h
    if ("XBTUSDT", "4h") in store:
        df = store[("XBTUSDT", "4h")]
        ref = df[(df.meth == "TEMA") & (df.price == "close") &
                 (df.fast.isin([50, 100])) & (df.slow.isin([100, 200]))]
        print("\n--- реф: наши линии v11 (TEMA close, BTC 4h) ---")
        print(ref[["fast", "slow", "n", "net", "h1", "h2", "pf", "wr", "whip", "mdd"]].to_string(index=False))

if __name__ == "__main__":
    main()
