"""Тест стратегии 'Market Structure BOS' (видео): пробой свинг-структуры по HTF-тренду + ATR-цели
×4/×8/×12, стоп ATR×2, частичные выходы 33/33/34 с трейлом SL в безубыток после TP1. Реальная комиссия.
Ядро = пробой свинг-хая/лоу (BOS) в сторону тренда 1ч. Данные frozen BTCUSDT 5m, look-ahead-free."""
import numpy as np, pandas as pd, sys
sys.path.insert(0, "tools")
from _sma_momentum_breakout_quick import load_5m, NOTION, SLIP

SWING = 12          # свинг-хай/лоу = макс/мин последних N баров (структура)
ATR_N = 14
SL_X, TP1_X, TP2_X, TP3_X = 2.0, 4.0, 8.0, 12.0

def atr(d, n=ATR_N):
    h, l, c = d["high"], d["low"], d["close"]; pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def main():
    d = load_5m()
    # HTF тренд (1ч EMA50) — golden rule: лонги только в бычьем HTF, шорты в медвежьем
    c1h = d["close"].resample("1h").last()
    ema1h = c1h.ewm(span=50, adjust=False).mean()
    htf_up = (c1h > ema1h).reindex(d.index, method="ffill").shift(1).fillna(False).to_numpy()
    a = atr(d).to_numpy()
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close"))
    sw_hi = pd.Series(h).rolling(SWING).max().shift(1).to_numpy()   # свинг-хай (структура до текущего)
    sw_lo = pd.Series(l).rolling(SWING).min().shift(1).to_numpy()
    n = len(d); i = SWING + 60; trades = []
    while i < n - 1:
        long_bos = c[i] > sw_hi[i] and c[i] > o[i] and htf_up[i]    # BOS вверх + бычья свеча + HTF бычий
        short_bos = c[i] < sw_lo[i] and c[i] < o[i] and not htf_up[i]
        side = 1 if long_bos else (-1 if short_bos else 0)
        if side == 0 or np.isnan(a[i]) or a[i] <= 0:
            i += 1; continue
        e = i + 1; fill = o[e] * (1 + side * SLIP / 100)
        A = a[i]
        sl = fill - side * SL_X * A
        tps = [fill + side * x * A for x in (TP1_X, TP2_X, TP3_X)]
        rem = 1.0; pnl = 0.0; fills = 1; hit = [False, False, False]; cur_sl = sl
        j = e
        while j < n:
            # выход по стопу (по low/high)
            stopped = (l[j] <= cur_sl) if side == 1 else (h[j] >= cur_sl)
            if stopped:
                exitp = cur_sl * (1 - side * SLIP / 100)
                pnl += rem * side * (exitp / fill - 1); fills += 1; rem = 0; break
            # частичные тейки
            for k, tp in enumerate(tps):
                if not hit[k] and ((h[j] >= tp) if side == 1 else (l[j] <= tp)):
                    part = 0.33 if k < 2 else rem
                    pnl += part * side * (tp / fill - 1); rem -= part; fills += 1; hit[k] = True
                    if k == 0:
                        cur_sl = fill          # трейл SL в безубыток после TP1
            if rem <= 1e-9:
                break
            j += 1
        if rem > 1e-9:                         # конец данных
            pnl += rem * side * (c[min(j, n - 1)] / fill - 1)
        trades.append(dict(side=side, pnl=pnl * NOTION, fills=fills, tp1=hit[0], tp3=hit[2]))
        i = j + 1
    df = pd.DataFrame(trades); N = len(df)
    if N == 0:
        print("нет сделок"); return
    gross = df["pnl"].sum()
    tot_fills = df["fills"].sum()
    print(f"Market Structure BOS · 5m BTC · {N} сделок (свинг {SWING}, SL ATR×2, TP ×4/8/12, частичные 33/33/34)")
    print(f"  TP1 достигнут: {df['tp1'].mean()*100:.0f}%  ·  TP3 (×12): {df['tp3'].mean()*100:.0f}%  ·  средн. филлов/сделку: {tot_fills/N:.1f}")
    print(f"  GROSS (после slip, БЕЗ комиссии): ${gross:+.0f}  ({gross/N:+.2f}$/сделку = {gross/N/NOTION*100:+.3f}%)\n")
    print(f"  {'комиссия/сторона':>22}{'филлов':>9}{'комиссия':>11}{'NET':>10}")
    for sf, tag in [(0.075, "ТЗ-опт"), (0.32, "ТВОЯ ребейт"), (0.35, "ТВОЯ без")]:
        fees = tot_fills * NOTION * sf / 100      # комиссия на КАЖДЫЙ филл (вход + частичные выходы)
        print(f"  {tag+f' {sf}%':>22}{tot_fills:>9}{-fees:>10.0f}${gross-fees:>+9.0f}")
    print(f"\n  ATR×2 стоп ≈ {SL_X*np.nanmedian(a)/np.nanmedian(c)*100:.2f}% риска · твоя комиссия 0.64%/круг × {tot_fills/N:.1f} филла.")

if __name__ == "__main__":
    main()
