"""Аддендум GPT 13.10, B3: research/weex/fetch_1m.py не пишет ещё не закрытую минуту (явный endTime по времени
сервера, close_time < server_now) и при продолжении перекачивает и перезаписывает последнюю записанную минуту.
Binance поддельный, часы мака нарочно впереди сервера на 5 минут — граница берётся по серверу."""
from __future__ import annotations

import csv
import io
import json
import types
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from tests.research_tools._util import load_defs

MIN = 60_000
BASE = int(datetime(2025, 12, 11, tzinfo=timezone.utc).timestamp() * 1000)    # = START скрипта
SYM = "FAKEUSDT"


class FakeBinance:
    """/time и /klines. Минута, не закрытая к `now`, отдаётся с промежуточными high/low/close (как настоящий)."""

    FINAL = {BASE: (100, 110, 98, 102), BASE + MIN: (102, 104, 101, 103), BASE + 2 * MIN: (103, 105, 102, 104)}
    PARTIAL = {BASE: (100, 105, 99, 101), BASE + MIN: (102, 103, 101, 102.5), BASE + 2 * MIN: (103, 104, 102, 103.5)}

    def __init__(self, honor_end: bool = True):
        self.now = BASE
        self.honor_end = honor_end
        self.kline_urls: list[str] = []

    def urlopen(self, url, timeout=30):
        u = urlparse(url)
        q = parse_qs(u.query)
        if u.path.endswith("/time"):
            return io.BytesIO(json.dumps({"serverTime": self.now}).encode())
        self.kline_urls.append(url)
        start = int(q["startTime"][0])
        end = int(q["endTime"][0]) if ("endTime" in q and self.honor_end) else None
        out = []
        for t in sorted(self.FINAL):
            if t < start or t > self.now or (end is not None and t > end):
                continue
            o, h, l, c = self.FINAL[t] if t + MIN - 1 < self.now else self.PARTIAL[t]
            out.append([t, str(o), str(h), str(l), str(c), "1", t + MIN - 1, "0", 1, "0", "0", "0"])
        return io.BytesIO(json.dumps(out[: int(q.get("limit", ["1000"])[0])]).encode())


def _script(tmp_path, srv: FakeBinance) -> dict:
    mac_clock = types.SimpleNamespace(time=lambda: srv.now / 1000 + 300, sleep=lambda s: None)
    fake_urllib = types.SimpleNamespace(request=types.SimpleNamespace(urlopen=srv.urlopen))
    return load_defs("research/weex/fetch_1m.py", DATA=tmp_path, urllib=fake_urllib, time=mac_clock)


def _rows(tmp_path) -> list[tuple[int, float]]:
    path = tmp_path / f"{SYM}_1m.csv"
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return [(int(r[0]), float(r[4])) for r in list(csv.reader(f))[1:]]


def test_open_minute_not_written(tmp_path):
    srv = FakeBinance()
    ns = _script(tmp_path, srv)
    srv.now = BASE + 30_000                                   # минута BASE ещё идёт
    ns["fetch"](SYM)
    assert _rows(tmp_path) == [], "записана незакрытая минута"
    srv.now = BASE + 90_000                                   # BASE закрыта (close 102), BASE+1 мин идёт
    ns["fetch"](SYM)
    assert _rows(tmp_path) == [(BASE, 102.0)]


def test_explicit_end_time_is_last_closed_minute(tmp_path):
    srv = FakeBinance()
    ns = _script(tmp_path, srv)
    srv.now = BASE + 90_000
    ns["fetch"](SYM)
    assert srv.kline_urls, "klines не запрашивались"
    assert all(parse_qs(urlparse(u).query).get("endTime") == [str(BASE)] for u in srv.kline_urls)


def test_close_time_checked_even_if_server_returns_open_bar(tmp_path):
    srv = FakeBinance(honor_end=False)                        # сервер проигнорировал endTime
    ns = _script(tmp_path, srv)
    srv.now = BASE + MIN + 30_000
    ns["fetch"](SYM)
    assert _rows(tmp_path) == [(BASE, 102.0)]


def test_stale_last_bar_refetched_and_overwritten(tmp_path):
    srv = FakeBinance()
    ns = _script(tmp_path, srv)
    (tmp_path / f"{SYM}_1m.csv").write_bytes(b"ts,open,high,low,close\r\n" + f"{BASE},100,105,99,101\r\n".encode())
    srv.now = BASE + 2 * MIN + 30_000                         # BASE и BASE+1 закрыты, BASE+2 идёт
    ns["fetch"](SYM)
    assert _rows(tmp_path) == [(BASE, 102.0), (BASE + MIN, 103.0)], "устаревшая последняя минута не исправлена"
    srv.now = BASE + 3 * MIN + 1
    ns["fetch"](SYM)                                          # повтор: закрытые не меняются, без дублей и дыр
    assert _rows(tmp_path) == [(BASE, 102.0), (BASE + MIN, 103.0), (BASE + 2 * MIN, 104.0)]
