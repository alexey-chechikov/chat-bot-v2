"""Тест единственного специфицируемого куска видео-индикатора: ORB (opening-range breakout) + ретест.
Остальное (supply/demand, confirmation-сигналы) — правил нет, автор сам признаёт «не работает».
Крипта 24/7 не имеет «открытия» → якорю на US-открытие 13:30 UTC (ликвидное событие, контекст видео).
ORB = первые 30 мин (6×5m). Пробой close за hi/lo → ждём ретест уровня → вход на продолжении. SL/TP 2:1.
Реальная комиссия оператора. Данные frozen BTCUSDT 1m→5m."""
import numpy as np, pandas as pd, sys
sys.path.insert(0, "tools")
from _sma_momentum_breakout_quick import load_5m, NOTION, SLIP

ANCHOR_H, ANCHOR_M = 13, 30     # US-открытие UTC
ORB_BARS = 6                    # 30 мин
SL_PCT, TP_PCT = 1.5, 3.0
TOL = 0.0005                    # зона ретеста уровня

def main():
    d = load_5m()
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close"))
    idx = d.index
    day = idx.date
    # ORB hi/lo по дню (первые 6 баров от якоря)
    trades = []
    for dd in sorted(set(day)):
        mask = (day == dd)
        sess = np.where(mask & (idx.hour == ANCHOR_H) & (idx.minute == ANCHOR_M))[0]
        if len(sess) == 0:
            continue
        s0 = sess[0]
        if s0 + ORB_BARS >= len(d):
            continue
        orb_hi = h[s0:s0 + ORB_BARS].max(); orb_lo = l[s0:s0 + ORB_BARS].min()
        end = np.where(mask)[0].max()
        # ищем пробой → ретест → вход, до конца дня
        i = s0 + ORB_BARS
        state = 0   # 0 ждём пробой, 1 пробой-вверх ждём ретест, -1 пробой-вниз
        while i <= end:
            if state == 0:
                if c[i] > orb_hi: state = 1
                elif c[i] < orb_lo: state = -1
            elif state == 1:                         # пробой вверх был → ждём касание уровня и закрытие выше
                if l[i] <= orb_hi * (1 + TOL) and c[i] > orb_hi and i < end:
                    side, lvl = 1, orb_hi; break
            elif state == -1:
                if h[i] >= orb_lo * (1 - TOL) and c[i] < orb_lo and i < end:
                    side, lvl = -1, orb_lo; break
            i += 1
        else:
            continue
        e = i + 1
        fill = o[e] * (1 + side * SLIP / 100)
        stop = fill * (1 - side * SL_PCT / 100); tp = fill * (1 + side * TP_PCT / 100)
        ex = None; reason = ""; j = e
        while j < len(d) and idx[j].date() <= dd + pd.Timedelta(days=1):
            if side == 1:
                if l[j] <= stop: ex, reason = stop * (1 - SLIP / 100), "SL"; break
                if h[j] >= tp: ex, reason = tp, "TP"; break
            else:
                if h[j] >= stop: ex, reason = stop * (1 + SLIP / 100), "SL"; break
                if l[j] <= tp: ex, reason = tp, "TP"; break
            j += 1
        if ex is None:
            ex, reason = c[min(j, len(d) - 1)] * (1 - side * SLIP / 100), "EOD"
        gross = side * (ex / fill - 1) * NOTION
        trades.append(dict(side=side, reason=reason, gross=gross))
    n = len(trades)
    if n == 0:
        print("нет сделок"); return
    from collections import Counter
    rc = Counter(t["reason"] for t in trades)
    tp = rc["TP"]; sl = rc["SL"]
    gross = sum(t["gross"] for t in trades)
    print(f"ORB break-retest на BTC 5m (якорь 13:30 UTC), {len(set(day))} дней:")
    print(f"  сделок: {n}  ·  TP(+3%): {tp} ({tp/n*100:.0f}%)  ·  SL(−1.5%): {sl} ({sl/n*100:.0f}%)  ·  EOD: {rc['EOD']}")
    print(f"  win-rate {tp/n*100:.1f}%  vs  безубыток 2:1 = 33.3%")
    print(f"  GROSS (после slip, БЕЗ комиссии): ${gross:>+8.0f}  ({gross/n/NOTION*100:+.3f}%/сделку)\n")
    print(f"  {'комиссия/сторона':>22}{'комиссия':>12}{'NET':>10}")
    for sf, tag in [(0.075, "ТЗ-опт"), (0.32, "ТВОЯ ребейт"), (0.35, "ТВОЯ без")]:
        fees = n * NOTION * sf / 100 * 2
        print(f"  {tag+f' {sf}%':>22}{-fees:>11.0f}${gross-fees:>+9.0f}")

if __name__ == "__main__":
    main()
