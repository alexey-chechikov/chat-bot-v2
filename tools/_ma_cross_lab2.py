"""MA-cross lab, phase 2: crossing GEOMETRY on the phase-1 winners (EMA 14/77 hl2 = transferable,
LWMA 50/77 open = BTC-best). Per operator 2026-06-12:
 - touch vs real cross (hysteresis eps),
 - setup CANCEL (fast re-cross back within N bars),
 - where NOT to enter (extension from slow, slope against, lines merged, against regime-200),
 - where signal IMPROVES (3-line stack confirm, slope agree, volume),
 - 4th line = regime 200 gate, 5th line = fast-7 early exit.
All variants = same SAR accounting as phase 1 (fee 0.1%/reversal), halves h1/h2 = anti-overfit."""
import numpy as np, pandas as pd, sys

FEE = 0.0005

def load(sym, tf="4h"):
    d = pd.read_csv(f"data/ma_lab/{sym}_1h.csv", index_col=0, parse_dates=True)
    if tf != "1h":
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
    e1 = s.ewm(span=n, adjust=False).mean(); e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3

def run_pos(close, pos):
    """pos: -1/0/+1 series aligned to close (signal at bar close -> exposure next bar)."""
    lr = np.log(close).diff().to_numpy()
    p = pos.shift(1).fillna(0.0).to_numpy()
    strat = p * lr
    fees = np.abs(np.diff(p, prepend=0.0)) * FEE
    net = strat - fees
    half = len(p) // 2
    eq = np.nancumsum(net)
    dd = float((np.maximum.accumulate(eq) - eq).max()) * 100
    chg = np.flatnonzero(np.diff(p) != 0)
    seg = np.split(np.arange(len(p)), chg + 1)
    tr = [np.nansum(strat[s]) - 2 * FEE for s in seg if len(s) and p[s[0]] != 0]
    tr = np.array(tr)
    gp, gl = tr[tr > 0].sum(), -tr[tr < 0].sum()
    return dict(n=len(tr), net=float(np.nansum(net)) * 100,
                h1=float(np.nansum(net[:half])) * 100, h2=float(np.nansum(net[half:])) * 100,
                pf=gp / gl if gl > 0 else np.inf, wr=float((tr > 0).mean()) * 100 if len(tr) else 0,
                mdd=dd)

def hysteresis_pos(diff_pct, eps):
    """Flip only when |fast-slow|/price crosses eps in the new direction (touch != cross)."""
    v = diff_pct.to_numpy()
    pos = np.zeros(len(v))
    cur = 0.0
    for i in range(len(v)):
        if np.isnan(v[i]):
            pos[i] = cur; continue
        if v[i] > eps:
            cur = 1.0
        elif v[i] < -eps:
            cur = -1.0
        pos[i] = cur
    return pd.Series(pos, index=diff_pct.index)

def fmt(name, m):
    return (f"{name:42}{m['n']:>5}{m['net']:>7.0f}{m['h1']:>7.0f}{m['h2']:>7.0f}"
            f"{m['pf']:>6.2f}{m['wr']:>5.0f}{m['mdd']:>6.0f}")

def trades_with_features(close, pos, feats):
    """Segment SAR trades; attach entry-bar features. Returns DataFrame."""
    lr = np.log(close).diff().to_numpy()
    p = pos.shift(1).fillna(0.0).to_numpy()
    strat = p * lr
    chg = np.flatnonzero(np.diff(p) != 0)
    seg = np.split(np.arange(len(p)), chg + 1)
    rows = []
    for s in seg:
        if not len(s) or p[s[0]] == 0:
            continue
        ei = s[0] - 1  # signal bar (entry decision)
        if ei < 0: continue
        row = dict(ret=(np.nansum(strat[s]) - 2 * FEE) * 100, dur=len(s), side=p[s[0]], i=ei)
        for k, v in feats.items():
            row[k] = float(v.iloc[ei]) if not np.isnan(v.iloc[ei]) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)

def cond_table(tdf, name, mask):
    a, b = tdf[mask], tdf[~mask]
    if len(a) < 5 or len(b) < 5:
        return f"{name:38} —  мало данных ({len(a)} vs {len(b)})"
    return (f"{name:38} ДА: n={len(a):>3} avg{a.ret.mean():>6.2f}% win{(a.ret>0).mean()*100:>4.0f}%  |"
            f"  НЕТ: n={len(b):>3} avg{b.ret.mean():>6.2f}% win{(b.ret>0).mean()*100:>4.0f}%")

