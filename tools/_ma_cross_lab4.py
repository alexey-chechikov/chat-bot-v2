"""MA-cross фаза-4: то, что я НЕ покрыл в первом заходе (по справедливому упрёку оператора).
Всё прежнее было «держать до обратного кросса». Здесь — три непокрытых рычага, все на 3 символах
с проверкой переноса (дисциплина «2 движка»):
  A. ВЫХОДЫ (половина стратегии, не трогал): slope-flip / EMA14-break / ATR-chandelier / фикс-таргет
  B. АСИММЕТРИЯ long/short (крипта секулярно вверх — H5 может быть однобокой)
  C. КОНВИКШН-разрез готовых входов H5 по силе (то, что нашёл Мак, но шире): наклон-магнитуда,
     растяжка, ER — какой РАЗДЕЛЯЕТ и ПЕРЕНОСИТСЯ на все 3 символа.
Выходы каузальны: условие на закрытии бара -> выход на СЛЕДУЮЩЕМ (без intrabar-фантазий — урок
paper-vs-live). Chandelier/таргет по close, не по intrabar-touch. Fee 0.05%/сторона. Данные data/ma_lab."""
import numpy as np, pandas as pd, sys
from _elliott_lab import load, FEE

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def h5_signals(d):
    """Список входов H5: (cross_i, side). Без выхода — выход задаёт политика."""
    close = d["close"]; hl2 = (d["high"] + d["low"]) / 2
    e14, e77, e200 = ema(hl2, 14), ema(hl2, 77), ema(hl2, 200)
    slope = e77.diff(5)
    diff = (e14 - e77).to_numpy()
    cl, sl, rg = close.to_numpy(), slope.to_numpy(), e200.to_numpy()
    sign = np.sign(diff); n = len(cl)
    sig = []; last_cross = -1
    for i in range(1, n):
        if np.isnan(sign[i]) or sign[i] == 0 or sign[i] == sign[i - 1]:
            continue
        side = int(sign[i]); prev_leg = i - last_cross if last_cross >= 0 else 999; last_cross = i
        if ((sl[i] > 0) == (side > 0)) and ((cl[i] > rg[i]) == (side > 0)) and prev_leg > 4:
            sig.append((i, side))
    return sig

def exit_index(d, ei, side, policy, e14, e77, slope, atr, opp_cross):
    """Каузальный выход: возвращает бар выхода (close-based, сигнал->следующий бар)."""
    cl = d["close"].to_numpy(); n = len(cl)
    e14a, e77a, sla, atra = e14.to_numpy(), e77.to_numpy(), slope.to_numpy(), atr.to_numpy()
    hi_close = cl[ei]
    for j in range(ei + 1, n):
        if policy == "base":
            if opp_cross[j] == -side:
                return j
        elif policy == "slope_flip":
            if (sla[j] > 0) != (side > 0):
                return j
        elif policy == "ema14_break":
            if (cl[j] - e14a[j]) * side < 0:
                return j
        elif policy == "chandelier":
            hi_close = max(hi_close, cl[j]) if side > 0 else min(hi_close, cl[j])
            if side > 0 and cl[j] < hi_close - 3 * atra[j]:
                return j
            if side < 0 and cl[j] > hi_close + 3 * atra[j]:
                return j
            if opp_cross[j] == -side:
                return j
        elif policy == "target2R":
            move = (cl[j] - cl[ei]) * side
            if move > 2 * atra[ei]:
                return j
            if move < -1 * atra[ei]:
                return j
            if opp_cross[j] == -side:
                return j
    return n - 1

def metrics(rets, eis, n):
    if len(rets) < 5:
        return None
    rets = np.array(rets); eis = np.array(eis); half = n // 2
    gp, gl = rets[rets > 0].sum(), -rets[rets < 0].sum()
    eq = np.cumsum(rets); dd = float((np.maximum.accumulate(eq) - eq).max()) * 100
    return dict(n=len(rets), net=rets.sum() * 100, h1=rets[eis < half].sum() * 100,
                h2=rets[eis >= half].sum() * 100, pf=gp / gl if gl > 0 else 9,
                wr=(rets > 0).mean() * 100, mdd=dd)

def run_policy(d, sig, policy):
    close = d["close"]; hl2 = (d["high"] + d["low"]) / 2
    e14, e77 = ema(hl2, 14), ema(hl2, 77); slope = e77.diff(5)
    diff = (e14 - e77).to_numpy(); sign = np.sign(diff); n = len(close)
    # бар обратного кросса -> знак новой стороны
    opp = np.zeros(n)
    for i in range(1, n):
        if not np.isnan(sign[i]) and sign[i] != 0 and sign[i] != sign[i - 1]:
            opp[i] = sign[i]
    tr = (d["high"] - d["low"]); atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    lr = np.log(close).to_numpy(); rets, eis = [], []
    for (ei, side) in sig:
        xi = exit_index(d, ei, side, policy, e14, e77, slope, atr, opp)
        if xi > ei:
            rets.append(side * (lr[xi] - lr[ei]) - 2 * FEE); eis.append(ei)
    return metrics(rets, eis, n)

