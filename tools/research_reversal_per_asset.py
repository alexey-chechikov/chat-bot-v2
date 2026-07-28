"""Пороги истощения ПО АКТИВАМ + глубина последующего движения.
Отвечает: 'коррекция или разворот' и 'какие цифры именно для этого актива'."""
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, "/Users/alexeychechikov/code/bot7")

import numpy as np
import pandas as pd

from research_reversal_anatomy import ZZ, load4h, rsi, zigzag

print("ПОРОГИ ИСТОЩЕНИЯ ПО АКТИВАМ (2 года, 4h)\n")
for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
    df = load4h(sym)
    c = df["close"].to_numpy(); v = df["volume"].to_numpy()
    h = df["high"].to_numpy(); l = df["low"].to_numpy()
    piv = zigzag(c)
    ema20 = pd.Series(c).ewm(span=20).mean().to_numpy()
    r = rsi(c)
    v_ma = pd.Series(v).rolling(30).mean().to_numpy()
    atr = pd.Series(np.maximum(h - l, np.abs(h - np.roll(c, 1)))).rolling(14).mean().to_numpy()

    legs, stats = [], []
    for k in range(len(piv) - 1):
        a, b = piv[k], piv[k + 1]
        if b - a < 3:
            continue
        move = (c[b] / c[a] - 1) * 100
        up = move > 0
        # что было В ТОЧКЕ разворота
        stats.append({
            "move": abs(move), "bars": b - a,
            "stretch": abs(c[b] - ema20[b]) / ema20[b] * 100,
            "stretch_atr": abs(c[b] - ema20[b]) / atr[b] if atr[b] else np.nan,
            "rsi": r[b] if up else 100 - r[b],
            "vol": v[b] / v_ma[b] if v_ma[b] else np.nan,
            "up": up,
        })
        # глубина ПОСЛЕДУЮЩЕГО отката относительно завершённой ноги
        if k + 2 < len(piv):
            nxt = piv[k + 2]
            back = abs(c[nxt] - c[b]) / abs(c[b] - c[a]) * 100
            legs.append(back)

    s = pd.DataFrame(stats)
    print(f"=== {sym} ===  ног (движений ≥{ZZ}%): {len(s)}")
    print(f"  типичная нога: {s['move'].median():.1f}% "
          f"(25-75%: {s['move'].quantile(.25):.1f}–{s['move'].quantile(.75):.1f}%), "
          f"{s['bars'].median():.0f} баров ≈ {s['bars'].median()*4/24:.1f} дней")
    print(f"  В ТОЧКЕ РАЗВОРОТА (медиана / 75-й перцентиль):")
    print(f"    отрыв от EMA20: {s['stretch'].median():.1f}% / "
          f"{s['stretch'].quantile(.75):.1f}%   "
          f"({s['stretch_atr'].median():.1f} / {s['stretch_atr'].quantile(.75):.1f} ATR)")
    print(f"    RSI по ходу:    {s['rsi'].median():.0f} / {s['rsi'].quantile(.75):.0f}")
    print(f"    объём к норме:  {s['vol'].median():.2f}x / {s['vol'].quantile(.75):.2f}x")
    if legs:
        L = pd.Series(legs)
        print(f"  ЧТО ДАЛЬШЕ (откат к размеру завершённой ноги):")
        print(f"    медиана {L.median():.0f}%  |  "
              f"<38% (мелкая коррекция): {(L < 38).mean()*100:.0f}%  |  "
              f"38–100% (глубокая): {((L >= 38) & (L < 100)).mean()*100:.0f}%  |  "
              f">100% (полный разворот): {(L >= 100).mean()*100:.0f}%")
    print()
