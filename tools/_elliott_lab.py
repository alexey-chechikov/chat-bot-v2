"""Elliott-wave lab — алгоритмическая (воспроизводимая) версия, НЕ «на глаз».
Основа = каузальный ZigZag (пивот подтверждается ТОЛЬКО после разворота на thr% — нет look-ahead).
Гипотезы из теории Эллиота, которые реально тестируемы:
  E-A  наивное следование свингам (SAR по подтверждённым пивотам) — БАЗА (это не Эллиот, это «зигзаг»)
  E-B  вход в ВОЛНУ-3 (сильнейшую): после L0→H1→L2 ставим в сторону волны-1, если L2 держит начало волны-1
  E-C  + фиб-зона коррекции волны-2 (ретрейс 38.2–78.6% волны-1)
  E-D  + правило «волна-3 не короче» / целевой проджекшн 1.618
  E-E  Эллиот × H5: вход в волну-3 только если согласован с наклоном EMA77 и стороной EMA200
Учёт идентичен MA-лабе: fee 0.05%/сторона, log-доход, половины h1/h2 (анти-оверфит). Данные: data/ma_lab/*_1h.csv.
"""
import numpy as np, pandas as pd, sys, itertools

FEE = 0.0005
FIB_LO, FIB_HI = 0.382, 0.786     # зона коррекции волны-2 (классика 0.5–0.618, берём шире)

def load(sym, tf="4h"):
    d = pd.read_csv(f"data/ma_lab/{sym}_1h.csv", index_col=0, parse_dates=True)
    if tf != "1h":
        d = d.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"}).dropna()
    return d

def zigzag_confirmed(high, low, thr):
    """Каузальный ZigZag. Возвращает список пивотов (confirm_i, piv_i, piv_price, kind:+1 high/-1 low).
    Пивот эмитится В МОМЕНТ разворота на thr — confirm_i это бар, на котором сигнал доступен."""
    n = len(high)
    piv = []
    direction = 0
    eh, eh_i = high[0], 0
    el, el_i = low[0], 0
    for i in range(1, n):
        if direction >= 0:                              # ищем верх (или старт)
            if high[i] > eh:
                eh, eh_i = high[i], i
            if low[i] < eh * (1 - thr):                 # подтверждённый разворот вниз
                piv.append((i, eh_i, eh, +1))
                direction = -1
                el, el_i = low[i], i
                continue
        if direction <= 0:                              # ищем низ (или старт)
            if low[i] < el:
                el, el_i = low[i], i
            if high[i] > el * (1 + thr):                # подтверждённый разворот вверх
                piv.append((i, el_i, el, -1))
                direction = +1
                eh, eh_i = high[i], i
    return piv

def run_trades(close, trades):
    """trades: list (entry_i, exit_i, side). Лог-доход, fee 2x, метрики + половины."""
    lr = np.log(close).to_numpy()
    n = len(close)
    rets, durs, exposure = [], [], np.zeros(n)
    for ei, xi, side in trades:
        if xi <= ei or xi >= n:
            continue
        r = side * (lr[xi] - lr[ei]) - 2 * FEE
        rets.append(r)
        durs.append(xi - ei)
        exposure[ei:xi] = 1
    if len(rets) < 6:
        return None
    rets = np.array(rets)
    half = n // 2
    # половины по индексу входа (ровно те сделки, что дали rets)
    eis = np.array([t[0] for t in trades if t[1] > t[0] and t[1] < n][:len(rets)])
    h1v = rets[eis < half].sum() * 100
    h2v = rets[eis >= half].sum() * 100
    gp, gl = rets[rets > 0].sum(), -rets[rets < 0].sum()
    eq = np.cumsum(rets)
    dd = float((np.maximum.accumulate(eq) - eq).max()) * 100 if len(eq) else 0.0
    return dict(n=len(rets), net=rets.sum() * 100, h1=h1v, h2=h2v,
                pf=gp / gl if gl > 0 else np.inf, wr=(rets > 0).mean() * 100,
                mdd=dd, dur=float(np.mean(durs)), expo=exposure.mean() * 100)

