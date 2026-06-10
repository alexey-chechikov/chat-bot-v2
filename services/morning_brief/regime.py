"""BTC 4h режим: цена vs красная TEMA200 (price-gate) + vol-z. Источник истины.

Логика валидирована Win grid-$ (band ±0.3%, hold 2 бара); сюда вынесена из
scripts/morning_briefing.py, скрипт импортирует отсюда. Публичные свечи:
Bybit (3 попытки) → фоллбэк BitMEX 1h→4h (интермиттент-баг 04:00 2026-06-10
«list index out of range» — пустой ответ Bybit ронял секцию РЫНОК).
"""
from __future__ import annotations

import json
import time
import urllib.request

BAND = 0.3  # price-gate %, валидировано Win grid-$
RECLAIM_PCT = 1.0  # закрытие шорта при реклейме красной +1% (handoff 2026-06-08)
MIN_BARS = 210  # TEMA200 на 4h — меньше нельзя


def _ema(xs: list[float], n: int) -> list[float]:
    a = 2.0 / (n + 1)
    e = xs[0]
    out = [e]
    for x in xs[1:]:
        e = x * a + e * (1 - a)
        out.append(e)
    return out


def _bybit_4h() -> tuple[list[float], list[float], list[float]]:
    from market_collector.ohlcv import _fetch_klines
    raw = _fetch_klines("240", 250)  # 4h, descending [ts,o,h,l,c,v,...]
    if len(raw) < MIN_BARS:
        raise ValueError(f"bybit вернул {len(raw)} баров (< {MIN_BARS})")
    c = [float(x[4]) for x in raw][::-1]
    h = [float(x[2]) for x in raw][::-1]
    lo = [float(x[3]) for x in raw][::-1]
    return h, lo, c


def _bitmex_4h(n4h: int = 250) -> tuple[list[float], list[float], list[float]]:
    """Фоллбэк: BitMEX 1h → ресемпл в 4h (binSize=4h BitMEX не поддерживает)."""
    n1h = n4h * 4 + 8
    url = ("https://www.bitmex.com/api/v1/trade/bucketed?binSize=1h&partial=false"
           f"&symbol=XBTUSDT&count={n1h}&reverse=true")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    rows = json.load(urllib.request.urlopen(req, timeout=20))[::-1]
    buckets: dict[tuple[str, int], list[dict]] = {}
    for r in rows:
        ts = r.get("timestamp", "")
        try:
            hour = int(ts[11:13])
            key_day = ts[:10]
        except (ValueError, IndexError):
            continue
        buckets.setdefault((key_day, hour // 4), []).append(r)
    h: list[float] = []
    lo: list[float] = []
    c: list[float] = []
    ordered = sorted(buckets.values(), key=lambda b: b[0]["timestamp"])
    if ordered and len(ordered[-1]) < 4:
        ordered = ordered[:-1]  # незакрытый 4h-бакет не считаем
    for b in ordered:
        h.append(max(float(x["high"]) for x in b))
        lo.append(min(float(x["low"]) for x in b))
        c.append(float(b[-1]["close"]))
    if len(c) < MIN_BARS:
        raise ValueError(f"bitmex дал {len(c)} 4h-баров (< {MIN_BARS})")
    return h, lo, c


def _fetch_4h() -> tuple[list[float], list[float], list[float]]:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            return _bybit_4h()
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(3)
    try:
        return _bitmex_4h()
    except Exception as e:
        raise RuntimeError(f"bybit: {last_err}; bitmex fallback: {e}") from e


def regime() -> dict:
    h, lo, c = _fetch_4h()
    e1 = _ema(c, 200); e2 = _ema(e1, 200); e3 = _ema(e2, 200)
    t200 = 3 * e1[-1] - 3 * e2[-1] + e3[-1]
    px = c[-1]
    above = (px - t200) / t200 * 100.0
    zone = "LONG-зона" if above > BAND else "SHORT-зона" if above < -BAND else "FLAT (у красной)"
    tr = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) / c[i] * 100.0
          for i in range(1, len(c))]
    atr = [tr[0]]
    for x in tr[1:]:
        atr.append((atr[-1] * 13 + x) / 14)
    win = atr[-100:]
    mean = sum(win) / len(win)
    sd = (sum((x - mean) ** 2 for x in win) / len(win)) ** 0.5
    z = (atr[-1] - mean) / sd if sd else 0.0
    return dict(px=px, t200=t200, above=above, zone=zone, atr=atr[-1], z=z, voloff=z >= 2.5)


def close_level(side: str, t200: float) -> float:
    """Уровень закрытия по режиму: шорт — реклейм красной +1%, лонг — пробой −1%."""
    if side == "short":
        return t200 * (1 + RECLAIM_PCT / 100.0)
    return t200 * (1 - RECLAIM_PCT / 100.0)


def verdict(side: str, zone: str, voloff: bool) -> str:
    if voloff:
        return "⚫ VOL-OFF спайк — оцени: краш? фикс профит / хедж"
    if "FLAT" in zone:
        return "🟡 FLAT — обе ноги доят чоп, держать"
    fav = (side == "short" and "SHORT" in zone) or (side == "long" and "LONG" in zone)
    return "🟢 в зоне — держать/доить" if fav else "🔴 ПРОТИВ режима — присмотреть / брать профит (будет бажить)"


def border_flag(side: str, px: float, border: tuple) -> str:
    bot, top = border
    if not bot or not top:
        return ""
    pos = (px - bot) / (top - bot)  # 0=у дна, 1=у верха
    if side == "short" and pos > 0.8:
        return " ⚠️у TOP (мешок к максимуму)"
    if side == "long" and pos < 0.2:
        return " ⚠️у BOTTOM (мешок к максимуму)"
    return f" (в border {pos*100:.0f}%)"
