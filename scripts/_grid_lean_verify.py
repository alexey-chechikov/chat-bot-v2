"""Независимая проверка H5-уклон vs MA100-свитч (методика Вина) на Binance BTC 4ч.
Экспозиция e∈[-1,+1], PnL = Σ e_prev·лог-доход. H5: +1/-1 после прошедшего H5-кросса,
0 если кросс не прошёл фильтры (нейтрал), холд до обратного кросса. Win BTC: MA100 84/31, H5 116/21."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT / "scripts"))
import _elliott_on_macross as e  # load(), ema(), cross_signals()


def h5_pass(close, e77, e200, i, d):
    slope_ok = (e77[i] - e77[i - 5] > 0) == (d == 1) if i >= 5 else False
    side_ok = (close[i] > e200[i]) == (d == 1)
    # анти-whipsaw: прошлая нога > 4 баров (по предыдущему кроссу) — приблизим в вызывающем коде
    return slope_ok and side_ok


def build_leans(df):
    close = df["close"].to_numpy(float)
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
    e14, e77, e200 = e.ema(hl2, 14), e.ema(hl2, 77), e.ema(hl2, 200)
    diff = e14 - e77
    sign = np.sign(diff)
    n = len(close)
    cx = [i for i in range(1, n) if sign[i] != 0 and sign[i] != sign[i - 1]]
    cx_set = {}
    for k, i in enumerate(cx):
        d = 1 if diff[i] > 0 else -1
        prev_leg = (i - cx[k - 1]) if k > 0 else 99
        leg_ok = prev_leg > 4
        passed = h5_pass(close, e77, e200, i, d) and leg_ok
        cx_set[i] = d if passed else 0
    # H5 lean: на кроссе ставим уклон (или нейтрал), держим до следующего кросса
    h5 = np.zeros(n); cur = 0.0
    for i in range(1, n):
        if i in cx_set:
            cur = float(cx_set[i])
        h5[i] = cur
    # MA100 lean: sign(close - SMA100), hold 3
    sma = pd.Series(close).rolling(100).mean().to_numpy()
    raw = np.sign(close - sma)
    ma = np.zeros(n); cur = 0.0; run = 0; prev = 0.0
    for i in range(n):
        if np.isnan(raw[i]):
            ma[i] = cur; continue
        if raw[i] == prev:
            run += 1
        else:
            run = 1; prev = raw[i]
        if run >= 3 and raw[i] != 0:
            cur = raw[i]
        ma[i] = cur
    return close, h5, ma


def stats(lean, lr, name):
    e_ = np.nan_to_num(lean)
    pnl = e_[:-1] * lr[1:]
    eq = np.cumsum(pnl)
    dd = float((np.maximum.accumulate(eq) - eq).max()) * 100 if len(eq) else 0
    net = eq[-1] * 100 if len(eq) else 0
    nf = e_[:-1] != 0
    right = (np.sign(e_[:-1][nf]) == np.sign(lr[1:][nf])).mean() * 100 if nf.sum() else 0
    flips = int((np.diff(np.sign(e_[e_ != 0])) != 0).sum()) if (e_ != 0).sum() > 1 else 0
    months = len(lr) / (6 * 30)
    half = len(pnl) // 2
    h1 = eq[half] * 100 if len(eq) > half else 0
    h2 = (eq[-1] - eq[half]) * 100 if len(eq) > half else 0
    return net, h1, h2, dd, right, flips / months if months else 0, nf.mean() * 100


def main():
    df = e.load("4h")
    close, h5, ma = build_leans(df)
    lr = np.log(pd.Series(close)).diff().fillna(0).to_numpy()
    print(f"Binance BTC 4ч, {len(close)} баров ≈ {len(close)/(6*30):.0f} мес\n")
    print(f"{'уклон':14}{'net%':>7}{'h1%':>7}{'h2%':>7}{'DD%':>6}{'прав%':>6}{'флип/мес':>9}{'экспо%':>7}")
    for nm, ln in [("symmetric(0)", np.zeros(len(close))), ("MA100 свитч", ma),
                   ("H5 свитч", h5), ("H5_cap ±0.5", h5 * 0.5), ("buy&hold", np.ones(len(close)))]:
        net, h1, h2, dd, right, fm, expo = stats(ln, lr, nm)
        star = "★" if h1 > 0 and h2 > 0 else " "
        print(f"{nm:14}{net:>7.0f}{h1:>7.0f}{h2:>7.0f}{dd:>6.0f}{right:>6.0f}{fm:>9.1f}{expo:>7.0f} {star}")
    print("\nWin BTC (BitMEX): MA100 84/DD31 · H5 116/DD21 · H5_cap 58/DD10")


if __name__ == "__main__":
    main()
