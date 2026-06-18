"""Постмортем SOL-бота 5693279219: харвест +119 (10-14.06) → слив −350 (ночь 14→15.06).
Вопрос оператора: как взять харвест, но не словить слив. Смотрю РЕАЛЬНУЮ цену SOL в окне (не гадаю по скрину)
и гоняю наш EXIT-FAST (Donchian-пробой + ATR-расширение + объём) — поймал бы он начало хода и где."""
import urllib.request, json, time
import numpy as np, pandas as pd

UA = {"User-Agent": "Mozilla/5.0"}
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))

def klines(sym, days=9):
    start = (pd.Timestamp("2026-06-09") ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows, st = [], start
    for _ in range(6):
        u = (f"https://www.bitmex.com/api/v1/trade/bucketed?binSize=1h&partial=false&symbol={sym}"
             f"&count=1000&reverse=false&startTime={st}")
        k = get(u)
        if not k: break
        rows += k
        if len(k) < 1000: break
        st = k[-1]["timestamp"]; time.sleep(0.5)
    df = pd.DataFrame(rows); df["ts"] = pd.to_datetime(df["timestamp"])
    return df.drop_duplicates("ts").set_index("ts")[["open", "high", "low", "close", "volume"]]

def main():
    d = klines("SOLUSDT")
    d = d[(d.index >= "2026-06-10") & (d.index <= "2026-06-16")]
    c = d["close"]
    # дневной разрез: где был сильный ход
    print("SOL 1ч — ход по дням (харвест-окно vs слив):")
    for day, g in d.groupby(d.index.date):
        rng = (g["high"].max() / g["low"].min() - 1) * 100
        chg = (g["close"].iloc[-1] / g["open"].iloc[0] - 1) * 100
        print(f"  {day}: open {g['open'].iloc[0]:.2f} → close {g['close'].iloc[-1]:.2f}  "
              f"Δдень {chg:>+5.1f}%  размах {rng:>4.1f}%")
    # EXIT-FAST: Donchian20-пробой + ATR>1.4× медианы(60) + объём>1.8×
    tr = pd.concat([d["high"] - d["low"], (d["high"] - c.shift()).abs(), (d["low"] - c.shift()).abs()], axis=1).max(1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_exp = atr / atr.rolling(60).median()
    volx = d["volume"] / d["volume"].rolling(60).median()
    up = d["high"].rolling(20).max().shift(1); dn = d["low"].rolling(20).min().shift(1)
    brk = (c > up) | (c < dn)
    fire = brk & (atr_exp > 1.4) & (volx > 1.8)
    print("\nEXIT-FAST срабатывания (пробой+ATR+объём) в окне:")
    ff = d[fire.fillna(False)]
    if len(ff):
        for ts, r in ff.iterrows():
            dirn = "ВНИЗ" if r["close"] < c.shift().loc[ts] else "ВВЕРХ"
            print(f"  {ts:%Y-%m-%d %H:%M}  цена {r['close']:.2f}  ATR×{atr_exp.loc[ts]:.1f} об×{volx.loc[ts]:.1f}  пробой {dirn}")
    else:
        print("  (нет — ход был не explosive)")
    # ночь 14→15.06: что произошло
    night = d[(d.index >= "2026-06-14 18:00") & (d.index <= "2026-06-15 12:00")]
    if len(night):
        lo, hi = night["low"].min(), night["high"].max()
        print(f"\nНочь 14→15.06 18:00-12:00: low {lo:.2f} high {hi:.2f}  ход {(hi/lo-1)*100:.1f}%  "
              f"(open {night['open'].iloc[0]:.2f} → close {night['close'].iloc[-1]:.2f})")

if __name__ == "__main__":
    main()
