"""Разбор графиков BTC вместе с оператором (05.11.2026): замеры на каждой свече 1ч и 4ч.

Данные и линии — как в research/market_regimes_20261102/mr_data.py (Binance spot, только закрытые бары; график оператора —
Bybit perp, расхождение цен малое): зелёная G = TEMA50, жёлтая Y = TEMA100, красная R = TEMA200, голубая B = EMA200;
B4 — EMA200 4ч, B1 — EMA200 1ч. 4ч-значения на 1ч-баре берутся по последнему ЗАКРЫТОМУ 4ч-бару (known ≤ known 1ч-бара).
Прогон на копии снимка: scratchpad/cw/ (копирует copy_frozen.py), sha256 печатается в mr_data.load_1m."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "market_regimes_20261102"))
import gridk  # noqa: E402
import mr_data as md  # noqa: E402

SCR = Path("/private/tmp/claude-501/-Users-alexeychechikov/279942d8-034f-4a29-bc43-ed7d07642e98/scratchpad/cw")
SCR.mkdir(parents=True, exist_ok=True)
md.SCR = gridk.SCR = SCR
md.SRC_OLD = SCR / "BTCUSDT_1m_2017_2024.csv"
md.SRC_NEW = SCR / "BTCUSDT_1m_2y.csv"
md.SRC_FUND = SCR / "BTCUSDT_funding_full.csv"

HOUR = 3600
LINES = ("G", "Y", "R", "B")


def run_len(sign: np.ndarray) -> np.ndarray:
    """Сколько закрытий подряд с тем же знаком (+ над линией, − под ней)."""
    out = np.zeros(len(sign), dtype=int)
    cur = 0
    for i, s in enumerate(sign):
        if s == 0 or s != s:                    # равно линии или линии ещё нет
            cur = 0
        elif (s > 0) == (cur > 0) and cur != 0:
            cur += int(s)
        else:
            cur = int(s)
        out[i] = cur
    return out


def asof(b: pd.DataFrame, other: pd.DataFrame, col: str) -> np.ndarray:
    j = np.searchsorted(other["known"].to_numpy(), b["known"].to_numpy(), side="right") - 1
    v = other[col].to_numpy()
    out = np.full(len(b), np.nan)
    ok = j >= 0
    out[ok] = v[j[ok]]
    return out


def roll_rank(x: pd.Series, win: int) -> pd.Series:
    """Доля прошлых win баров, у которых значение ниже текущего (0 = самое низкое за окно). Без заглядывания."""
    a = x.to_numpy(float)
    out = np.full(len(a), np.nan)
    for i in range(win, len(a)):
        w = a[i - win:i]
        w = w[np.isfinite(w)]
        if len(w) and np.isfinite(a[i]):
            out[i] = float((w < a[i]).mean())
    return pd.Series(out, index=x.index)


def features(b: pd.DataFrame, other: pd.DataFrame, tf_hours: int) -> pd.DataFrame:
    """b — бары своего ТФ с линиями; other — второй ТФ (голубая и линии второго ТФ по закрытому бару)."""
    f = b.copy()
    k24 = 24 // tf_hours
    d30 = 30 * k24
    c = f["close"]
    tag = "4" if tf_hours == 1 else "1"
    for ln in LINES:
        f[f"{ln}{tag}"] = asof(b, other, ln)
    for ln in LINES:
        f[f"d_{ln}"] = (c / f[ln] - 1) * 100
        f[f"a_{ln}"] = (c - f[ln]) / f["atr"]
        f[f"slope_{ln}"] = (f[ln] / f[ln].shift(k24) - 1) * 100
        f[f"run_{ln}"] = run_len(np.sign((c - f[ln]).to_numpy()))
    other_blue = f[f"B{tag}"]
    f["d_Bo"] = (c / other_blue - 1) * 100
    f["a_Bo"] = (c - other_blue) / f["atr"]
    f["slope_Bo"] = (other_blue / other_blue.shift(k24) - 1) * 100
    f["run_Bo"] = run_len(np.sign((c - other_blue).to_numpy()))
    arr = f[list(LINES)].to_numpy()
    arr2 = np.c_[arr, other_blue.to_numpy()]
    f["width"] = (arr.max(1) - arr.min(1)) / c * 100
    f["width2"] = (np.nanmax(arr2, 1) - np.nanmin(arr2, 1)) / c * 100
    f["width_atr"] = (arr.max(1) - arr.min(1)) / f["atr"]
    f["width_rank"] = roll_rank(f["width"], 180 * k24)
    f["ret24"] = (c / c.shift(k24) - 1) * 100
    f["ret72"] = (c / c.shift(3 * k24) - 1) * 100
    v = f["volume"]
    f["vol_vs30"] = v.rolling(k24).mean() / v.rolling(d30).median().shift(k24)
    f["vol_trend"] = v.rolling(k24).mean() / v.rolling(k24).mean().shift(k24)   # сутки к прошлым суткам
    f["range_pct"] = (f["high"] - f["low"]) / c * 100
    f["atr_pct"] = f["atr"] / c * 100
    return f


def load():
    """→ (m, h1, h4, d1, fund) с замерами; кэш в scratchpad."""
    pk = SCR / "cw_bars.pkl"
    if pk.exists():
        return pd.read_pickle(pk)
    m, h1, h4, d1, fund = md.build(cache=False)
    h1f = features(h1, h4, 1)
    h4f = features(h4, h1, 4)
    out = (m, h1f, h4f, d1, fund)
    pd.to_pickle(out, pk)
    return out


def utc(t: int) -> str:
    return pd.Timestamp(t, unit="s").strftime("%d.%m %H:%M")


def T(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").timestamp())
