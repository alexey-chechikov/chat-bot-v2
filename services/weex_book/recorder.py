"""Запись стакана и сделок WEEX (публичный websocket) — данные для замера maker-бота на объём.

Зачем (11.10, разбор GPT docs/WEEX_GPT_VOLUME_VARIANTS_2026-10-11.md): прежде чем ставить хоть один maker-ордер,
измерить цену оборота — как часто заявка у лучшей цены исполняется с учётом очереди и куда идёт цена после
исполнения (markout 1/5/30/60 с). Ордеров служба не ставит, ключи не использует.

Поток wss://ws-contract.weex.com/v3/ws/public: <SYM>@depth15 (снимок при подписке, дальше изменения раз в
~0.5 с; U нового сообщения = u предыдущего — иначе пропуск, пересинхронизация) и <SYM>@trade (сделки тейкеров,
m=true — агрессивная продажа). Пишем:
  state/weex_book/<SYM>_<YYYYMMDD>_book.csv   — E, 3 уровня bid (цена, объём), 3 уровня ask — при изменении;
  state/weex_book/<SYM>_<YYYYMMDD>_trades.csv — T, E, цена, объём, m.
Хранение 10 суток (~70 МБ/сутки на две монеты). Лимиты WEEX: 300 подключений/5 мин/IP, 240 подписок/час/соединение — переподключение с
паузой, пересинхронизация не чаще раза в 30 с на символ (иначе переподключение)."""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "state" / "weex_book"
URL = "wss://ws-contract.weex.com/v3/ws/public"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
LEVELS = 3
KEEP_DAYS = 10
SILENCE_SEC = 30


class Book:
    """Стакан по снимку и изменениям; ok=False — был пропуск, нужен новый снимок."""

    def __init__(self):
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.last_u: int | None = None
        self.ok = False

    def snapshot(self, msg: dict) -> None:
        self.bids = {float(p): float(q) for p, q in msg.get("b", []) if float(q) > 0}
        self.asks = {float(p): float(q) for p, q in msg.get("a", []) if float(q) > 0}
        self.last_u = int(msg["u"])
        self.ok = True

    def change(self, msg: dict) -> bool:
        if not self.ok or self.last_u is None or int(msg["U"]) != self.last_u:
            self.ok = False
            return False
        for side, rows in ((self.bids, msg.get("b", [])), (self.asks, msg.get("a", []))):
            for p, q in rows:
                p, q = float(p), float(q)
                if q > 0:
                    side[p] = q
                else:
                    side.pop(p, None)
        self.last_u = int(msg["u"])
        return True

    def top(self, n: int = LEVELS) -> tuple:
        b = sorted(self.bids.items(), reverse=True)[:n]
        a = sorted(self.asks.items())[:n]
        b += [(0.0, 0.0)] * (n - len(b))
        a += [(0.0, 0.0)] * (n - len(a))
        return tuple(x for lvl in b for x in lvl) + tuple(x for lvl in a for x in lvl)