def analyze(sym, meth, price, f_, s_, mid_, tf="4h"):
    d = load(sym, tf)
    close = d["close"]; src = applied(d, price)
    fast, slow = ma(src, f_, meth), ma(src, s_, meth)
    mid = ma(src, mid_, meth)
    reg = ma(src, 200, meth)         # 4-я линия: режим
    xfast = ma(src, 7, meth)         # 5-я линия: триггер выхода
    diff_pct = (fast - slow) / close * 100
    atr = (d["high"] - d["low"]).rolling(14).mean()
    volx = d["volume"] / d["volume"].rolling(60).median()
    slope_s = slow.diff(5) / close * 100
    spread_pct = (fast - slow).abs() / close * 100
    ext_atr = (close - slow).abs() / atr

    print(f"\n###### {sym} {tf}  {meth} {f_}/{s_} ({price}), mid={mid_}, reg=200, xfast=7 ######")
    print(f"{'вариант':42}{'n':>5}{'net%':>7}{'h1%':>7}{'h2%':>7}{'PF':>6}{'win':>5}{'DD%':>6}")
    base_pos = hysteresis_pos(diff_pct, 0.0)
    print(fmt("A базовый кросс (SAR)", run_pos(close, base_pos)))
    # --- ТЗ: касание != пересечение (гистерезис eps) ---
    for eps in (0.05, 0.1, 0.2, 0.35):
        print(fmt(f"B гистерезис eps={eps}% (анти-касание)", run_pos(close, hysteresis_pos(diff_pct, eps))))
    # --- 4-я линия: режим-200 гейт (против режима -> флэт) ---
    regpos = base_pos.where(((base_pos > 0) & (close > reg)) | ((base_pos < 0) & (close < reg)), 0.0)
    print(fmt("D +линия 200: против режима -> ФЛЭТ", run_pos(close, regpos)))
    # --- 3 линии: полный стек (fast>mid>slow / fast<mid<slow), иначе флэт ---
    stack = pd.Series(np.where((fast > mid) & (mid > slow), 1.0,
                       np.where((fast < mid) & (mid < slow), -1.0, 0.0)), index=close.index)
    print(fmt(f"E стек 3 линий ({f_}>{mid_}>{s_}), иначе флэт", run_pos(close, stack)))
    # --- стек + режим ---
    stackreg = stack.where(((stack > 0) & (close > reg)) | ((stack < 0) & (close < reg)), 0.0)
    print(fmt("F стек + линия 200", run_pos(close, stackreg)))
    # --- 5-я линия: ранний выход по xfast(7) против позиции ---
    ex = base_pos.copy().to_numpy()
    xf = xfast.to_numpy(); md = mid.to_numpy()
    for i in range(len(ex)):
        if ex[i] > 0 and xf[i] < md[i]: ex[i] = 0.0
        elif ex[i] < 0 and xf[i] > md[i]: ex[i] = 0.0
    print(fmt(f"G A + выход по 7x{mid_} против позиции", run_pos(close, pd.Series(ex, index=close.index))))

    # --- трейд-анализ: где НЕ входить / где сигнал сильнее ---
    feats = dict(slope_s=slope_s, ext_atr=ext_atr, volx=volx,
                 reg_agree=pd.Series(np.where(close > reg, 1.0, -1.0), index=close.index),
                 spread_prev=spread_pct.rolling(10).mean().shift(1))
    tdf = trades_with_features(close, base_pos, feats)
    tdf["slope_agree"] = np.sign(tdf.slope_s) == tdf.side
    tdf["regime_agree"] = tdf.reg_agree == tdf.side
    med_ext = tdf.ext_atr.median(); med_spr = tdf.spread_prev.median()
    print("\n  Условия в МОМЕНТ пересечения (трейд-статистика базового A):")
    print("  " + cond_table(tdf, "наклон slow ПО направлению кросса", tdf.slope_agree))
    print("  " + cond_table(tdf, "режим-200 ПО направлению", tdf.regime_agree))
    print("  " + cond_table(tdf, f"цена растянута от slow (> {med_ext:.1f} ATR)", tdf.ext_atr > med_ext))
    print("  " + cond_table(tdf, "объём на кроссе > 1.2x медианы", tdf.volx > 1.2))
    print("  " + cond_table(tdf, f"линии до кросса слиплись (<{med_spr:.2f}%)", tdf.spread_prev < med_spr))
    # --- отмена сетапа: быстрый обратный кросс ---
    quick = tdf.dur <= 4
    nxt = tdf.ret.shift(-1)
    print("\n  ОТМЕНА сетапа (обратный кросс <=4 баров):")
    print(f"  быстрых разворотов: {quick.sum()}/{len(tdf)} ({quick.mean()*100:.0f}%), их сред.исход {tdf[quick].ret.mean():+.2f}%")
    print(f"  СЛЕДУЮЩИЙ трейд после быстрого разворота: avg {nxt[quick].mean():+.2f}% (win {(nxt[quick]>0).mean()*100:.0f}%)"
          f"  vs после нормального: avg {nxt[~quick].mean():+.2f}% (win {(nxt[~quick]>0).mean()*100:.0f}%)")
    return tdf

if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "XBTUSDT"
    analyze(sym, "EMA", "hl2", 14, 77, 34)
    analyze(sym, "LWMA", "open", 50, 77, 63)
