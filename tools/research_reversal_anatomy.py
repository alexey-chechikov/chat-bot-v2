"""АНАТОМИЯ ЗАВЕРШЕНИЯ ДВИЖЕНИЯ — исследование на 2 годах.

Метод честный:
1) ZigZag выделяет реальные ноги движения (порог 5%);
2) в КАЖДОМ баре внутри ноги считаю признаки;
3) размечаю: развернулось ли в ближайшие 12 баров (2 суток на 4h);
4) сравниваю частоту разворота ПРИ признаке с БАЗОВОЙ частотой.
   Признак ценен, только если поднимает вероятность заметно выше базы.
"""
import sys

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")

import numpy as np
import pandas as pd

ROOT = "/Users/alexeychechikov/code/bot7/"
FWD = 12          # горизонт «скоро развернётся», баров 4h = 2 суток
ZZ = 5.0          # порог ноги, %


def load4h(sym):
    d = pd.read_csv(ROOT + f"backtests/frozen/{sym}_1m_2y.csv")
    d["dt"] = pd.to_datetime(d["ts"], unit="ms" if d["ts"].iloc[-1] > 1e12 else "s",
                             utc=True)
    d = d.set_index("dt").sort_index()
    return d.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna()


def zigzag(c, pct=ZZ):
    """Точки разворота: смена направления после отката >= pct% от экстремума."""
    piv = [0]
    hi_i = lo_i = 0
    direction = 0          # 0 = ещё не определено, 1 = вверх, −1 = вниз
    for i in range(1, len(c)):
        if c[i] > c[hi_i]:
            hi_i = i
        if c[i] < c[lo_i]:
            lo_i = i
        if direction >= 0 and (c[hi_i] - c[i]) / c[hi_i] * 100 >= pct:
            # был рост → откат на pct% → пик hi_i это разворот
            if hi_i != piv[-1]:
                piv.append(hi_i)
            direction = -1
            lo_i = i
        elif direction <= 0 and (c[i] - c[lo_i]) / c[lo_i] * 100 >= pct:
            if lo_i != piv[-1]:
                piv.append(lo_i)
            direction = 1
            hi_i = i
    return sorted(set(piv))


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1/n, adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


def study(sym):
    df = load4h(sym)
    c = df["close"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); o = df["open"].to_numpy()
    v = df["volume"].to_numpy()
    n = len(c)
    piv = zigzag(c)
    if len(piv) < 6:
        return None, None

    # для каждого бара: индекс конца текущей ноги и её старт
    leg_end = np.full(n, -1); leg_start = np.full(n, -1); leg_dir = np.zeros(n)
    for k in range(len(piv) - 1):
        a, b = piv[k], piv[k + 1]
        leg_start[a:b] = a; leg_end[a:b] = b
        leg_dir[a:b] = 1 if c[b] > c[a] else -1

    r = rsi(c)
    v_ma = pd.Series(v).rolling(30).mean().to_numpy()
    ema20 = pd.Series(c).ewm(span=20).mean().to_numpy()
    atr = pd.Series(np.maximum(h - l, np.abs(h - np.roll(c, 1)))).rolling(14).mean().to_numpy()

    rows = []
    for i in range(40, n - FWD):
        if leg_end[i] < 0 or leg_start[i] < 0:
            continue
        d = leg_dir[i]
        if d == 0:
            continue
        start = leg_start[i]
        move = abs(c[i] / c[start] - 1) * 100          # сколько прошло, %
        bars = i - start
        if move < 2 or bars < 3:
            continue
        rng = max(h[i] - l[i], 1e-9)
        # признаки
        f = {
            "move": move,
            "bars": bars,
            "vol_ratio": v[i] / v_ma[i] if v_ma[i] else 1,      # объём vs норма
            "rsi": r[i] if d > 0 else 100 - r[i],               # «перегрев» по ходу
            "stretch": abs(c[i] - ema20[i]) / ema20[i] * 100,   # отрыв от EMA20
            "atr_exp": atr[i] / np.nanmean(atr[i-20:i]) if i > 20 else 1,
            # хвост ПРОТИВ движения (отвержение)
            "rej_wick": ((h[i] - max(c[i], o[i])) / rng if d > 0
                         else (min(c[i], o[i]) - l[i]) / rng),
            # дивергенция: новый экстремум цены, RSI слабее
            "diver": 0.0,
        }
        w = 12
        if i > w:
            if d > 0 and h[i] >= np.max(h[i-w:i]) and r[i] < np.max(r[i-w:i]) - 3:
                f["diver"] = 1.0
            if d < 0 and l[i] <= np.min(l[i-w:i]) and (100-r[i]) < np.max(100-r[i-w:i]) - 3:
                f["diver"] = 1.0
        # ЦЕЛЬ: нога закончится в ближайшие FWD баров?
        f["reversal_soon"] = 1.0 if (leg_end[i] - i) <= FWD else 0.0
        rows.append(f)
    return pd.DataFrame(rows), df


