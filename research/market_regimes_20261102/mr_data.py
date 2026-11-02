"""Общие данные разбора режимов BTC (02.11.2026, пакет GPT docs/WEEX_GPT_MARKET_REGIMES_AND_GRID_RULES_2026-11-02.md).

Минутки Binance spot BTCUSDT: backtests/frozen/BTCUSDT_1m_2017_2024.csv (17.08.2017–14.05.2024) + BTCUSDT_1m_2y.csv
(с 15.05.2024, дописывается каждый час) — прогон только на КОПИИ (путь в --src2017= / --src2y=, печатается sha256).
Пропуски 2017–2024 (8 632 минуты, 35 кусков: 08.02.2018 2 011 мин и т.п.) — остановки самой Binance; минуты не
выдумываются: бар строится по имеющимся минутам, в сетке это остановка биржи (ни исполнений, ни входов).

Средние — как в индикаторах оператора (docs/WEEX_GPT_MA_SETTINGS_AND_SIGNAL_RECHECK_2026-11-02.md §2–3, исходник
grid_regime_ruleset_v11_win.pine и bot7_strategy432.pine):
  зелёная G = TEMA50, жёлтая Y = TEMA100, красная R = TEMA200 от close; голубая B = EMA200 от close (432);
  TEMA = 3·EMA1 − 3·EMA2 + EMA3, EMA: alpha = 2/(N+1), старт с первого значения;
  зона v11: raw_long = close > Y и Y > R; raw_short = close < Y и Y < R; иначе нейтраль; 3 подряд одинаковых raw →
  зона +1 / −1 / 0, иначе прежняя;
  ATR14 — RMA истинного диапазона (как ta.atr);
  дневная SMA100 — закрытия UTC-дней Binance spot (как bot7_regime_grids.pine и engine.regime_up).
Бар с началом t известен на t + длина бара: признак бара действует с первой минуты СЛЕДУЮЩЕГО бара."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCR = Path("/private/tmp/claude-501/-Users-alexeychechikov/85655d8a-c366-454b-bd04-314adf4588cf/scratchpad/mr")


def _arg(name: str, default: Path) -> Path:
    return Path(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith(f"--{name}=")), default))


SRC_OLD = _arg("src2017", SCR / "BTCUSDT_1m_2017_2024.csv")
SRC_NEW = _arg("src2y", SCR / "BTCUSDT_1m_2y.csv")
SRC_FUND = _arg("srcfund", SCR / "BTCUSDT_funding_full.csv")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def load_1m() -> pd.DataFrame:
    """Склейка двух файлов в один ряд минут (ts — секунды UTC). Дубли и обратный ход — отказ."""
    parts = []
    for p in (SRC_OLD, SRC_NEW):
        d = pd.read_csv(p, usecols=["ts", "open", "high", "low", "close", "volume"])
        print(f"данные {p.name}: {len(d)} строк, sha256 {sha(p)}…", file=sys.stderr)
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    ms = d["ts"].to_numpy(np.int64)
    if (ms % 60_000).any() or (np.diff(ms) <= 0).any():
        sys.exit("минуты не на сетке или не строго возрастают — отказ")
    d["ts"] = ms // 1000
    if not (np.isfinite(d[["open", "high", "low", "close"]].to_numpy()).all() and (d["low"] > 0).all()
            and (d["high"] >= d["low"]).all()):
        sys.exit("битые OHLC — отказ")
    return d


def bars(m: pd.DataFrame, sec: int) -> pd.DataFrame:
    """Бары длиной sec по имеющимся минутам. Индекс — начало бара (сек UTC); known — момент, когда он закрыт."""
    k = m["ts"].to_numpy() // sec * sec
    g = m.groupby(k, sort=True)
    b = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last(), "volume": g["volume"].sum(), "nmin": g["close"].size()})
    b.index.name = "t"
    b["known"] = b.index + sec
    return b


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(x, dtype=float)
    acc = x[0]
    for i, v in enumerate(x):
        acc = v if i == 0 else a * v + (1 - a) * acc
        out[i] = acc
    return out


def tema(x: np.ndarray, n: int) -> np.ndarray:
    e1 = ema(x, n)
    e2 = ema(e1, n)
    e3 = ema(e2, n)
    return 3 * e1 - 3 * e2 + e3


def rma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    acc = np.nan
    for i, v in enumerate(x):
        if i < n - 1:
            out[i] = np.nan
            continue
        acc = np.mean(x[:n]) if i == n - 1 else (acc * (n - 1) + v) / n
        out[i] = acc
    return out


def zone_v11(c: np.ndarray, y: np.ndarray, r: np.ndarray, hold: int = 3) -> np.ndarray:
    raw = np.where((c > y) & (y > r), 1, np.where((c < y) & (y < r), -1, 0))
    z = np.zeros(len(c), dtype=int)
    cur, run, last = 0, 0, None
    for i, v in enumerate(raw):
        run = run + 1 if v == last else 1
        last = v
        if run >= hold:
            cur = v
        z[i] = cur
    return z


def add_ind(b: pd.DataFrame) -> pd.DataFrame:
    c = b["close"].to_numpy(float)
    h, l = b["high"].to_numpy(float), b["low"].to_numpy(float)
    b["G"], b["Y"], b["R"] = tema(c, 50), tema(c, 100), tema(c, 200)
    b["B"] = ema(c, 200)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    b["atr"] = rma(tr, 14)
    b["zone"] = zone_v11(c, b["Y"].to_numpy(), b["R"].to_numpy())
    b["spread"] = (b["Y"] - b["R"]).abs() / b["close"] * 100     # «0,6» Grid Regime: |TEMA100−TEMA200|/close·100
    return b


def daily_regime(d: pd.DataFrame, band: float = 0.0) -> pd.Series:
    """SMA100 закрытий UTC-дней; режим дня d+1 по закрытию d (полоса band — гистерезис как у живых сеток с 25.10).
    Неполный день (не 1440 минут) — закрытие NaN, SMA через него NaN (как regime_grid.load)."""
    dc = d["close"].where(d["nmin"] == 1440)
    sma = dc.rolling(100).mean()
    st, out = None, []
    for c, s in zip(dc.to_numpy(), sma.to_numpy()):
        if not (np.isfinite(c) and np.isfinite(s)):
            out.append(np.nan)
            continue
        if st is None:
            st = c > s
        elif st and c < s * (1 - band / 100):
            st = False
        elif not st and c > s * (1 + band / 100):
            st = True
        out.append(float(st))
    return pd.Series(out, index=d.index).shift(1), sma        # действует в день d+1


def load_funding() -> pd.Series:
    f = pd.read_csv(SRC_FUND)
    print(f"фандинг {SRC_FUND.name}: {len(f)} выплат, sha256 {sha(SRC_FUND)}…", file=sys.stderr)
    t = (f["fundingTime"].to_numpy(np.int64) // 1000) // 60 * 60    # к минуте расчёта
    return pd.Series(f["fundingRate"].to_numpy(float), index=t)


def build(cache: bool = True):
    """→ (m 1m, h1, h4, d1 с индикаторами, режим SMA100 по дням, funding). Кэш в scratchpad по sha исходников."""
    key = f"{sha(SRC_OLD)}_{sha(SRC_NEW)}"
    pk = SCR / f"bars_{key}.pkl"
    if cache and pk.exists():
        return pd.read_pickle(pk)
    m = load_1m()
    h1 = add_ind(bars(m, 3600))
    h4 = add_ind(bars(m, 14400))
    d1 = bars(m, 86400)
    d1["reg0"], d1["sma100"] = daily_regime(d1, 0.0)
    d1["reg2"], _ = daily_regime(d1, 2.0)
    out = (m, h1, h4, d1, load_funding())
    if cache:
        pd.to_pickle(out, pk)
    return out


def at_minutes(ts_min: np.ndarray, b: pd.DataFrame, col: str) -> np.ndarray:
    """Значение признака закрытого бара для каждой минуты: последний бар с known ≤ минута."""
    j = np.searchsorted(b["known"].to_numpy(), ts_min, side="right") - 1
    v = b[col].to_numpy()
    out = np.full(len(ts_min), np.nan)
    ok = j >= 0
    out[ok] = v[j[ok]]
    return out
