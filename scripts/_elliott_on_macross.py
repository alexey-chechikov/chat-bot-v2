"""Объективный скелет Эллиотта поверх MA-cross H5 — добавляет ли что-то? (ТЗ 2026-06-13)

Тестируемые части EW (без субъективного «счёта»):
  - ZigZag-свинги (пивоты по порогу %);
  - структура: импульс (свинги монотонно трендят: HH+HL / LH+LL) vs коррекция (перекрытие);
  - зрелость тренда = сколько свингов подряд в одну сторону (прокси номера волны 1-3-5);
  - глубина отката к последнему свингу + Фибо-зона (0.382/0.5/0.618).
Метрика: делим MA-cross сигналы (база EMA14/77 hl2) по EW-фиче, смотрим forward 24ч +
held-to-reverse. Если фича РАЗДЕЛЯЕТ победителей/проигравших — кандидат. n мал → осторожно.
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEE = 0.10


def load(tf):
    parts = [pd.read_csv(ROOT / "state" / f"pattern_memory_BTCUSDT_1h_{y}.csv",
                         usecols=["open_time", "open", "high", "low", "close"]) for y in (2024, 2025, 2026)]
    df = pd.concat(parts)
    df["open_time"] = pd.to_datetime(df["open_time"])
    df = df.set_index("open_time").sort_index()
    rule = {"1h": "1h", "4h": "4h", "1d": "1D"}[tf]
    o = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return o.reset_index()


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def zigzag(close, pct):
    """Пивоты ZigZag: список (idx, price, type 'H'/'L'). Разворот на pct% от экстремума.
    Running hi/lo: при trend=0 отслеживаем оба, первый пробой порога задаёт направление."""
    piv = []
    hi_i = lo_i = 0
    hi = lo = close[0]
    trend = 0  # +1 вверх, -1 вниз
    for i in range(1, len(close)):
        c = close[i]
        if c > hi:
            hi_i, hi = i, c
        if c < lo:
            lo_i, lo = i, c
        if trend >= 0 and c <= hi * (1 - pct / 100):
            piv.append((hi_i, hi, "H")); trend = -1; hi_i = lo_i = i; hi = lo = c
        elif trend <= 0 and c >= lo * (1 + pct / 100):
            piv.append((lo_i, lo, "L")); trend = 1; hi_i = lo_i = i; hi = lo = c
    return piv


def cross_signals(df):
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
    close = df["close"].to_numpy(float)
    e14, e77 = ema(hl2, 14), ema(hl2, 77)
    diff = e14 - e77
    sign = np.sign(diff)
    cx = [i for i in range(1, len(close)) if not np.isnan(diff[i]) and sign[i] != sign[i - 1] and sign[i] != 0]
    return close, cx


def ew_features(close, piv, i):
    """EW-фичи на баре i: (n_legs_same_dir, retrace_pct, is_impulse)."""
    past = [p for p in piv if p[0] < i]
    if len(past) < 4:
        return None
    # последние 4 пивота
    p4 = past[-4:]
    prices = [p[1] for p in p4]
    types = [p[2] for p in p4]
    # импульс вверх: H растут и L растут (HH+HL); вниз: зеркально; иначе коррекция
    hs = [p[1] for p in p4 if p[2] == "H"]
    ls = [p[1] for p in p4 if p[2] == "L"]
    is_impulse = False
    if len(hs) >= 2 and len(ls) >= 2:
        up = hs[-1] > hs[-2] and ls[-1] > ls[-2]
        dn = hs[-1] < hs[-2] and ls[-1] < ls[-2]
        is_impulse = up or dn
    # зрелость: сколько последних свингов держат одно направление
    dirs = [1 if prices[k] > prices[k - 1] else -1 for k in range(1, len(prices))]
    n_legs = 1
    for k in range(len(dirs) - 1, 0, -1):
        if dirs[k] == dirs[k - 1]:
            n_legs += 1
        else:
            break
    # глубина отката: текущая цена vs последний свинг-размах
    last_p, prev_p = past[-1][1], past[-2][1]
    rng = abs(last_p - prev_p)
    retrace = abs(close[i] - last_p) / rng * 100 if rng > 0 else 0
    return n_legs, round(retrace, 1), is_impulse


def held_to_reverse(close, cx):
    out = {}
    for k in range(len(cx) - 1):
        i, nxt = cx[k], cx[k + 1]
        d = 1 if close[i] > close[i - 1] else None
        # направление по diff знаку проще: пересчитать
    return out


def main():
    for tf, zz in (("1h", 2.0), ("4h", 3.5), ("1d", 6.0)):
        df = load(tf)
        if len(df) < 250:
            continue
        close, cx = cross_signals(df)
        piv = zigzag(close, zz)
        hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
        diff = ema(hl2, 14) - ema(hl2, 77)
        rows = []
        for k in range(len(cx) - 1):
            i, nxt = cx[k], cx[k + 1]
            d = 1 if diff[i] > 0 else -1
            f24 = i + (6 if tf == "4h" else (24 if tf == "1h" else 1))
            if f24 >= len(close):
                continue
            ret24 = d * (close[f24] / close[i] - 1) * 100
            retX = d * (close[nxt] / close[i] - 1) * 100 - FEE   # held-to-reverse
            ew = ew_features(close, piv, i)
            if ew is None:
                continue
            n_legs, retr, imp = ew
            rows.append((d, ret24, retX, n_legs, retr, imp))
        if len(rows) < 20:
            print(f"\n=== {tf}: сигналов с EW-контекстом {len(rows)} — мало, пропуск")
            continue
        t = pd.DataFrame(rows, columns=["dir", "r24", "rX", "n_legs", "retr", "imp"])
        print(f"\n=== {tf} (ZigZag {zz}%) — MA-cross сигналов с EW-контекстом: {len(t)} ===")
        base24, baseX = t["r24"].mean(), t["rX"].mean()
        print(f"  БАЗА: forward24 {base24:+.2f}%  held-to-reverse {baseX:+.2f}% (win {100*(t.rX>0).mean():.0f}%)")

        # фича 1: импульс vs коррекция
        for lbl, mask in [("импульс (EW)", t["imp"]), ("коррекция", ~t["imp"])]:
            s = t[mask]
            if len(s) >= 8:
                print(f"  [{lbl:14}] n={len(s):3} forward24 {s.r24.mean():+.2f}%  "
                      f"heldX {s.rX.mean():+.2f}% win {100*(s.rX>0).mean():.0f}%")
        # фича 2: зрелость тренда (волна 1-2 vs 3+ — поздняя)
        for lbl, mask in [("ранние ≤2 legs", t["n_legs"] <= 2), ("поздние ≥3 legs", t["n_legs"] >= 3)]:
            s = t[mask]
            if len(s) >= 8:
                print(f"  [{lbl:14}] n={len(s):3} forward24 {s.r24.mean():+.2f}%  "
                      f"heldX {s.rX.mean():+.2f}% win {100*(s.rX>0).mean():.0f}%")
        # фича 3: глубокий откат к Фибо (0.5-0.7) vs мелкий/растянутый
        for lbl, mask in [("откат 38-62%", (t.retr >= 38) & (t.retr <= 62)),
                          ("вне фибо-зоны", (t.retr < 38) | (t.retr > 62))]:
            s = t[mask]
            if len(s) >= 8:
                print(f"  [{lbl:14}] n={len(s):3} forward24 {s.r24.mean():+.2f}%  "
                      f"heldX {s.rX.mean():+.2f}% win {100*(s.rX>0).mean():.0f}%")


if __name__ == "__main__":
    main()