ALL = []
for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
    t, df = study(sym)
    if t is None:
        continue
    t["sym"] = sym
    ALL.append(t)
    base = t["reversal_soon"].mean() * 100
    print(f"=== {sym} ===  наблюдений {len(t)}, БАЗОВАЯ частота разворота "
          f"в ближайшие 2 суток: {base:.0f}%")

t = pd.concat(ALL)
base = t["reversal_soon"].mean() * 100
print(f"\n=== ВСЕ АКТИВЫ: {len(t)} наблюдений, база {base:.1f}% ===")
print("\nКАКОЙ ПРИЗНАК РЕАЛЬНО ПОДНИМАЕТ ВЕРОЯТНОСТЬ РАЗВОРОТА\n")
print(f"{'признак':38s} {'случаев':>8s} {'P(разворот)':>12s} {'лифт':>7s}")

def test(name, mask):
    sub = t[mask]
    if len(sub) < 40:
        return None
    p = sub["reversal_soon"].mean() * 100
    print(f"{name:38s} {len(sub):>8d} {p:>11.0f}% {p/base:>7.2f}x")
    return p / base

res = {}
res["ход >= 10%"] = test("ход ноги >= 10%", t["move"] >= 10)
res["ход >= 15%"] = test("ход ноги >= 15%", t["move"] >= 15)
res["ход >= 20%"] = test("ход ноги >= 20%", t["move"] >= 20)
res["длит >= 40 баров"] = test("длительность >= 40 баров (7д)", t["bars"] >= 40)
res["RSI >= 70"] = test("RSI по ходу >= 70", t["rsi"] >= 70)
res["RSI >= 75"] = test("RSI по ходу >= 75", t["rsi"] >= 75)
res["отрыв EMA >= 5%"] = test("отрыв от EMA20 >= 5%", t["stretch"] >= 5)
res["отрыв EMA >= 8%"] = test("отрыв от EMA20 >= 8%", t["stretch"] >= 8)
res["объём >= 2x"] = test("объём бара >= 2x нормы (климакс)", t["vol_ratio"] >= 2)
res["объём <= 0.6x"] = test("объём <= 0.6x нормы (иссякание)", t["vol_ratio"] <= 0.6)
res["ATR-расширение"] = test("ATR расширение >= 1.5x", t["atr_exp"] >= 1.5)
res["хвост-отвержение"] = test("хвост против хода >= 50% бара", t["rej_wick"] >= 0.5)
res["дивергенция RSI"] = test("дивергенция RSI", t["diver"] == 1)

print("\n--- СОЧЕТАНИЯ (тут и должна быть сила) ---")
test("ход>=10% И RSI>=70", (t["move"] >= 10) & (t["rsi"] >= 70))
test("ход>=10% И отрыв>=5%", (t["move"] >= 10) & (t["stretch"] >= 5))
test("ход>=10% И дивергенция", (t["move"] >= 10) & (t["diver"] == 1))
test("ход>=10% И хвост>=50%", (t["move"] >= 10) & (t["rej_wick"] >= 0.5))
test("RSI>=70 И дивергенция", (t["rsi"] >= 70) & (t["diver"] == 1))
test("отрыв>=5% И объём>=2x", (t["stretch"] >= 5) & (t["vol_ratio"] >= 2))
test("ход>=10% И RSI>=70 И дивергенция",
     (t["move"] >= 10) & (t["rsi"] >= 70) & (t["diver"] == 1))
test("ход>=10% И RSI>=70 И отрыв>=5%",
     (t["move"] >= 10) & (t["rsi"] >= 70) & (t["stretch"] >= 5))
test("ход>=15% И RSI>=70 И отрыв>=5%",
     (t["move"] >= 15) & (t["rsi"] >= 70) & (t["stretch"] >= 5))
test("ВСЁ: ход>=10 RSI>=70 отрыв>=5 дивер",
     (t["move"] >= 10) & (t["rsi"] >= 70) & (t["stretch"] >= 5) & (t["diver"] == 1))
