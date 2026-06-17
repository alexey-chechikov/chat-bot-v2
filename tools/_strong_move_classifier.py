"""Валидация для Мака (HANDOFF_STRONG_MOVE_HANDLER): разделяет ли trend-confirmation
ОТСКОК (грид-нога восстановится) от ТРЕНДА (нога сольёт) — в момент, когда нога бажит на сильном ходе?
n=4 живых кейса слабы → моделирую сотни «бажащих» событий на 2г BTC 4ч.

Событие = ход |M баров| ≥ D% (это и бажит ногу, что фейдит ход). Метка ВПЕРЁД (K баров):
  BLEED (тренд) = ход ПРОДОЛЖился ≥ cont; RECOVER (отскок) = ход РАЗВЕРНУЛся ≥ rev. (середина = ambiguous, дроп.)
В МОМЕНТ события (каузально) считаем кандидат-подтверждения Мака и меряем bleed-rate с/без каждого.
Подтверждение «работает», если P(bleed|подтв) >> P(bleed|нет). Данные: frozen 2y BTC 4ч."""
from pathlib import Path
import numpy as np, pandas as pd

PX = Path(__file__).resolve().parents[1] / "backtests" / "frozen" / "BTCUSDT_1h_2y.csv"
M, D, K, CONT, REV = 6, 2.0, 12, 1.5, 1.5     # ход 1д≥2%, вперёд 2д, тренд/отскок ±1.5%

def load_4h():
    df = pd.read_csv(PX); df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return (df.set_index("ts").resample("4h").agg({"open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"}).dropna())

def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def main():
    df = load_4h(); c = df["close"].to_numpy(); n = len(c)
    hl2 = ((df["high"] + df["low"]) / 2)
    e14 = hl2.ewm(span=14, adjust=False).mean().to_numpy()
    e77 = hl2.ewm(span=77, adjust=False).mean().to_numpy()
    e200 = hl2.ewm(span=200, adjust=False).mean().to_numpy()
    a = atr(df); atrp = (a / df["close"] * 100).to_numpy()
    atr_exp = (a / a.rolling(60).median()).to_numpy()
    vol_spike = (df["volume"] / df["volume"].rolling(60).median()).to_numpy()
    don_hi = df["high"].rolling(20).max().shift(1).to_numpy()
    don_lo = df["low"].rolling(20).min().shift(1).to_numpy()

    rows = []
    for i in range(200, n - K):
        move = (c[i] / c[i - M] - 1) * 100
        if abs(move) < D:
            continue
        d = 1 if move > 0 else -1                       # сторона хода (против неё бажит нога)
        fwd = d * (c[i + K] / c[i] - 1) * 100           # +вперёд по ходу = продолжение
        if fwd >= CONT:   label = 1                     # BLEED (тренд)
        elif fwd <= -REV: label = 0                     # RECOVER (отскок)
        else:             continue                      # ambiguous
        # каузальные подтверждения Мака
        exitfast = ((c[i] > don_hi[i]) if d > 0 else (c[i] < don_lo[i])) and atr_exp[i] > 1.4 and vol_spike[i] > 1.8
        h5_agree = ((e14[i] > e77[i] > e200[i]) if d > 0 else (e14[i] < e77[i] < e200[i]))
        ema200_side = (c[i] > e200[i]) if d > 0 else (c[i] < e200[i])
        vol_exp = atr_exp[i] > 1.2
        move_atr = abs(move) / atrp[i] if atrp[i] > 0 else 0     # ход в ATR
        rows.append(dict(label=label, exitfast=bool(exitfast), h5=bool(h5_agree),
                         ema200=bool(ema200_side), volexp=bool(vol_exp), move_atr=move_atr))
    t = pd.DataFrame(rows)
    base = t["label"].mean()
    print(f"Событий: {len(t)}  (BLEED/тренд {t['label'].sum()}, RECOVER/отскок {len(t)-t['label'].sum()})")
    print(f"БАЗА P(bleed) = {base:.0%}  (монетка ~50% = тренд заранее неотличим)\n")
    print(f"{'подтверждение':16}{'ДА: n':>7}{'P(bleed)':>10}{'НЕТ: n':>9}{'P(bleed)':>10}{'разделение':>12}")
    for f in ["exitfast", "h5", "ema200", "volexp"]:
        a1, b1 = t[t[f]], t[~t[f]]
        sep = a1["label"].mean() - b1["label"].mean()
        print(f"{f:16}{len(a1):>7}{a1['label'].mean():>9.0%}{len(b1):>9}{b1['label'].mean():>9.0%}{sep:>+11.0%}")
    # сила хода в ATR — квартили
    print("\nХод в ATR (сила движения) — квартильный bleed-rate:")
    t["q"] = pd.qcut(t["move_atr"], 4, labels=["Q1слаб", "Q2", "Q3", "Q4сильн"])
    for q, g in t.groupby("q", observed=True):
        print(f"  {q}: n={len(g):>4}  P(bleed) {g['label'].mean():>4.0%}  (ход {g['move_atr'].mean():.1f} ATR)")
    # комбо: счёт подтверждений
    t["score"] = t[["exitfast", "h5", "ema200", "volexp"]].sum(axis=1)
    print("\nСчёт подтверждений (0-4) → bleed-rate (монотонность = сигнал реален):")
    for s, g in t.groupby("score"):
        print(f"  score {s}: n={len(g):>4}  P(bleed) {g['label'].mean():>4.0%}")

if __name__ == "__main__":
    main()
