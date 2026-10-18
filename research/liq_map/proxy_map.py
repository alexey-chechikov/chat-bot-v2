"""Наша карта ликвидаций из публичных данных Binance (18.10, вопрос оператора «неужели мы не можем использовать
тепловую карту»). Шаг 1 — сверка с его скринами CoinGlass 14.10 и 18.10: совпадают ли яркие полосы.

Модель (закреплена до сверки, параметры не подбираются по скринам):
  - каждый прирост OI на 5-мин баре = новые позиции ОБЕИХ сторон (у каждого контракта есть лонг и шорт) по close бара;
  - распределение плеча: 10× 40%, 25× 30%, 50× 20%, 100× 10%; поддерживающая маржа 0.5%;
    ликвидация лонга p·(1 − 1/L + 0.005), шорта p·(1 + 1/L − 0.005);
  - уменьшение OI — пропорциональное закрытие всех живых когорт;
  - полоса снимается, когда цена её прошла (low ≤ уровень лонга / high ≥ уровень шорта);
  - интенсивность — сумма BTC в корзине $100 × цена.
Это наша модель-заменитель, не CoinGlass Model1 (её формула не опубликована).

    .venv/bin/python3 research/liq_map/proxy_map.py 2026-10-18T22:00 2026-10-14T23:00
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

SYM = "BTCUSDT"
LEV = ((10, .4), (25, .3), (50, .2), (100, .1))
MM = 0.005
BIN = 100.0
WARM_DAYS = 14


def get(url):
    for k in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                                     timeout=20).read())
        except Exception:                                       # noqa: BLE001
            if k == 3:
                raise
            time.sleep(2 ** k)


def oi_5m(a_ms, b_ms):
    out, t = {}, a_ms
    while t < b_ms:
        rows = get(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={SYM}&period=5m&limit=500"
                   f"&startTime={t}&endTime={min(b_ms, t + 500 * 300_000)}")
        for r in rows:
            out[int(r["timestamp"])] = float(r["sumOpenInterest"])
        t += 500 * 300_000
        time.sleep(0.3)
    return out


def klines_5m(a_ms, b_ms):
    out, t = {}, a_ms
    while t < b_ms:
        rows = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={SYM}&interval=5m&limit=1500&startTime={t}"
                   f"&endTime={b_ms}")
        if not rows:
            break
        for r in rows:
            out[int(r[0])] = (float(r[2]), float(r[3]), float(r[4]))      # high, low, close
        t = int(rows[-1][0]) + 300_000
        time.sleep(0.3)
    return out


def build(at: datetime):
    b = int(at.timestamp() * 1000)
    a = int((at - timedelta(days=WARM_DAYS)).timestamp() * 1000)
    oi, kl = oi_5m(a, b), klines_5m(a, b)
    longs: dict[float, float] = {}                               # уровень ликвидации лонгов → BTC
    shorts: dict[float, float] = {}
    prev = None
    for t in sorted(kl):
        h, l, c = kl[t]
        # цена прошла уровень — полоса ликвидирована
        for lvl in [x for x in longs if l <= x]:
            del longs[lvl]
        for lvl in [x for x in shorts if h >= x]:
            del shorts[lvl]
        o = oi.get(t + 300_000) or oi.get(t)                     # OI на конце бара (метка — граница периода)
        if o is None:
            continue
        if prev is not None:
            d = o - prev
            if d > 0:
                for lev, w in LEV:
                    ll = round(c * (1 - 1 / lev + MM) / BIN) * BIN
                    sl = round(c * (1 + 1 / lev - MM) / BIN) * BIN
                    longs[ll] = longs.get(ll, 0) + d * w
                    shorts[sl] = shorts.get(sl, 0) + d * w
            elif d < 0:
                tot = sum(longs.values()) + 1e-12
                k = max(0.0, 1 + d / tot)
                longs = {x: v * k for x, v in longs.items()}
                shorts = {x: v * k for x, v in shorts.items()}
        prev = o
    price = kl[max(kl)][2]
    return price, longs, shorts


def show(at: datetime):
    price, longs, shorts = build(at)
    up = sorted(((lv, v * lv) for lv, v in shorts.items() if lv > price), key=lambda x: -x[1])[:6]
    dn = sorted(((lv, v * lv) for lv, v in longs.items() if lv < price), key=lambda x: -x[1])[:6]
    print(f"{at:%Y-%m-%d %H:%M} UTC цена {price:,.0f}")
    print("  сверху (шорты, $M):", ", ".join(f"{lv:,.0f}:{v / 1e6:.0f}" for lv, v in sorted(up)))
    print("  снизу  (лонги, $M):", ", ".join(f"{lv:,.0f}:{v / 1e6:.0f}" for lv, v in sorted(dn, reverse=True)))


if __name__ == "__main__":
    for s in sys.argv[1:]:
        show(datetime.fromisoformat(s).replace(tzinfo=timezone.utc))
