"""Калибровка профилей активов: трендовый эдж + пороги истощения.

Считает по каждому активу на 2 годах (4h):
  1) есть ли трендовый эдж (пробой 5д + ADX≥20, выход Chandelier ATR×3);
  2) пороги истощения В ТОЧКАХ РЕАЛЬНЫХ РАЗВОРОТОВ (ZigZag 5%):
     отрыв от EMA20 (в % и в ATR), RSI, объём;
  3) типичный размер/длительность ноги;
  4) что бывает ПОСЛЕ: мелкая коррекция / глубокая / полный разворот.

Результат → state/asset_profiles.json, откуда его читает tools/trend_state.py.
Перекалибровывать раз в квартал или после смены режима рынка.

Запуск: .venv/bin/python3 tools/calibrate_assets.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "state" / "asset_profiles.json"
ASSETS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
ZZ_PCT = 5.0          # порог ноги для ZigZag
FWD_BARS = 12         # горизонт «скоро развернётся» = 2 суток на 4h
FEE_RT = 0.10         # комиссии OKX за круг, %


def load_4h(symbol: str, years: float = 2.0) -> pd.DataFrame:
    """4h бары: локальный 2y CSV, иначе постранично с Binance."""
    p = ROOT / "backtests" / "frozen" / f"{symbol}_1m_2y.csv"
    if p.exists():
        d = pd.read_csv(p)
        unit = "ms" if d["ts"].iloc[-1] > 1e12 else "s"
        d["dt"] = pd.to_datetime(d["ts"], unit=unit, utc=True)
        d = d.set_index("dt").sort_index()
    else:
        from core.data_loader import load_historical_klines
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(365 * years))
        d = load_historical_klines(symbol, "4h",
                                   int(start.timestamp() * 1000),
                                   int(end.timestamp() * 1000))
        d = d.rename(columns={"open_time": "dt"}).set_index("dt").sort_index()
        return d[["open", "high", "low", "close", "volume"]]
    return d.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna()


def _rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1/n, adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


def _atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean().to_numpy()


def _adx(df: pd.DataFrame, n: int = 14):
    up, dn = df["high"].diff(), -df["low"].diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1/n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1/n, adjust=False).mean() / a
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1/n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return (dx.ewm(alpha=1/n, adjust=False).mean().to_numpy(),
            pdi.to_numpy(), mdi.to_numpy())


def zigzag(c: np.ndarray, pct: float = ZZ_PCT) -> list[int]:
    piv, hi_i, lo_i, direction = [0], 0, 0, 0
    for i in range(1, len(c)):
        if c[i] > c[hi_i]:
            hi_i = i
        if c[i] < c[lo_i]:
            lo_i = i
        if direction >= 0 and (c[hi_i] - c[i]) / c[hi_i] * 100 >= pct:
            if hi_i != piv[-1]:
                piv.append(hi_i)
            direction, lo_i = -1, i
        elif direction <= 0 and (c[i] - c[lo_i]) / c[lo_i] * 100 >= pct:
            if lo_i != piv[-1]:
                piv.append(lo_i)
            direction, hi_i = 1, i
    return sorted(set(piv))


def trend_edge(df: pd.DataFrame, lb: int = 30, mult: float = 3.0) -> dict:
    """Есть ли трендовый эдж: пробой lb баров при ADX≥20, Chandelier-выход."""
    d = df.copy()
    d["atr"] = _atr(d)
    d["adx"], _, _ = _adx(d)
    d["hh"] = d["high"].rolling(lb).max().shift(1)
    d["ll"] = d["low"].rolling(lb).min().shift(1)
    d = d.dropna()
    trades, pos, entry, peak = [], None, 0.0, 0.0
    for _, r in d.iterrows():
        if pos is None:
            if r["close"] > r["hh"] and r["adx"] >= 20:
                pos, entry, peak = "long", r["close"], r["high"]
            elif r["close"] < r["ll"] and r["adx"] >= 20:
                pos, entry, peak = "short", r["close"], r["low"]
            continue
        peak = max(peak, r["high"]) if pos == "long" else min(peak, r["low"])
        stop = (peak - mult * r["atr"]) if pos == "long" else (peak + mult * r["atr"])
        if (r["close"] < stop) if pos == "long" else (r["close"] > stop):
            ret = ((r["close"] / entry - 1) if pos == "long"
                   else (1 - r["close"] / entry)) * 100 - FEE_RT
            trades.append(ret)
            pos = None
    if not trades:
        return {"n": 0}
    t = np.array(trades)
    w, l = t[t > 0], t[t < 0]
    return {"n": len(t), "wr_pct": round(len(w) / len(t) * 100, 1),
            "pf": round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() else None,
            "total_pct": round(t.sum(), 1),
            "avg_win": round(w.mean(), 2) if len(w) else 0,
            "avg_loss": round(l.mean(), 2) if len(l) else 0}


def exhaustion_profile(df: pd.DataFrame) -> dict:
    """Пороги в точках реальных разворотов + что бывает после."""
    c = df["close"].to_numpy(); v = df["volume"].to_numpy()
    ema20 = pd.Series(c).ewm(span=20).mean().to_numpy()
    r = _rsi(c); atr = _atr(df)
    v_ma = pd.Series(v).rolling(30).mean().to_numpy()
    piv = zigzag(c)
    if len(piv) < 8:
        return {}
    at_rev, after, legs, durs = [], [], [], []
    for k in range(len(piv) - 1):
        a, b = piv[k], piv[k + 1]
        if b - a < 3 or np.isnan(atr[b]) or not v_ma[b]:
            continue
        up = c[b] > c[a]
        legs.append(abs(c[b] / c[a] - 1) * 100)
        durs.append(b - a)
        at_rev.append({
            "stretch_pct": abs(c[b] - ema20[b]) / ema20[b] * 100,
            "stretch_atr": abs(c[b] - ema20[b]) / atr[b],
            "rsi": r[b] if up else 100 - r[b],
            "vol_ratio": v[b] / v_ma[b],
        })
        if k + 2 < len(piv):
            nxt = piv[k + 2]
            after.append(abs(c[nxt] - c[b]) / abs(c[b] - c[a]) * 100)
    if not at_rev:
        return {}
    s = pd.DataFrame(at_rev)
    A = pd.Series(after) if after else pd.Series(dtype=float)
    return {
        "legs": len(legs),
        "leg_move_pct_med": round(float(np.median(legs)), 1),
        "leg_bars_med": int(np.median(durs)),
        "leg_days_med": round(float(np.median(durs)) * 4 / 24, 1),
        "stretch_pct_med": round(float(s["stretch_pct"].median()), 2),
        "stretch_pct_p75": round(float(s["stretch_pct"].quantile(.75)), 2),
        "stretch_atr_med": round(float(s["stretch_atr"].median()), 2),
        "stretch_atr_p75": round(float(s["stretch_atr"].quantile(.75)), 2),
        "rsi_med": round(float(s["rsi"].median())),
        "rsi_p75": round(float(s["rsi"].quantile(.75))),
        "vol_med": round(float(s["vol_ratio"].median()), 2),
        "vol_p75": round(float(s["vol_ratio"].quantile(.75)), 2),
        "after_small_pct": round(float((A < 38).mean() * 100)) if len(A) else None,
        "after_deep_pct": round(float(((A >= 38) & (A < 100)).mean() * 100)) if len(A) else None,
        "after_full_reversal_pct": round(float((A >= 100).mean() * 100)) if len(A) else None,
    }


def main() -> int:
    out = {"calibrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "method": ("4h бары, ZigZag 5% для ног; трендовый эдж = пробой 30 баров "
                      "при ADX>=20 с выходом Chandelier ATR x3, комиссии 0.1%/круг"),
           "assets": {}}
    for sym in ASSETS:
        print(f"считаю {sym}...")
        try:
            df = load_4h(sym)
        except Exception as e:
            print(f"  ошибка загрузки: {e}")
            continue
        if len(df) < 500:
            print(f"  мало данных ({len(df)} баров) — пропуск")
            continue
        edge = trend_edge(df)
        prof = exhaustion_profile(df)
        prof["trend_edge"] = edge
        prof["bars"] = len(df)
        prof["period"] = f"{df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}"
        # вердикт по трендовому боту
        pf = edge.get("pf") or 0
        prof["trend_bot_ok"] = bool(edge.get("n", 0) >= 30 and pf >= 1.2
                                    and (edge.get("total_pct") or 0) > 20)
        out["assets"][sym] = prof
        print(f"  ног {prof.get('legs')}, трендовый итог {edge.get('total_pct')}% "
              f"PF {edge.get('pf')} → бот {'ОК' if prof['trend_bot_ok'] else 'НЕТ'}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nпрофили записаны: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
