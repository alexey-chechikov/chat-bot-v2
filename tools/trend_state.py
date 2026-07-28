"""ТРЕНД: старт, сопровождение, конец — по валидированным правилам.

Валидация 2026-07-28 на 2 годах (4h бары, комиссии OKX 0.1%/круг):
вход = пробой экстремума N баров при ADX>=20, выход = Chandelier ATR-трейл.

  актив   итог 2г   PF    робастность по сетке (lb 20-60 × ATR 2-4)
  ETH     +109%    1.68   ВСЕ 16 комбинаций в плюсе  → эдж есть
  XRP     +117%    1.51   ВСЕ 16 комбинаций в плюсе  → эдж есть
  BTC      −3.5%   0.98   болтается −24…+24          → эджа НЕТ

Отсюда разделение ролей: BTC = грид (его грид-KPD 2.74 — лучший),
ETH/XRP = трендовые боты (их грид-KPD 0.49/1.02 — плохой). Активы
дополняют друг друга, а не дублируют.

Win rate трендовой ~38% — это НОРМА: много мелких стопов, редкие
крупные забеги (ср. плюс +8..10%, ср. минус −3..4%). Нельзя оценивать
по одной сделке.

Запуск: .venv/bin/python3 tools/trend_state.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# по активам: (lookback баров 4h для входа, множитель ATR для выхода)
# lb=30 (5 дней) и ATR×3 — центр устойчивой зоны, не край
ASSETS = {
    "ETHUSDT": {"lb": 30, "atr_mult": 3.0, "validated": "+109% / PF 1.68"},
    "XRPUSDT": {"lb": 30, "atr_mult": 3.0, "validated": "+117% / PF 1.51"},
    "BTCUSDT": {"lb": 30, "atr_mult": 3.0, "validated": "ЭДЖА НЕТ (−3.5%) — только грид"},
}
ADX_MIN = 20.0


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _adx(df: pd.DataFrame, n: int = 14):
    up, dn = df["high"].diff(), -df["low"].diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1/n, adjust=False).mean() / a
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1/n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def load_4h(symbol: str, bars: int = 900) -> pd.DataFrame | None:
    """4h бары: сначала локальный 2y CSV, иначе Binance."""
    p = ROOT / "backtests" / "frozen" / f"{symbol}_1m_2y.csv"
    if p.exists():
        d = pd.read_csv(p)
        unit = "ms" if d["ts"].iloc[-1] > 1e12 else "s"
        d["dt"] = pd.to_datetime(d["ts"], unit=unit, utc=True)
        d = d.set_index("dt").sort_index()
    else:
        from core.data_loader import load_klines
        d = load_klines(symbol, "1h", 1000)
        d = d.rename(columns={"open_time": "dt"}).set_index("dt")
    return d.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last"}).dropna().tail(bars)


def state(symbol: str, cfg: dict) -> dict | None:
    df = load_4h(symbol)
    if df is None or len(df) < 60:
        return None
    df["atr"] = _atr(df)
    df["adx"], df["pdi"], df["mdi"] = _adx(df)
    df["hh"] = df["high"].rolling(cfg["lb"]).max().shift(1)
    df["ll"] = df["low"].rolling(cfg["lb"]).min().shift(1)
    df = df.dropna()

    # проходим историю, чтобы понять, В ТРЕНДЕ ли сейчас и где стоп
    pos, entry, peak, since = None, 0.0, 0.0, None
    for ts, r in df.iterrows():
        if pos is None:
            if r["close"] > r["hh"] and r["adx"] >= ADX_MIN:
                pos, entry, peak, since = "LONG", r["close"], r["high"], ts
            elif r["close"] < r["ll"] and r["adx"] >= ADX_MIN:
                pos, entry, peak, since = "SHORT", r["close"], r["low"], ts
            continue
        peak = max(peak, r["high"]) if pos == "LONG" else min(peak, r["low"])
        stop = (peak - cfg["atr_mult"] * r["atr"] if pos == "LONG"
                else peak + cfg["atr_mult"] * r["atr"])
        if (r["close"] < stop) if pos == "LONG" else (r["close"] > stop):
            pos, since = None, None

    last = df.iloc[-1]
    out = {"px": last["close"], "adx": last["adx"], "atr": last["atr"],
           "pdi": last["pdi"], "mdi": last["mdi"],
           "hh": last["hh"], "ll": last["ll"], "pos": pos}
    if pos:
        out["entry"] = entry
        out["since"] = since
        out["peak"] = peak
        out["stop"] = (peak - cfg["atr_mult"] * last["atr"] if pos == "LONG"
                       else peak + cfg["atr_mult"] * last["atr"])
        out["open_pnl"] = ((last["close"] / entry - 1) if pos == "LONG"
                           else (1 - last["close"] / entry)) * 100
        out["dist_stop"] = abs(last["close"] - out["stop"]) / last["close"] * 100
    return out


def main() -> int:
    print("ТРЕНДОВОЕ СОСТОЯНИЕ (4h, вход: пробой 5д + ADX≥20, "
          "выход: Chandelier ATR×3)\n")
    for sym, cfg in ASSETS.items():
        s = state(sym, cfg)
        if not s:
            print(f"{sym}: нет данных")
            continue
        print(f"=== {sym}  ${s['px']:,.4f}  [{cfg['validated']}] ===")
        print(f"  ADX {s['adx']:.0f} ({'тренд' if s['adx'] >= ADX_MIN else 'нет тренда'})"
              f"  +DI {s['pdi']:.0f} / −DI {s['mdi']:.0f}  ATR {s['atr']:,.4f}")
        if s["pos"]:
            print(f"  🔥 В ТРЕНДЕ: {s['pos']} с {s['since']:%d.%m %H:%M} "
                  f"от {s['entry']:,.4f}, открытый PnL {s['open_pnl']:+.1f}%")
            print(f"  ВЫХОД (стоп-трейл): {s['stop']:,.4f} "
                  f"— до него {s['dist_stop']:.1f}%")
            print(f"  → закрывать/разворачивать при закрытии 4h "
                  f"{'НИЖЕ' if s['pos'] == 'LONG' else 'ВЫШЕ'} {s['stop']:,.4f}")
        else:
            print(f"  тренда нет. Вход {'LONG' if True else ''} при закрытии 4h "
                  f"выше {s['hh']:,.4f}, SHORT — ниже {s['ll']:,.4f} (при ADX≥20)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
