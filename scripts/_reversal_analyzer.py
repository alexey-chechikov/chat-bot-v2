"""Анализатор разворота + отмены сценария (ТЗ оператора 2026-06-13).
Локально 4ч (EMA14/77/200) + глобально 1д (EMA200). Бэктест: какие явные уровни
ВЫХОДА реально режут убыток, и подтверждает ли глобальная сторона локальный сигнал.
Цель: явные маркеры «сейчас лонг/шорт» + цена ОТМЕНЫ. BTC 1ч 2024-2026.
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEE = 0.10


def load_tf(rule):
    parts = [pd.read_csv(ROOT / "state" / f"pattern_memory_BTCUSDT_1h_{y}.csv",
                         usecols=["open_time", "open", "high", "low", "close"]) for y in (2024, 2025, 2026)]
    df = pd.concat(parts)
    df["open_time"] = pd.to_datetime(df["open_time"])
    df = df.set_index("open_time").sort_index()
    o = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return o


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def main():
    d4 = load_tf("4h").reset_index()
    d1 = load_tf("1D")
    hl2 = ((d4["high"] + d4["low"]) / 2).to_numpy(float)
    close = d4["close"].to_numpy(float)
    e14, e77, e200 = ema(hl2, 14), ema(hl2, 77), ema(hl2, 200)
    # дневная EMA200 (глобальная линия), смэппленная на 4ч-бары as-of
    d1hl2 = ((d1["high"] + d1["low"]) / 2)
    d1e200 = d1hl2.ewm(span=200, adjust=False).mean()
    d1e50 = d1hl2.ewm(span=50, adjust=False).mean()
    g200 = d1e200.reindex(d4["open_time"], method="ffill").to_numpy()
    g50 = d1e50.reindex(d4["open_time"], method="ffill").to_numpy()

    diff = e14 - e77
    sign = np.sign(diff)
    cx = [i for i in range(1, len(close)) if sign[i] != 0 and sign[i] != sign[i - 1]]

    def passed(i, d):
        slope_ok = (e77[i] - e77[i - 5] > 0) == (d == 1) if i >= 5 else False
        side_ok = (close[i] > e200[i]) == (d == 1)
        return slope_ok and side_ok

    # сигналы H5 (прошедшие фильтры + анти-whipsaw)
    sigs = []
    for k, i in enumerate(cx):
        d = 1 if diff[i] > 0 else -1
        leg = (i - cx[k - 1]) if k > 0 else 99
        if passed(i, d) and leg > 4:
            sigs.append((k, i, d))

    def run_exit(rule):
        """rule(i_entry, d, j) -> True если выйти на баре j (до обратного кросса)."""
        rets, dds = [], []
        for (k, i, d) in sigs:
            nxt = cx[k + 1] if k + 1 < len(cx) else len(close) - 1
            exit_j = nxt
            for j in range(i + 1, nxt + 1):
                if rule and rule(i, d, j):
                    exit_j = j
                    break
            ret = d * (close[exit_j] / close[i] - 1) * 100 - FEE
            rets.append(ret)
        return np.array(rets)

    def report(name, rets):
        if not len(rets):
            return
        wins = rets[rets > 0]; loss = rets[rets <= 0]
        pf = wins.sum() / abs(loss.sum()) if len(loss) else float("inf")
        eq = np.cumsum(rets); dd = (np.maximum.accumulate(eq) - eq).max()
        print(f"  {name:34} n={len(rets):3} net {rets.sum():+6.0f}пп win {100*len(wins)/len(rets):3.0f}% "
              f"PF {pf:4.2f} ср.убыток {loss.mean() if len(loss) else 0:+5.2f}% maxDD {dd:4.0f}")

    print(f"BTC 4ч, H5-сигналов: {len(sigs)}. Тест уровней ОТМЕНЫ сценария (выход раньше обратного кросса):\n")
    report("базово (до обратного кросса)", run_exit(None))
    report("отмена: close против EMA77", run_exit(lambda i, d, j: (close[j] < e77[j]) if d == 1 else (close[j] > e77[j])))
    report("отмена: close против EMA14", run_exit(lambda i, d, j: (close[j] < e14[j]) if d == 1 else (close[j] > e14[j])))
    report("отмена: глоб. EMA200(1д) пробита", run_exit(lambda i, d, j: (close[j] < g200[j]) if d == 1 else (close[j] > g200[j])))

    # глобальное подтверждение: H5 ПО дневному тренду vs против
    print("\nГлобальный фильтр (дневная EMA200 — водораздел):")
    aligned, against = [], []
    for (k, i, d) in sigs:
        nxt = cx[k + 1] if k + 1 < len(cx) else len(close) - 1
        ret = d * (close[nxt] / close[i] - 1) * 100 - FEE
        glob = 1 if close[i] > g200[i] else -1
        (aligned if glob == d else against).append(ret)
    report("H5 ПО глобальному тренду", np.array(aligned))
    report("H5 ПРОТИВ глобального", np.array(against))

    live_read()


def _fetch(symbol, interval, limit):
    import requests
    r = requests.get("https://api.bybit.com/v5/market/kline",
                     params={"category": "linear", "symbol": symbol, "interval": interval,
                             "limit": limit + 1}, timeout=12)
    r.raise_for_status()
    lst = r.json().get("result", {}).get("list", [])
    rows = [[int(x[0]), float(x[2]), float(x[3]), float(x[4])] for x in lst]  # ts,h,l,c
    rows.sort(key=lambda x: x[0])
    return rows[:-1]


def live_read(symbol="BTCUSDT"):
    """Текущий читай на ЖИВЫХ данных Bybit (4ч локально + 1д глобально)."""
    r4 = _fetch(symbol, "240", 600)
    r1 = _fetch(symbol, "D", 400)
    if len(r4) < 220 or len(r1) < 60:
        print("живые данные недоступны"); return
    hl2_4 = [(h + l) / 2 for _, h, l, _c in r4]
    c4 = [x[3] for x in r4]
    e14, e77, e200 = ema(hl2_4, 14)[-1], ema(hl2_4, 77)[-1], ema(hl2_4, 200)[-1]
    e77_5 = ema(hl2_4, 77)[-6]
    hl2_1 = [(h + l) / 2 for _, h, l, _c in r1]
    g200 = ema(hl2_1, 200)[-1]
    g50 = ema(hl2_1, 50)[-1]
    px = c4[-1]
    d = 1 if e14 > e77 else -1
    slope_ok = (e77 - e77_5 > 0) == (d == 1)
    side_ok = (px > e200) == (d == 1)
    loc = "LONG" if d == 1 else "SHORT"
    h5_ok = slope_ok and side_ok
    glob = "LONG (над 200d)" if px > g200 else "SHORT (под 200d)"

    print("\n" + "=" * 66)
    print(f"ТЕКУЩИЙ ЧИТАЙ {symbol} (живой Bybit)  ·  цена {px:,.0f}")
    print(f"  ЛОКАЛЬНО 4ч: EMA14 {e14:,.0f} {'>' if d==1 else '<'} EMA77 {e77:,.0f} · EMA200·4ч {e200:,.0f}")
    print(f"     → уклон {loc}" + (" H5✓ (наклон+режим)" if h5_ok else
          f" но H5 НЕ прошёл ({'наклон' if not slope_ok else ''}{' ' if not slope_ok and not side_ok else ''}{'режим' if not side_ok else ''}) → НЕЙТРАЛ"))
    print(f"  ГЛОБАЛЬНО 1д: цена vs EMA200d {g200:,.0f} → {glob} · EMA50d {g50:,.0f}")
    print("\n  ЯВНЫЕ УРОВНИ:")
    if d == 1:
        print(f"    • ЛОНГ-сценарий жив, пока EMA14>EMA77. ОТМЕНА (закрыть лонг) = обратный кросс")
        print(f"      EMA14 под EMA77 — случится при сходе цены к ~{e77:,.0f} (валидир. выход, НЕ раньше)")
        print(f"    • структурные маркеры слабости (НЕ паник-выход): потеря EMA77 {e77:,.0f}, затем EMA200·4ч {e200:,.0f}")
        print(f"    • ГЛОБАЛЬНО вверх подтвердится дневным закрытием выше EMA200d {g200:,.0f}")
    else:
        print(f"    • ШОРТ-сценарий жив, пока EMA14<EMA77. ОТМЕНА (закрыть шорт) = обратный кросс")
        print(f"      EMA14 над EMA77 — при росте к ~{e77:,.0f}")
        print(f"    • реклейм EMA77 {e77:,.0f} = ранний звонок, EMA200·4ч {e200:,.0f} = сильный, EMA200d {g200:,.0f} = глобальный разворот")


if __name__ == "__main__":
    main()
