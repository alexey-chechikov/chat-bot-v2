"""Честный перебор MA-кроссоверов на BTC 1h (2024-2026) — ТЗ оператора 2026-06-12.

Дисциплина (память: EMA/SMA-гейт уже падал OOS; Inside Bar = anchor-артефакт):
- forward-доходность после РЕАЛЬНОГО пересечения (с фильтром касаний);
- per-year стабильность (2024 train / 2025 val / 2026 test) — overfit ловим тут;
- net edge после комиссий (0.15% RT taker linear);
- 4-я линия = длинный якорь-фильтр (брать кросс только на «правильной» стороне MA-anchor);
- baseline: безусловная forward-доходность (кросс должен бить «всегда лонг/шорт»).

Запуск: .venv/bin/python3 scripts/_ma_cross_sweep.py
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEE_RT = 0.15          # % round-trip taker (XBTUSDT linear)
H = 24                 # горизонт удержания, баров (1h → сутки)
CONFIRM_BARS = 3       # подтверждение кросса: |diff| должен превысить порог за N баров
SEP_PCT = 0.10         # мин. расхождение MA после кросса, % цены = «не касание»
MIN_SIGNALS = 40       # меньше — статистически шумно, пропускаем


def load() -> pd.DataFrame:
    parts = []
    for y in (2024, 2025, 2026):
        p = ROOT / "state" / f"pattern_memory_BTCUSDT_1h_{y}.csv"
        d = pd.read_csv(p, usecols=["open_time", "open", "high", "low", "close"])
        d["year"] = y
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"])
    return df.sort_values("open_time").reset_index(drop=True)


def price(df, kind):
    if kind == "close":
        return df["close"].to_numpy(float)
    if kind == "open":
        return df["open"].to_numpy(float)
    if kind == "median":
        return ((df["high"] + df["low"]) / 2).to_numpy(float)
    if kind == "typical":
        return ((df["high"] + df["low"] + df["close"]) / 3).to_numpy(float)
    raise ValueError(kind)


def ma(x, n, method):
    s = pd.Series(x)
    if method == "SMA":
        return s.rolling(n).mean().to_numpy()
    if method == "EMA":
        return s.ewm(span=n, adjust=False).mean().to_numpy()
    if method == "SMMA":            # Wilder / RMA
        return s.ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()
    if method == "LWMA":            # linear weighted (вес = позиция)
        w = np.arange(1, n + 1, dtype=float)
        return s.rolling(n).apply(lambda a: np.dot(a, w) / w.sum(), raw=True).to_numpy()
    raise ValueError(method)


def eval_combo(close, fast, slow, years, anchor=None, anchor_px=None):
    """Возвращает dict с метриками по сигналам пересечения fast/slow.
    anchor: MA-фильтр (4-я линия) — брать LONG только при anchor_px>anchor, SHORT наоборот."""
    diff = fast - slow
    sign = np.sign(diff)
    n = len(close)
    sigs = []  # (idx, dir)
    for i in range(1, n):
        if np.isnan(diff[i]) or np.isnan(diff[i - 1]):
            continue
        if sign[i] == sign[i - 1] or sign[i] == 0:
            continue
        d = 1 if diff[i] > 0 else -1  # up-cross = LONG
        # фильтр касания: |diff| должен превысить SEP_PCT% за CONFIRM_BARS
        j = min(i + CONFIRM_BARS, n - 1)
        seg = np.abs(diff[i:j + 1])
        if not len(seg) or np.nanmax(seg) < SEP_PCT / 100.0 * close[i]:
            continue
        # 4-я линия: якорь-фильтр
        if anchor is not None:
            if np.isnan(anchor[i]):
                continue
            if d == 1 and anchor_px[i] <= anchor[i]:
                continue
            if d == -1 and anchor_px[i] >= anchor[i]:
                continue
        sigs.append((i, d))
    rows = []
    for i, d in sigs:
        if i + H >= n:
            continue
        ret = (close[i + H] / close[i] - 1) * 100
        rows.append((years[i], d, d * ret))      # signed = доходность в сторону сигнала
    if len(rows) < MIN_SIGNALS:
        return None
    arr = pd.DataFrame(rows, columns=["year", "dir", "signed"])
    net = arr["signed"].mean() - FEE_RT
    hit = (arr["signed"] > 0).mean() * 100
    per_year = {}
    for y in (2024, 2025, 2026):
        sub = arr[arr["year"] == y]
        per_year[y] = round(sub["signed"].mean() - FEE_RT, 3) if len(sub) >= 10 else None
    pos_years = sum(1 for v in per_year.values() if v is not None and v > 0)
    return dict(n=len(arr), hit=round(hit, 1), net=round(net, 3),
                per_year=per_year, pos_years=pos_years)


def main():
    df = load()
    years = df["year"].to_numpy()
    close = df["close"].to_numpy(float)

    # baseline: безусловная forward-доходность (|edge| кросса меряем ПРОТИВ этого)
    base = []
    for i in range(len(close) - H):
        base.append((close[i + H] / close[i] - 1) * 100)
    base = np.array(base)
    print(f"BTC 1h, {len(df)} баров (2024-2026). Горизонт {H}ч, fee {FEE_RT}% RT.")
    print(f"BASELINE 24ч: mean {base.mean():+.3f}%  |  up {100*(base>0).mean():.0f}%  "
          f"(кросс должен бить это направленно)\n")

    PERIODS = [7, 12, 13, 14, 21, 34, 55, 77, 89, 100, 200]
    METHODS = ["SMA", "EMA", "SMMA", "LWMA"]
    PRICES = ["close", "median"]

    results = []
    for pr in PRICES:
        px = price(df, pr)
        anchor200 = pd.Series(px).ewm(span=200, adjust=False).mean().to_numpy()
        for method in METHODS:
            ma_cache = {n: ma(px, n, method) for n in PERIODS}
            for fi, fp in enumerate(PERIODS):
                for sp in PERIODS[fi + 1:]:
                    for use_anchor in (False, True):
                        r = eval_combo(close, ma_cache[fp], ma_cache[sp], years,
                                       anchor=anchor200 if use_anchor else None,
                                       anchor_px=px if use_anchor else None)
                        if r:
                            r.update(method=method, price=pr, fast=fp, slow=sp,
                                     anchor="MA200" if use_anchor else "—")
                            results.append(r)

    res = pd.DataFrame(results)
    # робастные: положительны в ≥2 годах И net>baseline-edge И достаточно сигналов
    base_edge = base.mean()  # направленный дрейф рынка
    res["beats_base"] = res["net"] > abs(base_edge)
    robust = res[(res["pos_years"] >= 2) & (res["net"] > 0)].copy()
    robust = robust.sort_values("net", ascending=False)

    print("=== ТОП-15 по net edge (24ч, после fees), КОМБО ===")
    cols = ["method", "price", "fast", "slow", "anchor", "n", "hit", "net", "pos_years", "per_year"]
    with pd.option_context("display.width", 200, "display.max_colwidth", 40):
        print(robust[cols].head(15).to_string(index=False))

    print(f"\nВсего комбо протестировано: {len(res)};  робастных (net>0, ≥2 года+): {len(robust)}")
    print(f"С якорем MA200 в топ-15: {(robust.head(15)['anchor'] == 'MA200').sum()}/15")

    # эффект 4-й линии: средний net с якорем vs без, на одинаковых fast/slow
    merged = res.pivot_table(index=["method", "price", "fast", "slow"],
                             columns="anchor", values="net")
    if "MA200" in merged and "—" in merged:
        delta = (merged["MA200"] - merged["—"]).dropna()
        print(f"\n4-я линия (MA200-фильтр): средний Δnet {delta.mean():+.3f}%  "
              f"улучшил {100*(delta>0).mean():.0f}% комбо  (n={len(delta)})")

    res.to_csv(ROOT / "state" / "ma_cross_sweep_results.csv", index=False)
    print("\n→ полная таблица: state/ma_cross_sweep_results.csv")


if __name__ == "__main__":
    main()
