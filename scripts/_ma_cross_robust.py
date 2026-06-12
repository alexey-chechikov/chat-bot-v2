"""Робастность топ-кандидата MA-кросса (EMA/LWMA ~12/14 close) — anchor-shift,
3-MA выравнивание, горизонты. Урок Inside Bar: если 12/14 жив, а соседи мертвы — артефакт.
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEE_RT = 0.15
CONFIRM_BARS = 3
SEP_PCT = 0.10
MIN_SIGNALS = 30


def load():
    parts = []
    for y in (2024, 2025, 2026):
        d = pd.read_csv(ROOT / "state" / f"pattern_memory_BTCUSDT_1h_{y}.csv",
                        usecols=["open_time", "open", "high", "low", "close"])
        d["year"] = y
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"])
    return df.sort_values("open_time").reset_index(drop=True)


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def crosses(fast, slow, close):
    diff = fast - slow
    sign = np.sign(diff)
    out = []
    for i in range(1, len(close)):
        if np.isnan(diff[i]) or np.isnan(diff[i - 1]) or sign[i] == sign[i - 1] or sign[i] == 0:
            continue
        d = 1 if diff[i] > 0 else -1
        j = min(i + CONFIRM_BARS, len(close) - 1)
        if np.nanmax(np.abs(diff[i:j + 1])) < SEP_PCT / 100 * close[i]:
            continue
        out.append((i, d))
    return out


def score(close, years, sigs, h):
    rows = [(years[i], d * (close[i + h] / close[i] - 1) * 100)
            for i, d in sigs if i + h < len(close)]
    if len(rows) < MIN_SIGNALS:
        return None
    a = pd.DataFrame(rows, columns=["year", "signed"])
    py = {y: (round(a[a.year == y]["signed"].mean() - FEE_RT, 2)
              if len(a[a.year == y]) >= 8 else None) for y in (2024, 2025, 2026)}
    return dict(n=len(a), hit=round((a.signed > 0).mean() * 100, 1),
                net=round(a.signed.mean() - FEE_RT, 3),
                pos=sum(1 for v in py.values() if v and v > 0), py=py)


def main():
    df = load()
    close = df["close"].to_numpy(float)
    years = df["year"].to_numpy()

    print("① ANCHOR-SHIFT соседей EMA close, горизонт 24ч (12/14 жив? соседи?):")
    print(f"{'fast/slow':>10}{'n':>5}{'hit':>6}{'net':>8}{'pos_yr':>7}  per_year")
    for fp, sp in [(11, 13), (11, 14), (11, 15), (12, 13), (12, 14), (12, 15),
                   (13, 14), (13, 15), (13, 16), (10, 14), (12, 16)]:
        r = score(close, years, crosses(ema(close, fp), ema(close, sp), close), 24)
        if r:
            star = " ⭐" if r["pos"] == 3 and r["net"] > 0.3 else ""
            print(f"{fp:>4}/{sp:<5}{r['n']:>5}{r['hit']:>6}{r['net']:>8}{r['pos']:>7}  {r['py']}{star}")

    print("\n② ГОРИЗОНТЫ для EMA 12/14 close (где эдж пик / держится):")
    s1214 = crosses(ema(close, 12), ema(close, 14), close)
    for h in (6, 12, 24, 48, 72):
        r = score(close, years, s1214, h)
        if r:
            print(f"  {h:>3}ч: n={r['n']} hit {r['hit']}% net {r['net']:+.3f}% pos_yr {r['pos']}/3  {r['py']}")

    print("\n③ 3-MA выравнивание (оператор: «3 кросса вместе = сильнее»):")
    print("   правило: сигнал когда EMA fast>mid>slow (LONG) или fast<mid<slow (SHORT),")
    print("   момент образования полного порядка из неполного. Горизонт 24ч.")
    for triple in [(7, 12, 14), (7, 13, 34), (12, 14, 34), (13, 34, 77), (7, 21, 55)]:
        f, m, s = (ema(close, triple[0]), ema(close, triple[1]), ema(close, triple[2]))
        order = np.sign(f - m) + np.sign(m - s)  # +2 = полный LONG-порядок, -2 = SHORT
        sigs = []
        for i in range(1, len(close)):
            if abs(order[i]) == 2 and abs(order[i - 1]) != 2:
                d = 1 if order[i] > 0 else -1
                sigs.append((i, d))
        r = score(close, years, sigs, 24)
        if r:
            print(f"  {triple}: n={r['n']} hit {r['hit']}% net {r['net']:+.3f}% pos_yr {r['pos']}/3  {r['py']}")

    print("\n④ ВЫХОД: EMA 12/14 — держать H баров vs выход на обратном кроссе:")
    # сравнение: фикс 24ч vs выход когда EMA12 пересекает EMA14 обратно
    f, s = ema(close, 12), ema(close, 14)
    diff = f - s
    sign = np.sign(diff)
    trades = []
    pos = 0
    for i in range(1, len(close)):
        if np.isnan(diff[i]) or sign[i] == sign[i - 1] or sign[i] == 0:
            continue
        d = 1 if diff[i] > 0 else -1
        j = min(i + CONFIRM_BARS, len(close) - 1)
        if np.nanmax(np.abs(diff[i:j + 1])) < SEP_PCT / 100 * close[i]:
            continue
        if pos != 0:
            trades.append(pos_dir * (close[i] / entry - 1) * 100 - FEE_RT)
        pos, pos_dir, entry = 1, d, close[i]
    if trades:
        t = np.array(trades)
        print(f"  выход-на-обратном-кроссе: n={len(t)} mean {t.mean():+.3f}% "
              f"win {100*(t>0).mean():.0f}% sum {t.sum():+.1f}%")


if __name__ == "__main__":
    main()