class Writer:
    """CSV по символу и UTC-дню; стакан пишется только при изменении верхних уровней."""

    def __init__(self, data: Path | None = None):
        self.data = data or DATA
        self.data.mkdir(parents=True, exist_ok=True)
        self.files: dict[tuple, tuple] = {}
        self.last_top: dict[str, tuple] = {}

    def _w(self, sym: str, kind: str, header: list[str], ts_ms: int):
        day = datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y%m%d")
        key = (sym, kind)
        cur = self.files.get(key)
        if cur and cur[0] == day:
            return cur[2]
        if cur:
            cur[1].close()
        path = self.data / f"{sym}_{day}_{kind}.csv"
        new = not path.exists()
        f = path.open("a", newline="", encoding="utf-8")
        w = csv.writer(f)
        if new:
            w.writerow(header)
        self.files[key] = (day, f, w)
        self._prune()
        return w

    def book(self, sym: str, ts_ms: int, top: tuple) -> None:
        if self.last_top.get(sym) == top:
            return
        self.last_top[sym] = top
        hdr = ["E"] + [f"{s}{i}{k}" for s in ("b", "a") for i in range(1, LEVELS + 1) for k in ("", "q")]
        self._w(sym, "book", hdr, ts_ms).writerow([ts_ms, *top])

    def trade(self, sym: str, t: dict, ev_ms: int) -> None:
        self._w(sym, "trades", ["T", "E", "p", "q", "m"], int(t["T"])).writerow(
            [int(t["T"]), ev_ms, t["p"], t["q"], int(bool(t.get("m")))])

    def flush(self) -> None:
        for _, f, _ in self.files.values():
            f.flush()

    def close(self) -> None:
        for _, f, _ in self.files.values():
            f.close()
        self.files.clear()

    def _prune(self) -> None:
        cutoff = time.time() - KEEP_DAYS * 86400
        for p in self.data.glob("*_*_*.csv"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass


async def _session(ws, symbols, writer: Writer, stop_event: asyncio.Event) -> None:
    books = {s: Book() for s in symbols}
    seen: dict[str, deque] = {s: deque(maxlen=5000) for s in symbols}
    seen_set: dict[str, set] = {s: set() for s in symbols}
    last_resync = {s: 0.0 for s in symbols}                 # последняя переподписка из-за пропуска
    asked = {s: time.time() for s in symbols}               # с какого момента ждём снимок
    waiting = {s: True for s in symbols}                    # ждём снимок (первый или после переподписки)
    params = [f"{s}@depth15" for s in symbols] + [f"{s}@trade" for s in symbols]
    await ws.send(json.dumps({"method": "SUBSCRIBE", "params": params, "id": 1}))
    last_flush = time.time()
    while not stop_event.is_set():
        try:
            raw = await asyncio.wait_for(ws.recv(), SILENCE_SEC)
        except asyncio.TimeoutError:
            raise ConnectionError("тишина в потоке")
        msg = json.loads(raw)
        ev = msg.get("e") or msg.get("event")
        if ev == "ping":
            await ws.send(json.dumps({"method": "PONG", "id": 1}))
            continue
        sym = msg.get("s")
        if sym not in books:
            continue
        if ev == "depthSnapshot":
            books[sym].snapshot(msg)
            waiting[sym] = False
            writer.book(sym, int(msg["E"]), books[sym].top())
        elif ev == "depth":
            if books[sym].change(msg):
                writer.book(sym, int(msg["E"]), books[sym].top())
            elif waiting[sym]:                              # до снимка изменения не применяются
                if time.time() - asked[sym] > 30:
                    raise ConnectionError(f"нет снимка стакана {sym}")
            elif time.time() - last_resync[sym] > 30:      # пропуск — новый снимок через переподписку
                last_resync[sym] = asked[sym] = time.time()
                waiting[sym] = True
                logger.warning("weex_book.resync %s", sym)
                ch = f"{sym}@depth15"
                await ws.send(json.dumps({"method": "UNSUBSCRIBE", "params": [ch], "id": 2}))
                await ws.send(json.dumps({"method": "SUBSCRIBE", "params": [ch], "id": 3}))
            else:
                raise ConnectionError(f"частые пропуски стакана {sym}")
        elif ev in ("trade", "tradeSnapshot"):
            for t in msg.get("d", []):
                tid = str(t.get("t"))
                if tid in seen_set[sym]:
                    continue
                if len(seen[sym]) == seen[sym].maxlen:
                    seen_set[sym].discard(seen[sym][0])
                seen[sym].append(tid)
                seen_set[sym].add(tid)
                if ev == "trade":                            # снимок — прошлые сделки, только для дедупа
                    writer.trade(sym, t, int(msg["E"]))
        if time.time() - last_flush > 5:
            writer.flush()
            last_flush = time.time()


async def weex_book_loop(stop_event: asyncio.Event, symbols=SYMBOLS) -> None:
    import websockets
    writer = Writer()
    pause = 5.0
    try:
        while not stop_event.is_set():
            t0 = time.time()
            try:
                async with websockets.connect(URL, additional_headers={"User-Agent": "bot7-book-recorder"},
                                              max_size=2 ** 22, ping_interval=None) as ws:
                    await _session(ws, symbols, writer, stop_event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:                            # noqa: BLE001 — переподключиться
                logger.warning("weex_book.reconnect err=%s", str(exc)[:200])
            writer.flush()
            pause = 5.0 if time.time() - t0 > 300 else min(pause * 2, 300.0)
            try:
                await asyncio.wait_for(stop_event.wait(), pause)
            except asyncio.TimeoutError:
                pass
    finally:
        writer.close()
