"""Журнал сигналов Bybit TradeGPT (оператор пересылает их в Telegram-бота, 10.10.2026).

Зачем: сигнал TradeGPT — направление и плечо без стопа и цели, обоснование — разворот формы/объём/MACD
(похожие индикаторы наша лаборатория уже проверяла против плацебо: шум). Прежде чем торговать — замер:
куда пошла цена через 1/4/24 ч в сторону сигнала, против случайного направления.

Сообщение распознаётся по словам «TradeGPT» и «Контрактная пара»/«Contract». Время сигнала — время
исходного сообщения (forward_date), иначе время получения. Цены — публичные свечи Bybit (linear), запасной
источник Binance. Результат считается при запросе /tgpt и кэшируется в журнале.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / "state" / "tradegpt_signals.jsonl"
HORIZ = (1, 4, 24)
FEE = 0.1                     # % за круг тейкером (для чистого результата)
# виртуальные сделки «тейк / стоп» (вопрос оператора 11.10: $200, тейк 1%, стоп 3–5%) — без денег, по минуткам
# Bybit от цены входа p0; в одной минуте задеты оба — стоп; не закрылась за 72 ч — по цене закрытия.
# Бэктест 2г (research/tradegpt/barrier.py, N 4173): 1/3 −0.13%, 1/5 −0.10%, 2/5 −0.06% на сделку.
RULES = ((1.0, 3.0), (1.0, 5.0), (2.0, 5.0))
MAX_H = 72
STAKE = 200.0

DOWN = ("снижается", "снижение", "шорт", "short", "bearish", "down", "падает", "продав")
UP = ("возраст", "растёт", "растет", "повышается", "рост", "лонг", "long", "bullish", "up", "покуп")


def is_tradegpt(text: str) -> bool:
    t = (text or "").lower()
    return "tradegpt" in t and ("контрактная пара" in t or "contract" in t)


def parse(text: str) -> dict | None:
    """Монета, цена, направление, плечо, обоснование из текста TradeGPT."""
    t = text or ""
    sym = re.search(r"(?:Контрактная пара|Contract(?: pair)?)\s*[:：]\s*([A-Z0-9]+)", t, re.I)
    px = re.search(r"(?:Входная цена|Entry(?: price)?)\s*[:：]\s*([\d.,]+)", t, re.I)
    dr = re.search(r"(?:Направление|Direction)\s*[:：]\s*([^\n]+)", t, re.I)
    lev = re.search(r"(?:Плечо|Leverage)\s*[:：]\s*(\d+)", t, re.I)
    why = re.search(r"AI\s*сигнал\s*[:：]?\s*\n?([^\n]+)", t, re.I)
    if not sym or not dr:
        return None
    d = dr.group(1).strip().lower()
    side = "SHORT" if any(w in d for w in DOWN) else ("LONG" if any(w in d for w in UP) else None)
    if side is None:
        return None
    return {"symbol": sym.group(1).upper(), "side": side,
            "price": float(px.group(1).replace(",", "")) if px else None,
            "leverage": int(lev.group(1)) if lev else None,
            "why": why.group(1).strip() if why else ""}


def record(text: str, signal_ts: float) -> dict | None:
    s = parse(text)
    if not s:
        return None
    rec = {"ts": datetime.fromtimestamp(signal_ts, timezone.utc).isoformat(timespec="seconds"), **s}
    rows = _read()
    if any(r["symbol"] == rec["symbol"] and r["ts"] == rec["ts"] and r["side"] == rec["side"] for r in rows):
        return {**rec, "duplicate": True}
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _read() -> list[dict]:
    try:
        return [json.loads(l) for l in JOURNAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    except FileNotFoundError:
        return []


def _write(rows: list[dict]) -> None:
    from services.weex_grid.engine import atomic_write
    atomic_write(JOURNAL, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def price_at(symbol: str, ts: float) -> float | None:
    """Цена открытия минутной свечи в момент ts (Bybit linear, иначе Binance spot)."""
    ms = int(ts // 60 * 60 * 1000)
    urls = [f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=1&start={ms}&limit=1",
            f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&startTime={ms}&limit=1"]
    for u in urls:
        try:
            data = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "bot7"}),
                                                     timeout=15).read())
            rows = data.get("result", {}).get("list") if isinstance(data, dict) else data
            if rows:
                return float(rows[0][1])
        except Exception:                                       # noqa: BLE001
            logger.exception("tradegpt.price_failed %s", u[:60])
    return None


def klines(symbol: str, start: float, end: float) -> list[tuple]:
    """Минутки Bybit linear [start, end): (ts_ms, open, high, low, close) по возрастанию."""
    out: list[tuple] = []
    a, b = int(start // 60 * 60_000), int(end * 1000)
    while a < b:
        u = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=1&start={a}&limit=1000"
        try:
            data = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "bot7"}),
                                                     timeout=15).read())
        except Exception:                                       # noqa: BLE001
            logger.exception("tradegpt.klines_failed %s", symbol)
            return []
        rows = sorted((int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]))
                      for x in data.get("result", {}).get("list") or [])
        rows = [x for x in rows if x[0] < b and (not out or x[0] > out[-1][0])]
        if not rows:
            break
        out += rows
        a = rows[-1][0] + 60_000
    return out


def rule_key(tp: float, sl: float) -> str:
    return f"tp{tp:g}_sl{sl:g}"


def barrier(k: list[tuple], d: int, entry: float, tp: float, sl: float, expired: bool) -> float | None:
    """Результат виртуальной сделки в % цены после комиссии; None — ещё открыта."""
    for _, _o, h, l, _c in k:
        if d * ((l if d > 0 else h) / entry - 1) * 100 <= -sl:
            return -sl - FEE
        if d * ((h if d > 0 else l) / entry - 1) * 100 >= tp:
            return tp - FEE
    if expired and k:
        return d * (k[-1][4] / entry - 1) * 100 - FEE
    return None


def update_outcomes(now: float | None = None) -> list[dict]:
    """Дописать цены входа и через 1/4/24 ч там, где время уже наступило, и итоги виртуальных сделок."""
    now = now or time.time()
    rows = _read()
    changed = False
    for r in rows:
        t0 = datetime.fromisoformat(r["ts"]).timestamp()
        if r.get("p0") is None:
            r["p0"] = price_at(r["symbol"], t0)
            changed = True
        for h in HORIZ:
            k = f"p{h}"
            if r.get(k) is None and now >= t0 + h * 3600 + 60:
                r[k] = price_at(r["symbol"], t0 + h * 3600)
                changed = True
        todo = [(tp, sl) for tp, sl in RULES if r.get(rule_key(tp, sl)) is None]
        if r.get("p0") and todo and now > t0 + 60:
            end = min(now, t0 + MAX_H * 3600)
            k = klines(r["symbol"], t0, end)
            d = 1 if r["side"] == "LONG" else -1
            for tp, sl in todo:
                res = barrier(k, d, r["p0"], tp, sl, expired=now >= t0 + MAX_H * 3600)
                if res is not None:
                    r[rule_key(tp, sl)] = round(res, 3)
                    changed = True
    if changed:
        _write(rows)
    return rows


def summary() -> str:
    rows = update_outcomes()
    if not rows:
        return ("📒 Журнал TradeGPT пуст. Пересылай сюда сигналы TradeGPT из Bybit — запишу и через 1/4/24 ч "
                "посчитаю, куда пошла цена, против случайного направления.")
    lines = [f"📒 TradeGPT: сигналов {len(rows)} (с {rows[0]['ts'][:10]})"]
    for h in HORIZ:
        res = []
        for r in rows:
            p0, ph = r.get("p0"), r.get(f"p{h}")
            if p0 and ph:
                d = 1 if r["side"] == "LONG" else -1
                res.append(d * (ph / p0 - 1) * 100)
        if res:
            hit = sum(1 for x in res if x > 0)
            avg = sum(res) / len(res)
            lines.append(f"через {h} ч: {len(res)} шт., угадано {hit} ({hit / len(res):.0%}), средний ход "
                         f"{avg:+.2f}% (после комиссии {avg - FEE:+.2f}%)")
    lines.append(f"виртуально по ${STAKE:.0f} без плеча (тейк/стоп, после комиссии):")
    for tp, sl in RULES:
        res = [r[rule_key(tp, sl)] for r in rows if r.get(rule_key(tp, sl)) is not None]
        if res:
            win = sum(1 for x in res if x > 0)
            usd = sum(res) * STAKE / 100
            lines.append(f"  {tp:g}% / −{sl:g}%: закрыто {len(res)}, тейков {win} ({win / len(res):.0%}, безубыток "
                         f"{(sl + FEE) / (tp + sl):.0%}), итог ${usd:+.2f}, открыто {len(rows) - len(res)}")
    lines.append("  бэктест 2 года (4 173 похожих сигнала): 1/3 −0.13%, 1/5 −0.10%, 2/5 −0.06% на сделку")
    last = rows[-5:]
    lines.append("последние: " + "; ".join(f"{r['symbol']} {r['side']} {r['ts'][5:16]}" for r in last))
    lines.append("Монетка угадывает 50%; вывод — не раньше ~50 сигналов.")
    return "\n".join(lines)