def base_trades(d, sig):
    """База held-to-reverse для разрезов B/C: (ei, xi, side, slope_mag, stretch, er)."""
    close = d["close"]; hl2 = (d["high"] + d["low"]) / 2
    e14, e77, e200 = ema(hl2, 14), ema(hl2, 77), ema(hl2, 200); slope = e77.diff(5)
    diff = (e14 - e77).to_numpy(); sign = np.sign(diff); n = len(close)
    cl = close.to_numpy(); e77a = e77.to_numpy(); sla = slope.to_numpy()
    opp = []
    for i in range(1, n):
        if not np.isnan(sign[i]) and sign[i] != 0 and sign[i] != sign[i - 1]:
            opp.append(i)
    out = []
    for (ei, side) in sig:
        xi = next((c for c in opp if c > ei), n - 1)
        lr = np.log(cl)
        ret = (side * (lr[xi] - lr[ei]) - 2 * FEE) * 100
        slope_mag = abs(sla[ei]) / cl[ei] * 100
        stretch = abs(cl[ei] - e77a[ei]) / cl[ei] * 100
        er = abs(cl[ei] - cl[ei - 12]) / np.abs(np.diff(cl[ei - 12:ei + 1])).sum() if ei >= 12 else np.nan
        out.append(dict(ei=ei, xi=xi, side=side, ret=ret, slope_mag=slope_mag, stretch=stretch, er=er))
    return pd.DataFrame(out), n

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT", "SOLUSDT"]
    policies = ["base", "slope_flip", "ema14_break", "chandelier", "target2R"]
    print("########## A. ВЫХОДЫ (3 символа) ##########")
    for sym in syms:
        d = load(sym, "4h"); sig = h5_signals(d)
        print(f"\n=== {sym} 4h ({len(sig)} входов H5) ===")
        print(f"{'политика выхода':16}{'n':>4}{'net%':>7}{'h1%':>6}{'h2%':>6}{'PF':>6}{'win':>5}{'DD%':>6}")
        for pol in policies:
            m = run_policy(d, sig, pol)
            if m:
                star = "★" if m['h1'] > 0 and m['h2'] > 0 else " "
                print(f"{pol:16}{m['n']:>4}{m['net']:>7.0f}{m['h1']:>6.0f}{m['h2']:>6.0f}"
                      f"{m['pf']:>6.2f}{m['wr']:>5.0f}{m['mdd']:>6.0f} {star}")
    print("\n########## B. АСИММЕТРИЯ long/short (база, 3 символа) ##########")
    for sym in syms:
        d = load(sym, "4h"); sig = h5_signals(d); df, n = base_trades(d, sig)
        for nm, sub in [("ВСЕ", df), ("LONG", df[df.side > 0]), ("SHORT", df[df.side < 0])]:
            if len(sub) >= 3:
                r = sub.ret.values; gp, gl = r[r > 0].sum(), -r[r < 0].sum()
                print(f"  {sym:8} {nm:6} n={len(sub):>3} net{r.sum():>6.0f}% avg{r.mean():>5.2f}% "
                      f"win{(r>0).mean()*100:>4.0f}% PF{gp/gl if gl>0 else 9:>5.2f}")
    print("\n########## C. КОНВИКШН-разрез (верхняя/нижняя половина по силе, 3 символа) ##########")
    for feat in ["slope_mag", "stretch", "er"]:
        print(f"\n  --- признак: {feat} ---")
        for sym in syms:
            d = load(sym, "4h"); sig = h5_signals(d); df, n = base_trades(d, sig)
            df = df.dropna(subset=[feat])
            med = df[feat].median()
            hi, lo = df[df[feat] >= med].ret, df[df[feat] < med].ret
            if len(hi) >= 4 and len(lo) >= 4:
                print(f"  {sym:8} высок n={len(hi):>3} avg{hi.mean():>6.2f}% win{(hi>0).mean()*100:>4.0f}%"
                      f"  |  низк n={len(lo):>3} avg{lo.mean():>6.2f}% win{(lo>0).mean()*100:>4.0f}%"
                      f"   Δ={hi.mean()-lo.mean():>+6.2f}")

if __name__ == "__main__":
    main()
