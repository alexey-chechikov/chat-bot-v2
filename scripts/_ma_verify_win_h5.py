"""Независимая проверка рулсета Вина H5 (EMA 14/77 hl2 4ч) на ДРУГИХ данных.
Win: BitMEX 2г. Здесь: Binance pattern_memory BTC 1ч 2024-2026 → ресемпл 4ч.
Цель — реплицируются ли его 3 фильтра на другом движке/бирже (его главный запрос)."""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEE = 0.10  # %/реверс, как у Вина


def load_4h():
    parts = []
    for y in (2024, 2025, 2026):
        d = pd.read_csv(ROOT / "state" / f"pattern_memory_BTCUSDT_1h_{y}.csv",
                        usecols=["open_time", "open", "high", "low", "close"])
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"])
    df = df.set_index("open_time").sort_index()
    o = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return o.reset_index()


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def trades_with_context(df):
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
    close = df["close"].to_numpy(float)
    e14, e77, e200 = ema(hl2, 14), ema(hl2, 77), ema(hl2, 200)
    diff = e14 - e77
    sign = np.sign(diff)
    # точки кросса
    cross = [i for i in range(1, len(close))
             if not np.isnan(diff[i]) and not np.isnan(diff[i - 1])
             and sign[i] != sign[i - 1] and sign[i] != 0]
    rows = []
    for k in range(len(cross) - 1):
        i, nxt = cross[k], cross[k + 1]
        d = 1 if diff[i] > 0 else -1
        ret = d * (close[nxt] / close[i] - 1) * 100 - FEE  # удержание до обратного кросса
        leg_prev = (i - cross[k - 1]) if k > 0 else 99      # длина прошлой ноги, баров
        slope77 = e77[i] - e77[i - 5] if i >= 5 else 0.0
        slope_ok = (slope77 > 0) == (d == 1)
        side_ok = (close[i] > e200[i]) == (d == 1) if not np.isnan(e200[i]) else False
        stretch = abs(close[i] - e77[i]) / close[i] * 100
        rows.append(dict(ret=ret, d=d, leg_prev=leg_prev, slope_ok=slope_ok,
                         side_ok=side_ok, stretch=stretch))
    return pd.DataFrame(rows)


def split(t, mask, label):
    a, b = t[mask]["ret"], t[~mask]["ret"]
    print(f"  {label:38} ДА: {a.mean():+.2f}% (n{len(a)})  ·  НЕТ: {b.mean():+.2f}% (n{len(b)})")


def main():
    df = load_4h()
    print(f"BTC 4ч Binance, {len(df)} баров (~2.3г). Fee {FEE}%/реверс.\n")
    t = trades_with_context(df)
    base = t["ret"]
    eq = (1 + base / 100).prod() - 1
    pf = base[base > 0].sum() / abs(base[base < 0].sum()) if (base < 0).any() else float("inf")
    print(f"БАЗА EMA14/77 hl2 (без фильтров): n={len(t)} net {base.sum():+.0f}пп "
          f"equity ×{1+eq:.2f} PF {pf:.2f} win {100*(base>0).mean():.0f}%\n")

    print("Проверка фильтров Вина (его BTC-числа в скобках):")
    split(t, t["slope_ok"], "①наклон EMA77 по кроссу (+2.35/−2.39)")
    split(t, t["side_ok"], "②цена на стороне EMA200 (+2.48/+1.07)")
    split(t, t["leg_prev"] > 4, "③прошлая нога >4 бара / whipsaw (+2.30/−2.04)")
    split(t, t["stretch"] > t["stretch"].median(), "④растяжка от EMA77 (сюрприз +2.99/+0.86)")

    # H5: все три фильтра
    h5 = t[t["slope_ok"] & t["side_ok"] & (t["leg_prev"] > 4)]["ret"]
    if len(h5):
        eqh = (1 + h5 / 100).prod() - 1
        pfh = h5[h5 > 0].sum() / abs(h5[h5 < 0].sum()) if (h5 < 0).any() else float("inf")
        # max drawdown по equity-кривой
        curve = (1 + h5 / 100).cumprod()
        dd = (1 - curve / curve.cummax()).max() * 100
        print(f"\nРУЛСЕТ H5 (все 3 фильтра): n={len(h5)} net {h5.sum():+.0f}пп "
              f"equity ×{1+eqh:.2f} PF {pfh:.2f} win {100*(h5>0).mean():.0f}% DD {dd:.0f}%")
        print(f"(Вин BTC: n34 +118пп PF 4.13 win 50% DD 21%)")


if __name__ == "__main__":
    main()
