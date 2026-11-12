"""Закрытые часовые свечи для расчёта сигналов: кэш CSV + дозагрузка из источника.

Источник по умолчанию — Binance spot BTCUSDT (публичный, без ключа): на нём проверены система (536/536 с Pine) и 432.
Линии считаются по ≥20 000 часам (≈833 дня) — с меньшей историей события последнего года расходятся (ранг за год,
TEMA200), см. research/sigexec_20261112/NOTES.md. Только закрытые часы; разрыв или битая свеча — данные несвежие."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

H1 = 3600
MIN_HOURS = 20000
KEEP_HOURS = 26000


class FeedError(RuntimeError):
    pass


def _get_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": "bot7-sigexec/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class BinanceSpotHours:
    """GET /api/v3/klines interval=1h — до 1000 свечей за запрос. Строка: [open_ms, o, h, l, c, v, close_ms, ...]."""

    URL = "https://api.binance.com/api/v3/klines"
    name = "binance-spot"

    def __init__(self, symbol: str = "BTCUSDT", getter=_get_json):
        self.symbol, self.get = symbol, getter

    def fetch(self, start_close_t: int, now: float) -> list[tuple[int, float, float, float, float]]:
        """Закрытые часы с временем закрытия ≥ start_close_t: (t закрытия, o, h, l, c)."""
        out, start_ms = [], (start_close_t - H1) * 1000
        while True:
            q = urllib.parse.urlencode({"symbol": self.symbol, "interval": "1h", "startTime": start_ms, "limit": 1000})
            rows = self.get(f"{self.URL}?{q}")
            if not isinstance(rows, list):
                raise FeedError(f"binance klines: не список ({str(rows)[:120]})")
            got = 0
            for r in rows:
                t_close = int(r[0]) // 1000 + H1
                if t_close > now:                          # час ещё не закрыт
                    continue
                out.append((t_close, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
                got += 1
            if len(rows) < 1000:
                return out
            start_ms = int(rows[-1][0]) + H1 * 1000
            if got == 0:
                return out


class HourFeed:
    def __init__(self, cache: Path, source, keep: int = KEEP_HOURS):
        self.cache, self.src, self.keep = Path(cache), source, keep
        self.gaps: list[tuple[int, int]] = []
        self.t = np.zeros(0, np.int64)
        self.ohlc = np.zeros((0, 4))
        if self.cache.exists():
            d = np.loadtxt(self.cache, delimiter=",", skiprows=1, ndmin=2)
            if len(d):
                self.t, self.ohlc = d[:, 0].astype(np.int64), d[:, 1:5]

    def _save(self) -> None:
        tmp = self.cache.with_suffix(".tmp")
        rows = np.c_[self.t, self.ohlc]
        np.savetxt(tmp, rows, delimiter=",", header="t_close,o,h,l,c", comments="", fmt=["%d", "%.8g", "%.8g", "%.8g", "%.8g"])
        tmp.replace(self.cache)

    def update(self, now: float | None = None) -> int:
        """Дозагрузить закрытые часы. → сколько новых. Ошибка источника — FeedError (данные остаются прежними)."""
        now = time.time() if now is None else now
        start = int(self.t[-1]) + H1 if len(self.t) else (int(now) // H1 * H1 - self.keep * H1)
        if start > now:
            return 0
        try:
            rows = self.src.fetch(start, now)
        except FeedError:
            raise
        except Exception as e:  # noqa: BLE001
            raise FeedError(f"{self.src.name}: {e!r}") from None
        rows = [r for r in rows if not len(self.t) or r[0] > self.t[-1]]
        # разбор aadc2a4: пропущенный час не дописывается молча. Свежая дыра (час закрыт меньше 3 ч назад) — ждём, пока
        # источник отдаст час, и не пишем свечи после дыры; старая дыра — настоящий простой биржи, пишется с пометкой
        prev = int(self.t[-1]) if len(self.t) else None
        keep = []
        for r in rows:
            if prev is not None and r[0] - prev > H1:
                if now - (prev + H1) < 3 * H1:
                    break
                self.gaps.append((prev + H1, r[0] - H1))
            keep.append(r)
            prev = r[0]
        rows = keep
        if not rows:
            return 0
        t = np.array([r[0] for r in rows], np.int64)
        x = np.array([r[1:] for r in rows], float)
        if (np.diff(np.r_[self.t[-1:], t]) <= 0).any() or not np.isfinite(x).all() or (x <= 0).any() or (x[:, 1] < x[:, 2]).any():
            raise FeedError("свечи не по порядку или битые цены — не дописываю")
        self.t, self.ohlc = np.r_[self.t, t][-self.keep:], np.r_[self.ohlc, x][-self.keep:]
        self._save()
        return len(rows)

    def fresh(self, now: float | None = None) -> bool:
        """Последний закрытый час на месте (с запасом 15 мин на задержку источника) и истории хватает."""
        now = time.time() if now is None else now
        if len(self.t) < MIN_HOURS or int(self.t[-1]) < (int(now) - 900) // H1 * H1:
            return False
        recent = self.t[-49:]                           # последние двое суток без дыр — иначе решение по неполным 4ч
        return bool((np.diff(recent) == H1).all())

    def arrays(self):
        return self.t, self.ohlc[:, 0], self.ohlc[:, 1], self.ohlc[:, 2], self.ohlc[:, 3]
