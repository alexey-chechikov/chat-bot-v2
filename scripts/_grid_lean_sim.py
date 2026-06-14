"""Задача 1 Вина [деньги]: H5-уклон vs текущий TEMA200-гейт на ПОЛНОМ grid-симе книги.
Полный PnL дуальной книги (лонг+шорт ноги) + max-bag (DD-прокси) под тремя gate-режимами:
  TEMA  — текущий гейт (build_allow по TEMA200 4ч; он же MARKDOWN-гейт в alt_guard);
  H5    — EMA14/77/200 4ч уклон: ногу против уклона ЗАКРЫВАЕМ (flip);
  H5cap — ногу против уклона лишь НЕ доливаем (cap, не force-close).
Приёмка: H5 net ≥ TEMA при не-большей DD на BTC/ETH/XRP. Данные frozen 1m 2y.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import _grid_sim as gs

FROZEN = ROOT / "backtests" / "frozen"


def load_ohlc(sym, a=None):
    df = pd.read_csv(FROZEN / f"{sym}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    if a:
        df = df.loc[a:]
    return df


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def ma100_allow_1m(df, side, tf="4h"):
    """MA100-свитч Вина (baseline): знак (close − SMA100) на 4ч, hold 3, причинно на 1m."""
    o = df.resample(tf).agg({"close": "last"}).dropna()
    c = o["close"]
    sma = c.rolling(100).mean()
    raw = np.sign((c - sma).to_numpy())
    lean = np.zeros(len(raw)); cur = 0.0; run = 0; prev = 0.0
    for i in range(len(raw)):
        if np.isnan(raw[i]):
            lean[i] = cur; continue
        if raw[i] == prev:
            run += 1
        else:
            run = 1; prev = raw[i]
        if run >= 3 and raw[i] != 0:
            cur = raw[i]
        lean[i] = cur
    ok = (lean >= 0) if side == "long" else (lean <= 0)
    s = pd.Series(ok, index=o.index + pd.Timedelta(tf))
    return s.reindex(df.index, method="ffill").fillna(False).astype(bool).to_numpy()


def h5_lean_1m(df, tf="4h"):
    """H5-уклон (+1/-1/0) на 4ч, причинно смэпплен на 1m. Лонг/шорт после
    прошедшего фильтры кросса, 0 если кросс не прошёл (нейтрал), холд до кросса."""
    o = df.resample(tf).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    hl2 = (o["high"] + o["low"]) / 2
    e14 = ema(hl2, 14).to_numpy(); e77 = ema(hl2, 77).to_numpy()
    e200 = ema(hl2, 200).to_numpy(); c = o["close"].to_numpy()
    diff = e14 - e77; sign = np.sign(diff); n = len(c)
    lean = np.zeros(n); cur = 0.0
    last_cross = -999
    for i in range(1, n):
        if sign[i] != 0 and sign[i] != sign[i - 1]:
            d = 1 if diff[i] > 0 else -1
            slope_ok = (e77[i] - e77[i - 5] > 0) == (d == 1) if i >= 5 else False
            side_ok = (c[i] > e200[i]) == (d == 1)
            leg_ok = (i - last_cross) > 4
            cur = float(d) if (slope_ok and side_ok and leg_ok) else 0.0
            last_cross = i
        lean[i] = cur
    s = pd.Series(lean, index=o.index + pd.Timedelta(tf))   # причинный сдвиг
    return s.reindex(df.index, method="ffill").fillna(0.0).to_numpy()


def book(close, allow_long, allow_short, close_on_disallow,
         close_long=None, close_short=None, **kw):
    """Полная книга: лонг-нога + шорт-нога. → (net, max_bag_сумм).
    close_long/short — маска принудительного закрытия ноги (для гибрида растяжки)."""
    lo = gs.sim(close, side="long", allow=allow_long, close_on_disallow=close_on_disallow,
                close_mask=close_long, **kw)
    sh = gs.sim(close, side="short", allow=allow_short, close_on_disallow=close_on_disallow,
                close_mask=close_short, **kw)
    return lo["profit"] + sh["profit"], lo["max_bag"] + sh["max_bag"]


def stretch_1m(df, tf="4h"):
    """Растяжка |close−EMA77|/close на 4ч (конвикшн-уклон Вина), причинно на 1m."""
    o = df.resample(tf).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    hl2 = (o["high"] + o["low"]) / 2
    e77 = ema(hl2, 77)
    st = (o["close"] - e77).abs() / o["close"] * 100
    s = pd.Series(st.to_numpy(), index=o.index + pd.Timedelta(tf))
    return s.reindex(df.index, method="ffill").fillna(0.0).to_numpy()


def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
    start = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"Grid-книга: H5-уклон vs TEMA200-гейт (frozen 1m{' от '+start if start else ' 2y'})\n")
    print(f"{'символ':9}{'режим':9}{'net книги':>11}{'max-bag':>10}{'vs TEMA net':>13}{'vs TEMA bag':>13}")
    for sym in syms:
        df = load_ohlc(sym, start)
        close = df["close"]
        # TEMA-гейт (текущий)
        al = gs.build_allow(close, side="long")
        ash = gs.build_allow(close, side="short")
        # H5-уклон
        lean = h5_lean_1m(df)
        h5_long = lean >= 0     # лонг разрешён при уклоне LONG или НЕЙТРАЛ
        h5_short = lean <= 0    # шорт разрешён при уклоне SHORT или НЕЙТРАЛ
        res = {}
        res["TEMA"] = book(close, al, ash, close_on_disallow=True)
        res["MA100"] = book(close, ma100_allow_1m(df, "long"), ma100_allow_1m(df, "short"), close_on_disallow=True)
        res["H5"] = book(close, h5_long, h5_short, close_on_disallow=True)
        res["H5cap"] = book(close, h5_long, h5_short, close_on_disallow=False)
        # ГИБРИД Вина: направление от TEMA, растяжка модулирует СИЛУ капа — force-close
        # неправой ноги ТОЛЬКО на высокой растяжке (сильный ход = режем), иначе лишь не доливаем.
        st = stretch_1m(df)
        thr = float(np.nanmedian(st[st > 0])) if (st > 0).any() else 1.0
        hi = st >= thr
        close_long = (~al) & hi      # TEMA говорит «лонг-нога неправая» И конвикшн высокий
        close_short = (~ash) & hi
        res["TEMA+растяжка"] = book(close, al, ash, close_on_disallow=False,
                                    close_long=close_long, close_short=close_short)
        base_net, base_bag = res["TEMA"]
        for mode in ("TEMA", "MA100", "H5", "H5cap", "TEMA+растяжка"):
            net, bag = res[mode]
            dn = "" if mode == "TEMA" else f"{net-base_net:+.0f}"
            dbag = "" if mode == "TEMA" else f"{bag-base_bag:+.0f}"
            print(f"{sym:9}{mode:9}{net:>11.0f}{bag:>10.0f}{dn:>13}{dbag:>13}")
        print()


if __name__ == "__main__":
    main()
