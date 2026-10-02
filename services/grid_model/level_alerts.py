"""Сигнал о близком уровне бота: тейк, выход по средней, граница.

Оператор 02.10.2026: «делай» — после того как граница BTC-шорта 86 500 была
задета около 12:00 UTC при утреннем шансе 79% за сутки, а узнать это можно
было только открыв /odds в нужный момент.

Раз в 10 минут: для каждого живого бота уровни из реальных ордеров
(bot_money), шанс коснуться за 4 часа по внутридневной модели (живая сверка
30.09–02.10: обещанное = факт в пределах 1–5 п.п. на 2 112 проверках). Шанс
перешёл порог — одно сообщение на уровень, повтор не чаще cooldown_hours.
Каждый сигнал пишется в журнал, чтобы потом сверить, доходила ли цена.
Ботов служба не трогает.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "state" / "level_alerts_config.json"
STATE = ROOT / "state" / "level_alerts_state.json"
JOURNAL = ROOT / "state" / "level_alerts_journal.jsonl"
DEFAULT = {"enabled": True, "threshold_4h": 0.30, "cooldown_hours": 4.0, "poll_sec": 600}
LEVELS = {"первый тейк", "все тейки", "выход шортов по средней",
          "выход лонгов по средней", "граница"}
SYM = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}


def load_config() -> dict:
    try:
        return {**DEFAULT, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except FileNotFoundError:
        CONFIG.write_text(json.dumps({"_note": __doc__.splitlines()[0], **DEFAULT},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        return dict(DEFAULT)
    except (OSError, ValueError):
        logger.exception("level_alerts.config_failed")
        return dict(DEFAULT)


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def candidates(book, px: float, touch) -> list[dict]:
    """Уровни бота с шансом за 4ч/сутки и деньгами на уровне."""
    from services.grid_model import bot_money as bm

    out = []
    for name, lvl in bm.key_levels(book, px):
        if name not in LEVELS:
            continue
        pct = lvl / px - 1
        o = bm.simulate(book, px, lvl)
        out.append({"name": name, "level": float(lvl), "pct": pct,
                    "p4": touch(pct, "4ч"), "p24": touch(pct, "сутки"),
                    "realized": o.realized, "total": o.total})
    return out


def message(bot_name: str, c: dict) -> str:
    risk = c["name"] == "граница"
    head = "⚠️" if risk else "📣"
    if risk:
        money = f"там итог {c['total']:+,.0f}$, набор остановится"
    elif c["realized"] > 0:
        money = f"забирает {c['realized']:+,.0f}$, итог {c['total']:+,.0f}$"
    else:
        money = f"итог {c['total']:+,.0f}$"
    return (f"{head} {bot_name}: {c['name']} {c['level']:,.0f} ({c['pct']:+.1%}) — "
            f"шанс дойти за 4ч {c['p4']:.0%}, за сутки {c['p24']:.0%}. {money}.")


def due(state: dict, key: str, now: float, cooldown_h: float) -> bool:
    last = state.get(key)
    return last is None or now - float(last) >= cooldown_h * 3600


def tick(send_fn=None, books=None, touch_by_sym=None, prices=None,
         now: float | None = None) -> list[str]:
    """Один проход. Возвращает отправленные тексты (для тестов и журнала)."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return []
    now = now or time.time()
    if books is None:
        from services.grid_model.command import _live_books
        _, books = _live_books()
    touch_by_sym = {} if touch_by_sym is None else touch_by_sym
    if prices is None:
        from services.order_harvester.loop import market_mark
        prices = {}
        for coin, sym in SYM.items():
            prices[coin] = market_mark(sym)
    st = _state()
    sent = []
    for coin, bl in books.items():
        px = prices.get(coin)
        if not px or coin not in SYM:
            continue
        touch = touch_by_sym.get(coin)
        if touch is None:
            from services.grid_model.command import _touch_fn
            touch = touch_by_sym[coin] = _touch_fn(SYM[coin])
        for book in bl:
            name = (" ".join(book.name.split()[:2]) if book.inverse
                    else book.name.split()[0] + (" шорт" if book.net_qty() < 0
                                                 else " Auto" if book.grid_side == 3
                                                 else " лонг"))
            for c in candidates(book, px, touch):
                if c["p4"] < float(cfg["threshold_4h"]):
                    continue
                key = f"{book.name}|{c['name']}|{round(c['level'], -1):.0f}"
                if not due(st, key, now, float(cfg["cooldown_hours"])):
                    continue
                text = message(name, c)
                if send_fn:
                    try:
                        send_fn(text)
                    except Exception:                       # noqa: BLE001
                        logger.exception("level_alerts.send_failed")
                st[key] = now
                sent.append(text)
                rec = {"ts": datetime.fromtimestamp(now, timezone.utc).isoformat(
                    timespec="seconds"), "bot": book.name, "coin": coin, "price": px, **c}
                with JOURNAL.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return sent


async def level_alerts_loop(stop_event=None, send_fn=None) -> None:
    cfg = load_config()
    poll = int(cfg.get("poll_sec", 600))
    logger.info("level_alerts.start poll=%ds threshold_4h=%.2f", poll,
                float(cfg.get("threshold_4h", 0.3)))
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            sent = await asyncio.to_thread(tick, send_fn)
            if sent:
                logger.info("level_alerts.sent n=%d", len(sent))
        except Exception:                                   # noqa: BLE001
            logger.exception("level_alerts.tick_failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), poll)
                return
            await asyncio.sleep(poll)
        except asyncio.TimeoutError:
            continue
