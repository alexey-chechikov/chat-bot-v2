#!/usr/bin/env python3
"""SHADOW-режим: непрерывная запись признаков затяжного роста и просадки.

Ничего не решает и никуда не вмешивается — только пишет. Смысл в том, чтобы
через месяцы можно было сопоставить «как выглядели признаки ДО» с «что
случилось ПОСЛЕ» на СВЕЖИХ данных, а не на тех, по которым признаки подбирались.

Эпизод определяется зигзагом с порогом отката:
  затяжной рост   — от локального минимума цена прошла >= RALLY_MIN%,
                    эпизод жив, пока откат от максимума эпизода < RETRACE%
  затяжная просадка — зеркально

Режимы:
  --backfill   построить историю из backtests/frozen (2 года, с OI/funding/тейкером)
               и market_live/market_1m.csv (свежий хвост)
  --tick       дописать строки за новые часы (для запуска по расписанию)
  --report     свести признаки с фактическими исходами и показать лифты

Файл: state/shadow_regime.jsonl — одна строка на час.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "state" / "shadow_regime.jsonl"
FROZEN = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
PUMP = ROOT / "data" / "pump_research" / "BTCUSDT_pump_features_1m.csv"
LIVE = ROOT / "market_live" / "market_1m.csv"

RALLY_MIN = 6.0      # % — с какого хода считаем движение затяжным
RETRACE = 3.0        # % отката от экстремума эпизода = конец эпизода
SCHEMA = 1


# ---------------------------------------------------------------- источники

def _hourly(df: pd.DataFrame) -> pd.DataFrame:
    agg = {"high": "max", "low": "min", "close": "last"}
    for extra, how in (("volume", "sum"), ("quote_volume", "sum"),
                       ("trades", "sum"), ("taker_buy_volume", "sum"),
                       ("funding_rate", "last"), ("open_interest", "last")):
        if extra in df.columns:
            agg[extra] = how
    h = df.resample("1h").agg(agg)
    return h.dropna(subset=["close"])


def load_history() -> pd.DataFrame:
    """Два года с деривативами + свежий хвост из живого коллектора."""
    frames = []
    if PUMP.exists():
        cols = ["ts", "high", "low", "close", "volume", "quote_volume",
                "trades", "taker_buy_volume", "funding_rate", "open_interest"]
        d = pd.read_csv(PUMP, usecols=cols)
        d["ts"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
        frames.append(_hourly(d.dropna(subset=["ts"]).set_index("ts")))
    elif FROZEN.exists():
        d = pd.read_csv(FROZEN)
        d["ts"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
        frames.append(_hourly(d.dropna(subset=["ts"]).set_index("ts")))
    if LIVE.exists():
        d = pd.read_csv(LIVE, on_bad_lines="skip")
        d["ts"] = pd.to_datetime(d["ts_utc"], utc=True, errors="coerce")
        for c in ("high", "low", "close", "volume"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=["ts", "close"]).set_index("ts")
        frames.append(_hourly(d))
    if not frames:
        raise SystemExit("нет источников данных")
    h = pd.concat(frames).sort_index()
    h = h[~h.index.duplicated(keep="last")]
    for c in ("funding_rate", "open_interest"):
        if c in h.columns:
            h[c] = h[c].ffill()
    return h


# ---------------------------------------------------------------- признаки

def features(h: pd.DataFrame) -> pd.DataFrame:
    r = np.log(h["close"]).diff()
    hi7, lo7 = h["high"].rolling(168).max(), h["low"].rolling(168).min()
    f = pd.DataFrame(index=h.index)
    f["price"] = h["close"]
    # волатильность — сильнейший одиночный предиктор (лифт 1.54 на 7д)
    f["vol_24h"] = r.rolling(24).std() * 100
    f["vol_7d"] = r.rolling(168).std() * 100
    f["vol_ratio_24h_7d"] = r.rolling(24).std() / r.rolling(168).std()
    f["range_24h_pct"] = (h["high"].rolling(24).max()
                          / h["low"].rolling(24).min() - 1) * 100
    # положение в структуре — обратные предикторы роста
    f["chan_pos_7d"] = (h["close"] - lo7) / (hi7 - lo7)
    f["dd_from_30d_high_pct"] = (1 - h["close"]
                                 / h["high"].rolling(720).max()) * 100
    f["ret_7d_pct"] = (h["close"] / h["close"].shift(168) - 1) * 100
    f["ret_24h_pct"] = (h["close"] / h["close"].shift(24) - 1) * 100
    f["dist_sma7d_pct"] = (h["close"] / h["close"].rolling(168).mean() - 1) * 100
    f["efficiency_7d"] = ((h["close"] - h["close"].shift(168)).abs()
                          / h["close"].diff().abs().rolling(168).sum())
    # поток и деривативы — единственные, что пережили контроль по волатильности
    if "taker_buy_volume" in h and "volume" in h:
        tb = h["taker_buy_volume"] / h["volume"].replace(0, np.nan)
        f["taker_buy_7d"] = tb.rolling(168).mean()
    if "quote_volume" in h:
        f["vol_ratio_6h_7d"] = (h["quote_volume"].rolling(6).sum()
                                / (h["quote_volume"].rolling(168).sum() / 28))
    if "funding_rate" in h:
        f["funding_7d"] = h["funding_rate"].rolling(168).mean() * 100
        f["funding_chg_24h"] = (h["funding_rate"]
                                - h["funding_rate"].shift(24)) * 100
    if "open_interest" in h:
        f["oi_vs_30d"] = h["open_interest"] / h["open_interest"].rolling(720).mean()
        f["oi_chg_24h_pct"] = (h["open_interest"]
                               / h["open_interest"].shift(24) - 1) * 100
    # календарь: NFP — единственный сигнал, побивший случайный контроль
    idx = h.index
    days = pd.DatetimeIndex(sorted(set(idx.normalize())))
    nfp = set()
    for (_y, _m), g in pd.Series(days).groupby([days.year, days.month]):
        fri = g[g.dt.weekday == 4]
        if len(fri):
            nfp.add(fri.iloc[0])
    f["nfp_window"] = [1 if (t.normalize() in nfp and 13 <= t.hour < 20) else 0
                       for t in idx]
    return f


# ---------------------------------------------------------------- эпизоды

def episodes(close: pd.Series) -> pd.DataFrame:
    """Зигзаг: помечает, находимся ли мы внутри затяжного роста/просадки,
    сколько он длится и насколько прошёл. Только назад-смотрящее."""
    p = close.to_numpy()
    n = len(p)
    state = np.zeros(n, dtype=np.int8)     # +1 рост, -1 просадка, 0 нет
    age = np.zeros(n, dtype=np.int32)      # часов от начала эпизода
    gain = np.zeros(n)                     # % от точки старта
    anchor_lo = anchor_hi = p[0]
    lo_i = hi_i = 0
    cur = 0
    start_i = 0
    for i in range(n):
        if p[i] < anchor_lo:
            anchor_lo, lo_i = p[i], i
        if p[i] > anchor_hi:
            anchor_hi, hi_i = p[i], i
        up = (p[i] / anchor_lo - 1) * 100
        dn = (1 - p[i] / anchor_hi) * 100
        if cur == 0:
            if up >= RALLY_MIN:
                cur, start_i = 1, lo_i
                anchor_hi, hi_i = p[i], i
            elif dn >= RALLY_MIN:
                cur, start_i = -1, hi_i
                anchor_lo, lo_i = p[i], i
        elif cur == 1:
            if (1 - p[i] / anchor_hi) * 100 >= RETRACE:
                cur = 0
                anchor_lo, lo_i = p[i], i
        else:
            if (p[i] / anchor_lo - 1) * 100 >= RETRACE:
                cur = 0
                anchor_hi, hi_i = p[i], i
        state[i] = cur
        if cur != 0:
            age[i] = i - start_i
            gain[i] = (p[i] / p[start_i] - 1) * 100
    return pd.DataFrame({"episode": state, "episode_age_h": age,
                         "episode_move_pct": gain}, index=close.index)


# ---------------------------------------------------------------- запись

def build(tail_only: bool) -> int:
    h = load_history()
    f = features(h)
    e = episodes(h["close"])
    df = f.join(e).dropna(subset=["vol_7d"])
    seen = set()
    if OUT.exists():
        with OUT.open() as fh:
            for line in fh:
                try:
                    seen.add(json.loads(line)["ts"])
                except (ValueError, KeyError):
                    continue
    if tail_only and seen:
        df = df[df.index > pd.Timestamp(max(seen))]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with OUT.open("a") as fh:
        for ts, row in df.iterrows():
            key = ts.isoformat()
            if key in seen:
                continue
            rec = {"ts": key, "schema": SCHEMA}
            for k, v in row.items():
                rec[k] = (None if (isinstance(v, float) and not np.isfinite(v))
                          else (float(v) if isinstance(v, (int, float, np.floating,
                                                           np.integer)) else v))
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    return written


# ---------------------------------------------------------------- отчёт

def report(days_min: int) -> None:
    if not OUT.exists():
        raise SystemExit("нет state/shadow_regime.jsonl — запусти --backfill")
    d = pd.read_json(OUT, lines=True)
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    d = d.sort_values("ts").set_index("ts")
    print(f"строк: {len(d):,}   {d.index[0]:%d.%m.%Y} → {d.index[-1]:%d.%m.%Y}")

    p = d["price"].to_numpy()
    n = len(p)
    up7 = np.full(n, np.nan)
    for i in range(n - 168):
        up7[i] = (p[i + 1:i + 169].max() / p[i] - 1) * 100
    tgt = up7 >= RALLY_MIN
    ok = np.isfinite(up7)
    base = tgt[ok].mean()
    print(f"база «рост >= {RALLY_MIN}% за 7д»: {base*100:.1f}%\n")

    skip = {"price", "episode", "episode_age_h", "episode_move_pct", "schema"}
    rows = []
    for c in d.columns:
        if c in skip:
            continue
        v = pd.to_numeric(d[c], errors="coerce").to_numpy(float)
        g = ok & np.isfinite(v)
        if g.sum() < 500:
            continue
        x, y = v[g], tgt[g]
        u = np.unique(x)
        sel = (x > u[0]) if len(u) <= 2 else (x >= np.quantile(x, 0.80))
        if sel.sum() < 50:
            continue
        rows.append((c, y[sel].mean() / base, y[sel].mean() * 100, int(sel.sum())))
    rows.sort(key=lambda z: -abs(z[1] - 1))
    print(f"{'признак':24s} {'верх.20%':>10s} {'ЛИФТ':>7s} {'n':>7s}")
    for c, lift, hit, k in rows:
        print(f"{c:24s} {hit:9.1f}% {lift:7.2f} {k:7d}")

    print("\nЭПИЗОДЫ (зигзаг >= "
          f"{RALLY_MIN}% с откатом {RETRACE}%)")
    for lbl, val in (("затяжной рост", 1), ("затяжная просадка", -1),
                     ("без эпизода", 0)):
        m = d["episode"] == val
        if not m.any():
            continue
        print(f"  {lbl:20s} {m.mean()*100:5.1f}% времени", end="")
        if val:
            g = d.loc[m, "episode_move_pct"].abs()
            a = d.loc[m, "episode_age_h"]
            print(f"   ход медиана {g.median():5.1f}% макс {g.max():5.1f}%"
                  f"   длительность медиана {a.median()/24:4.1f}д "
                  f"макс {a.max()/24:4.1f}д")
        else:
            print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--days-min", type=int, default=7)
    a = ap.parse_args()
    if a.backfill or a.tick:
        k = build(tail_only=a.tick)
        print(f"записано строк: {k:,}   всего в файле: "
              f"{sum(1 for _ in OUT.open()) if OUT.exists() else 0:,}")
    if a.report or not (a.backfill or a.tick):
        report(a.days_min)
    return 0


if __name__ == "__main__":
    sys.exit(main())
