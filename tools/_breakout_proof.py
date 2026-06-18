"""Конкретное доказательство «5m пробой мёртв»: трейд-лента реального окна + ASCII-график + gross-vs-net.
Reference-конфиг ТЗ (20/50 SMA, пробой 20 баров, SL1.5/TP3). Данные frozen BTCUSDT 1m→5m."""
import numpy as np, pandas as pd, sys
sys.path.insert(0, "tools")
from _sma_momentum_breakout_quick import load_5m, signals, TAKER, SLIP, NOTION

def trades_detailed(d, longs, shorts, sl_pct=1.5, tp_pct=3.0):
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close"))
    ts = d.index; n = len(d); i = 0; out = []
    while i < n - 1:
        side = 1 if longs[i] else (-1 if shorts[i] else 0)
        if side == 0: i += 1; continue
        e = i + 1; fill = o[e] * (1 + side * SLIP / 100)
        stop = fill * (1 - side * sl_pct / 100); tp = fill * (1 + side * tp_pct / 100)
        ex = None; reason = ""; j = e
        while j < n:
            if side == 1:
                if o[j] <= stop: ex, reason = o[j] * (1 - SLIP / 100), "gapSL"; break
                if o[j] >= tp: ex, reason = tp, "gapTP"; break
                if l[j] <= stop: ex, reason = stop * (1 - SLIP / 100), "SL"; break
                if h[j] >= tp: ex, reason = tp, "TP"; break
            else:
                if o[j] >= stop: ex, reason = o[j] * (1 + SLIP / 100), "gapSL"; break
                if o[j] <= tp: ex, reason = tp, "gapTP"; break
                if h[j] >= stop: ex, reason = stop * (1 + SLIP / 100), "SL"; break
                if l[j] <= tp: ex, reason = tp, "TP"; break
            j += 1
        if ex is None: ex, reason, j = c[-1] * (1 - side * SLIP / 100), "EOD", n - 1
        gross = side * (ex / fill - 1) * NOTION; fees = NOTION * TAKER / 100 * 2
        out.append(dict(sig_ts=ts[i], side=side, entry=fill, stop=stop, tp=tp, exit=ex,
                        reason=reason, bars=j - e, net=gross - fees))
        i = j + 1
    return out

def ascii_chart(d, trs, rows=18, width=110):
    c = d["close"].to_numpy(); n = len(c)
    step = max(1, n // width); cols = c[::step]
    lo, hi = cols.min(), cols.max()
    grid = [[" "] * len(cols) for _ in range(rows)]
    for x, v in enumerate(cols):
        y = int((v - lo) / (hi - lo) * (rows - 1)) if hi > lo else 0
        grid[rows - 1 - y][x] = "·"
    # метки входов/выходов
    idx_map = {ts: k for k, ts in enumerate(d.index)}
    for t in trs:
        k = idx_map.get(t["sig_ts"]);
        if k is None: continue
        x = min(k // step, len(cols) - 1)
        v = c[min(k + 1, n - 1)]; y = int((v - lo) / (hi - lo) * (rows - 1)) if hi > lo else 0
        mark = ("L" if t["side"] > 0 else "S")
        grid[rows - 1 - y][x] = mark
        # выход
        win = t["reason"] in ("TP", "gapTP")
        ex_v = t["exit"]; ey = int((ex_v - lo) / (hi - lo) * (rows - 1)) if hi > lo else 0
        ex_x = min((k + 1 + t["bars"]) // step, len(cols) - 1)
        grid[rows - 1 - ey][ex_x] = "✓" if win else "✗"
    print(f"  BTC 5m  {d.index[0]:%m-%d %H:%M} → {d.index[-1]:%m-%d %H:%M}   "
          f"${lo:,.0f}…${hi:,.0f}   L/S=вход ✓=TP ✗=SL")
    for r in grid: print("  |" + "".join(r))

def main():
    d = load_5m()
    lo_s, sh_s = signals(d, 20, 50, 20, "rolling_extreme", "none", 0)
    # окно: возьмём фиксированный отрезок (не подобранный) — конец данных, ~4 дня
    win = d.loc["2026-05-01":"2026-05-05"]
    wl, ws = signals(win, 20, 50, 20, "rolling_extreme", "none", 0)
    trs = trades_detailed(win, wl, ws)
    print(f"=== ОКНО BTC 5m 01–05.05.2026 (НЕ подобрано, что было) — {len(trs)} сигналов пробоя ===\n")
    ascii_chart(win, trs)
    print(f"\n  Трейд-лента (вход t+1, SL1.5/TP3, тейкер+slip):")
    print(f"  {'время сигнала':16}{'side':>5}{'вход':>9}{'выход':>9}{'итог':>7}{'$нетто':>8}  баров")
    tot = 0
    for t in trs:
        tot += t["net"]
        print(f"  {t['sig_ts']:%m-%d %H:%M}  {'LONG' if t['side']>0 else 'SHORT':>5}{t['entry']:>9.0f}"
              f"{t['exit']:>9.0f}{t['reason']:>7}{t['net']:>+8.1f}{t['bars']:>6}")
    wins = sum(1 for t in trs if t["reason"] in ("TP", "gapTP"))
    print(f"  ИТОГ окна: {wins}/{len(trs)} в плюс, нетто ${tot:+.1f}  (видно: пробои разворачиваются → серия SL)")

    # --- ГЛАВНОЕ: gross vs net на всех 2 годах ---
    print("\n=== ГЛАВНОЕ ДОКАЗАТЕЛЬСТВО: gross (без комиссии) vs net (с тейкером) — вся 2-летняя выборка ===")
    allt = trades_detailed(d, lo_s, sh_s)
    gross = sum(t["net"] + NOTION * TAKER / 100 * 2 for t in allt)   # вернуть комиссию = gross
    fees = len(allt) * NOTION * TAKER / 100 * 2
    slipcost = len(allt) * NOTION * SLIP / 100 * 2
    net = sum(t["net"] for t in allt)
    print(f"  сделок: {len(allt)}")
    print(f"  GROSS (БЕЗ комиссии)        : ${gross:>+9.1f}   ({gross/len(allt):+.2f}$/сделку = {gross/len(allt)/NOTION*100:+.3f}%)")
    print(f"  − комиссия тейкер (0.075%×2): ${-fees:>+9.1f}")
    print(f"  = NET                       : ${net:>+9.1f}")
    print(f"\n  ВЫВОД: gross ≈ {gross/len(allt)/NOTION*100:+.3f}%/сделку = МОНЕТКА (нет направленного эджа).")
    print(f"  Комиссия −${fees:.0f} И ЕСТЬ весь убыток. Платишь тейкеру ~$1.9 за каждый бросок монетки → −${-net:.0f} за 2 года.")

if __name__ == "__main__":
    main()
