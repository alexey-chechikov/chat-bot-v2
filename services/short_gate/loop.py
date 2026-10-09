"""Гейт шорт-сеток: цена ниже дневной SMA100 — шорт разрешён, выше — нет.

Оператор 17.09: «как только я пойму, что у нас бычий год, буду работать
только от лонга». Проблема не в решении, а в слове «пойму»: в том бычьем
году, что мы смотрели, яма была вырыта в первые 2-4 месяца, когда бычий
рынок ещё не очевиден. Значит решать должно правило, а не глаз.

ЗАМЕР 17.09.2026 (BTC, 15.05.24-17.09.26, внутри ралли +131%; шорт-сетка
шаг 0.8 / цель 1.65 / ордер $70 / 200 ордеров; гейт выключает бота и
закрывает позицию по рынку):
                       половина с ралли   худшая точка   вторая половина
  без гейта                   −$3 180        −$3 806          +$332
  SMA100                        −$143          −$231          +$274
  SMA150                        −$185          −$222          +$191
  SMA50                         −$214          −$405          +$238
  SMA20                         −$274          −$308          +$208
КОНТРОЛЬ (то же время в рынке 56% и то же число переключений 18-19, но
отрезки включения переставлены случайно): −$791, −$1 616, −$2 121 в
половине с ралли. Перевёрнутый гейт (шорт выше средней): −$860.
То есть работает привязка к цене, а не воздержание от торговли.
Плата: 17% дохода в медвежьей половине и 13 переключений в год.

Оговорки: модель — чистая шорт-сетка без границ GinArea; ралли одно.

СЛУЖБА НИЧЕГО НЕ ВЫКЛЮЧАЕТ. Она считает гейт и сообщает при переключении;
останавливает шорт-ботов оператор руками.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import statistics as st
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "short_gate_config.json"
STATE_PATH = ROOT / "state" / "short_gate_state.json"
JOURNAL_PATH = ROOT / "state" / "short_gate_journal.jsonl"
HEARTBEAT_PATH = ROOT / "state" / "short_gate_heartbeat.json"
FROZEN_1M = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
LIVE_1M = ROOT / "market_live" / "market_1m.csv"

# 07.10.2026, оператор: «где ты говоришь шортить нельзя — я беру прибыль». Прав:
# с 20.08 по 06.10 шорт-сетки закрыли ~+$430 при BTC +7%. Гейт — страховка от
# ралли, а не запрет: формулировка «ЗАПРЕЩЁН» вводила в заблуждение.
ON, OFF = "ШОРТ: ОБЫЧНЫЙ РЕЖИМ", "ШОРТ: РИСК РАЛЛИ"


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(d: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.exception("short_gate.state_write_failed")


def _journal(rec: dict) -> None:
    try:
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**rec, "ts": _iso(_now_ts())},
                               ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("short_gate.journal_failed")


# ─── чистые функции ────────────────────────────────────────────────────
def daily_closes_from_csv(path: Path, ts_col: str, close_col: str,
                          ms: bool = False, tail_bytes: int = 0) -> dict:
    """{'ГГГГ-ММ-ДД': закрытие последней минуты дня}."""
    out: dict[str, float] = {}
    if not path.exists():
        return out
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            if tail_bytes and path.stat().st_size > tail_bytes:
                f.seek(path.stat().st_size - tail_bytes)
                f.readline()                       # обрезанная строка
                head = None
            else:
                head = next(csv.reader(f))
            r = csv.reader(f)
            ti = head.index(ts_col) if head else 0
            ci = head.index(close_col) if head else 4
            for row in r:
                try:
                    if ms:
                        d = datetime.fromtimestamp(int(row[ti]) / 1000,
                                                   timezone.utc).strftime("%Y-%m-%d")
                    else:
                        d = row[ti][:10]
                    out[d] = float(row[ci])
                except (ValueError, IndexError):
                    continue
    except OSError:
        logger.exception("short_gate.read_failed path=%s", path)
    return out


def gate_state(closes: dict, n: int) -> dict | None:
    """Гейт по ВЧЕРАШНЕМУ закрытию против SMA(n) прошлых дней."""
    days = sorted(closes)
    if len(days) < n + 2:
        return None
    last_done = days[-2]                 # вчера: сегодняшний день ещё идёт
    i = days.index(last_done)
    sma = st.mean(closes[d] for d in days[i - n:i])
    px = closes[last_done]
    return {"on": px < sma, "day": last_done, "close": px, "sma": sma,
            "dist_pct": (px / sma - 1) * 100, "n_days": len(days)}


def card(g: dict, n: int, prev_day: str | None) -> str:
    state = ON if g["on"] else OFF
    icon = "🟢" if g["on"] else "🔴"
    where = "ниже" if g["on"] else "выше"
    lines = [
        f"{icon} ГЕЙТ ШОРТА: {state}",
        f"вчерашнее закрытие {g['close']:,.0f} {where} SMA{n} "
        f"{g['sma']:,.0f} на {abs(g['dist_pct']):.1f}%",
    ]
    if prev_day:
        lines.append(f"прошлое переключение {prev_day}")
    if g["on"]:
        lines.append("замер: в этом режиме шорт-сетка и зарабатывала "
                     "(+$274 против +$332 без гейта во второй половине).")
    else:
        lines.append("это страховка, не запрет: в ралли 2024–25 шорт-сетка без неё "
                     "−$3 180 (худшая точка −$3 806), с ней −$143; в боковике она "
                     "стоит ~17% дохода.")
        lines.append("решение твоё: держи размер так, чтобы /stress был 🟢. "
                     "Ботов служба не трогает.")
    return "\n".join(lines)


def current_gate(cfg: dict | None = None) -> dict | None:
    cfg = cfg or load_config()
    n = int(cfg.get("sma_days", 100))
    closes = daily_closes_from_csv(FROZEN_1M, "ts", "close", ms=True)
    closes.update(daily_closes_from_csv(LIVE_1M, "ts_utc", "close",
                                        tail_bytes=40 * 1024 * 1024))
    return gate_state(closes, n)


# ─── цикл ───────────────────────────────────────────────────────────────
def tick(send_fn=None) -> str:
    cfg = load_config()
    status = "error"
    now = _now_ts()
    try:
        if not cfg.get("enabled"):
            status = "disabled"
            return status
        g = current_gate(cfg)
        if g is None:
            status = "no_data"
            return status
        state = read_state()
        prev = state.get("on")
        n = int(cfg.get("sma_days", 100))
        flipped = prev is not None and bool(prev) != bool(g["on"])
        if flipped or prev is None:
            _journal({"event": "FLIP" if flipped else "INIT",
                      "on": g["on"], "day": g["day"], "close": g["close"],
                      "sma": round(g["sma"], 2),
                      "dist_pct": round(g["dist_pct"], 2)})
        if flipped and send_fn:
            try:
                send_fn(card(g, n, state.get("since_day")))
            except Exception:
                logger.exception("short_gate.send_failed")
        state.update({"on": g["on"], "day": g["day"],
                      "close": round(g["close"], 2), "sma": round(g["sma"], 2),
                      "dist_pct": round(g["dist_pct"], 2),
                      "checked": _iso(now)})
        if flipped or prev is None:
            state["since_day"] = g["day"]
        write_state(state)
        status = "flip" if flipped else "ok"
        return status
    finally:
        try:
            HEARTBEAT_PATH.write_text(json.dumps(
                {"ts": _iso(now), "status": status}, ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            logger.exception("short_gate.heartbeat_failed")


async def short_gate_loop(stop_event=None, send_fn=None) -> None:
    cfg = load_config()
    interval = int(cfg.get("poll_seconds", 1800))
    logger.info("short_gate.start interval=%ds sma=%s", interval,
                cfg.get("sma_days", 100))
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            await asyncio.to_thread(tick, send_fn)
        except Exception:
            logger.exception("short_gate.tick_failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), interval)
                return
            await asyncio.sleep(interval)
        except asyncio.TimeoutError:
            continue