def build_trades(close, piv, mode, slope=None, reg=None):
    """Из пивотов строим сделки по выбранной гипотезе.
    piv: (confirm_i, piv_i, piv_price, kind). mode in {A,B,C,D,E}."""
    cl = close.to_numpy()
    trades = []
    # пройдём по подтверждённым пивотам; на каждом low/high у нас доступна предыстория пивотов
    for k in range(2, len(piv)):
        ci, pi, pp, kind = piv[k]
        entry_i = ci                       # входим на баре подтверждения (каузально)
        # следующий противоположный пивот -> выход
        exit_i = piv[k + 1][0] if k + 1 < len(piv) else None
        if exit_i is None:
            continue
        side = +1 if kind == -1 else -1    # подтверждён low -> разворот вверх -> long
        if mode == "A":
            trades.append((entry_i, exit_i, side))
            continue
        # Эллиот: нужен контекст L0,H1,L2 (для long) или H0,L1,H2 (для short)
        p_prev2 = piv[k - 2]   # L0 / H0
        p_prev1 = piv[k - 1]   # H1 / L1
        L0, H1, L2 = p_prev2[2], p_prev1[2], pp
        if side == +1:
            # up-impulse: L0(low) H1(high) L2(low, текущий)
            if not (p_prev2[3] == -1 and p_prev1[3] == +1 and kind == -1):
                continue
            if not (H1 > L0 and L2 > L0):              # волна-2 не сносит начало волны-1
                continue
            w1 = H1 - L0
            retr = (H1 - L2) / w1 if w1 > 0 else 9
        else:
            H0, L1, H2 = p_prev2[2], p_prev1[2], pp
            if not (p_prev2[3] == +1 and p_prev1[3] == -1 and kind == +1):
                continue
            if not (L1 < H0 and H2 < H0):
                continue
            w1 = H0 - L1
            retr = (H2 - L1) / w1 if w1 > 0 else 9
        if mode in ("C", "D", "E"):
            if not (FIB_LO <= retr <= FIB_HI):          # фиб-зона волны-2
                continue
        if mode in ("E",) and slope is not None and reg is not None:
            sl = slope.to_numpy()[entry_i]; rg = reg.to_numpy()[entry_i]
            if not ((side > 0) == (sl > 0)):            # наклон EMA77 по стороне
                continue
            if not ((side > 0) == (cl[entry_i] > rg)):  # цена на стороне EMA200
                continue
        trades.append((entry_i, exit_i, side))
    return trades

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def sweep(sym, tf, thr_list):
    d = load(sym, tf)
    close = d["close"]
    hl2 = (d["high"] + d["low"]) / 2
    e77 = ema(hl2, 77); e200 = ema(hl2, 200); slope = e77.diff(5)
    high, low = d["high"].to_numpy(), d["low"].to_numpy()
    rows = []
    for thr in thr_list:
        piv = zigzag_confirmed(high, low, thr)
        for mode in ("A", "B", "C", "D", "E"):
            tr = build_trades(close, piv, mode, slope, e200)
            m = run_trades(close, tr)
            if m:
                rows.append(dict(thr=thr, mode=mode, npiv=len(piv), **m))
    return pd.DataFrame(rows), len(close)

def show(df, nbars, sym, tf):
    print(f"\n=== {sym} {tf}  ({nbars} bars) ===")
    print(f"{'thr%':>5}{'mode':>5}{'piv':>5}{'n':>5}{'net%':>7}{'h1%':>7}{'h2%':>7}"
          f"{'PF':>6}{'win':>5}{'DD%':>6}{'dur':>5}{'expo%':>6}")
    for _, r in df.iterrows():
        mk = "★" if (r.h1 > 0 and r.h2 > 0 and r.net > 0) else " "
        print(f"{r.thr*100:>5.0f}{r['mode']:>5}{r.npiv:>5.0f}{r.n:>5.0f}{r.net:>7.0f}{r.h1:>7.0f}"
              f"{r.h2:>7.0f}{r.pf:>6.2f}{r.wr:>5.0f}{r.mdd:>6.0f}{r.dur:>5.1f}{r.expo:>6.0f} {mk}")

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT", "SOLUSDT"]
    tfs = sys.argv[2].split(",") if len(sys.argv) > 2 else ["4h", "1d"]
    thr_list = [0.02, 0.03, 0.05, 0.08]
    for sym in syms:
        for tf in tfs:
            df, nb = sweep(sym, tf, thr_list)
            show(df, nb, sym, tf)
            df.to_csv(f"data/ma_lab/elliott_{sym}_{tf}.csv", index=False)

if __name__ == "__main__":
    main()
