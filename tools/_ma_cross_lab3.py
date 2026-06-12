"""MA-cross lab, phase 3: assemble entry FILTERS found on BTC into a ruleset and validate
cross-symbol (ETH/SOL were not used to derive the rules -> honest instrument-OOS).
Filters at cross moment (from phase-2 trade stats, BTC 4h):
  F-slope: slow MA 5-bar slope agrees with cross direction (counter-slope avg was negative)
  F-regime: price on the cross side of MA200 (counter-regime avg ~0)
  F-whip: previous cross-to-cross leg lasted <=4 bars -> skip this signal (post-whipsaw next trade was negative)
Skip -> FLAT until the next cross. Same accounting (fee 0.1%/reversal, h1/h2 halves)."""
import numpy as np, pandas as pd, sys
from _ma_cross_lab2 import load, applied, ma, run_pos, fmt

def filtered_pos(close, src, meth, f_, s_, use_slope, use_regime, use_whip):
    fast, slow = ma(src, f_, meth), ma(src, s_, meth)
    reg = ma(src, 200, meth)
    slope = slow.diff(5)
    sign = np.sign((fast - slow).to_numpy())
    cl = close.to_numpy(); sl = slope.to_numpy(); rg = reg.to_numpy()
    pos = np.zeros(len(sign))
    cur, last_cross, prev_leg = 0.0, -1, 999
    for i in range(1, len(sign)):
        if np.isnan(sign[i]) or sign[i] == 0 or sign[i] == sign[i - 1]:
            pos[i] = cur
            continue
        # cross event
        side = sign[i]
        prev_leg = i - last_cross if last_cross >= 0 else 999
        last_cross = i
        ok = True
        if use_slope and not (np.sign(sl[i]) == side):
            ok = False
        if use_regime and not ((side > 0) == (cl[i] > rg[i])):
            ok = False
        if use_whip and prev_leg <= 4:
            ok = False
        cur = side if ok else 0.0
        pos[i] = cur
    return pd.Series(pos, index=close.index)

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT", "SOLUSDT"]
    meth, price, f_, s_ = "EMA", "hl2", 14, 77
    for sym in syms:
        d = load(sym, "4h")
        close = d["close"]; src = applied(d, price)
        print(f"\n=== {sym} 4h  EMA 14/77 hl2 ===")
        print(f"{'вариант':42}{'n':>5}{'net%':>7}{'h1%':>7}{'h2%':>7}{'PF':>6}{'win':>5}{'DD%':>6}")
        variants = [
            ("A база SAR", (False, False, False)),
            ("H1 фильтр: наклон slow по кроссу", (True, False, False)),
            ("H2 фильтр: режим-200 по кроссу", (False, True, False)),
            ("H3 фильтр: пропуск после whipsaw<=4", (False, False, True)),
            ("H4 наклон + whipsaw", (True, False, True)),
            ("H5 все три", (True, True, True)),
        ]
        for name, (us, ur, uw) in variants:
            p = filtered_pos(close, src, meth, f_, s_, us, ur, uw)
            print(fmt(name, run_pos(close, p)))

if __name__ == "__main__":
    main()
