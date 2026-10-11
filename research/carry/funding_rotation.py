"""Фандинг на альтах WEEX (10.10): «спот-лонг + шорт перпа» с перекладыванием в монеты с высоким фандингом.
Продолжение research/carry/carry_check.py (06.10: BTC/ETH/XRP держать всегда ≈5%/год валом, 2026 — 2–3%).

Данные — история фандинга WEEX (8ч) за 365 суток. Издержки пакета 0.30% за полный круг (спот 0.10% +
перп 0.05% за сторону). Варианты:
  держать монету весь год;
  ротация: раз в сутки держать TOP_N монет с наибольшим средним фандингом за прошлые 3 суток (только >0),
  смена монеты = полный круг. Решение — по прошлым данным, фандинг — следующих суток.
Результат в % к объёму позиции за год; на капитал меньше (спот + маржа под шорт ≈ ×1.33).
Разрез по времени: первая/вторая половина года."""
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")
DATA.mkdir(exist_ok=True)
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "BNBUSDT",
         "LTCUSDT", "TRXUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT", "NEARUSDT", "AAVEUSDT", "UNIUSDT", "APTUSDT",
         "INJUSDT", "TONUSDT", "WIFUSDT", "ORDIUSDT"]
ROUND = 0.30          # % за полный круг пакета
TOP_N = 3


def history(sym: str) -> pd.Series:
    p = DATA / f"{sym}_funding.json"
    if not p.exists():
        end = int(time.time() * 1000)
        start = end - 366 * 86_400_000
        rows = []
        week = 7 * 86_400_000 - 1                              # WEEX: окно не длиннее 7 суток
        a = start
        while a < end:
            b = min(a + week, end)
            url = (f"https://api-contract.weex.com/capi/v3/market/fundingRate?symbol={sym}&startTime={a}"
                   f"&endTime={b}&limit=1000")
            for k in range(4):
                try:
                    rows += json.loads(urllib.request.urlopen(url, timeout=30).read())
                    break
                except Exception:                           # noqa: BLE001
                    time.sleep(1 + 2 * k)
            a = b + 1
            time.sleep(0.12)
        p.write_text(json.dumps(rows))
    rows = json.loads(p.read_text())
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({pd.to_datetime(int(r["fundingTime"]), unit="ms", utc=True): float(r["fundingRate"]) * 100
                   for r in rows}).sort_index()
    return s[~s.index.duplicated()]


def main():
    fr = {}
    for sym in COINS:
        try:
            s = history(sym)
            if len(s) > 300:
                fr[sym] = s
        except Exception as exc:                            # noqa: BLE001
            print(sym, "нет данных:", str(exc)[:60])
    df = pd.DataFrame(fr).sort_index()
    df = df[df.index >= df.index[-1] - pd.Timedelta(days=365)]
    days = (df.index[-1] - df.index[0]).days or 1
    mid = df.index[0] + (df.index[-1] - df.index[0]) / 2
    print(f"WEEX фандинг {df.index[0]:%Y-%m-%d} … {df.index[-1]:%Y-%m-%d} ({days} сут), монет {df.shape[1]}")
    print(f"{'монета':<10} {'%/год':>7} {'1-я пол':>8} {'2-я пол':>8} {'плюсовых':>9} {'худшие 30 сут':>14}")
    rows = []
    for sym in df.columns:
        s = df[sym].dropna()
        ann = s.sum() * 365 / days
        h1 = s[s.index < mid].sum() * 365 / (days / 2)
        h2 = s[s.index >= mid].sum() * 365 / (days / 2)
        w30 = s.rolling(90).sum().min()
        rows.append((sym, ann, h1, h2, (s > 0).mean(), w30))
    for sym, ann, h1, h2, pos, w30 in sorted(rows, key=lambda r: -r[1]):
        print(f"{sym:<10} {ann:>+7.1f} {h1:>+8.1f} {h2:>+8.1f} {pos:>9.0%} {w30:>+13.2f}%")

    # ротация раз в сутки по прошлым 3 суткам
    daily = df.resample("1D").sum(min_count=1)
    trail = daily.rolling(3, min_periods=3).mean().shift(1)            # знание только прошлого
    held: set = set()
    net, gross, switches = [], 0.0, 0
    for day in daily.index:
        if day not in trail.index or trail.loc[day].isna().all():
            continue
        cand = trail.loc[day].dropna()
        cand = cand[cand > 0].sort_values(ascending=False).head(TOP_N)
        new = set(cand.index)
        cost = len(new ^ held) / 2 * ROUND / TOP_N if held else len(new) * ROUND / 2 / TOP_N
        switches += len(new - held)
        held = new
        inc = daily.loc[day, list(held)].fillna(0).mean() if held else 0.0
        gross += inc
        net.append((day, inc - cost))
    ns = pd.Series(dict(net))
    ann = ns.sum() * 365 / days
    h1 = ns[ns.index < mid].sum() * 365 / (days / 2)
    h2 = ns[ns.index >= mid].sum() * 365 / (days / 2)
    print(f"\nРОТАЦИЯ топ-{TOP_N} по фандингу прошлых 3 суток (раз в сутки), издержки {ROUND}% за круг:")
    print(f"  валовый фандинг {gross * 365 / days:+.1f}%/год, после издержек {ann:+.1f}%/год к объёму "
          f"({ann / 1.33:+.1f}% к капиталу); 1-я половина {h1:+.1f}%, 2-я {h2:+.1f}%; новых входов {switches}")
    print(f"  худшие 30 суток: {ns.rolling(30).sum().min():+.2f}%; дней в минусе {(ns < 0).mean():.0%}")


if __name__ == "__main__":
    main()
