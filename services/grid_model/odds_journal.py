"""Журнал прогнозов внутридневной модели и живая сверка (ворота №5).

Раз в час, на закрытии часовой свечи, пишем обещания модели: шанс коснуться
±0.5/1/2/3% за 1/4/12/24 часа и полуширину коридора 80%. Через h часов те же
свечи отвечают, случилось ли касание. Точка отсчёта — close закрытой свечи,
горизонт — следующие h свечей: ровно так модель и училась, поэтому сверка
честная, без подгонки по времени.

В TG ничего не шлёт. Смотреть: `/odds сверка`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from services.grid_model import odds_intraday as oi

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / "state" / "odds_journal.jsonl"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
PCTS = (0.005, 0.01, 0.02, 0.03)
POLL_SEC = 600
HOUR_MS = 3_600_000


def _recorded(path: Path = JOURNAL) -> set[tuple[str, int]]:
    out = set()
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for ln in f:
            try:
                r = json.loads(ln)
                out.add((r["sym"], int(r["ts_ms"])))
            except (ValueError, KeyError):
                continue
    return out


def entry(sym: str, m: oi.Model, d: pd.DataFrame) -> dict:
    """Обещания модели на закрытии последней свечи d."""
    now = oi.now_state(m, d)
    rows = []
    for h in oi.HOURS:
        for pct in PCTS:
            for sgn in (1, -1):
                rows.append({"h": h, "pct": sgn * pct,
                             "p": round(m.touch(sgn * pct, h, now.paths[h]), 4)})
        rows.append({"h": h, "corridor": round(m.corridor(h, now.paths[h], 0.8), 5)})
    return {"sym": sym, "ts_ms": int(d.index[-1].value // 1_000_000),
            "close": float(d["close"].iloc[-1]), "rows": rows}


def record(path: Path = JOURNAL) -> int:
    """Дописать обещания по новым закрытым свечам. Возвращает число записей."""
    done = _recorded(path)
    n = 0
    for sym in SYMBOLS:
        try:
            m, d = oi.get_model(sym)            # load_hourly дотягивает свежие свечи
        except Exception:                       # noqa: BLE001
            logger.exception("odds_journal.model_failed sym=%s", sym)
            continue
        e = entry(sym, m, d)
        if (sym, e["ts_ms"]) in done:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        n += 1
    return n


def outcomes(path: Path = JOURNAL, candles: dict | None = None) -> pd.DataFrame:
    """Созревшие обещания против факта: касание по high/low следующих h свечей."""
    if not path.exists():
        return pd.DataFrame()
    recs = [json.loads(ln) for ln in path.open(encoding="utf-8") if ln.strip()]
    candles = candles or {}
    out = []
    for sym in {r["sym"] for r in recs}:
        d = candles.get(sym)
        if d is None:
            d = oi.load_hourly(sym, refresh=False)
        ts = (d.index.asi8 // 1_000_000)
        hi, lo = d["high"].to_numpy(), d["low"].to_numpy()
        pos = {int(t): i for i, t in enumerate(ts)}
        for r in recs:
            if r["sym"] != sym or int(r["ts_ms"]) not in pos:
                continue
            i, c = pos[int(r["ts_ms"])], float(r["close"])
            for row in r["rows"]:
                h = int(row["h"])
                if i + h >= len(d):
                    continue                     # ещё не созрело
                mx = hi[i + 1:i + 1 + h].max() / c - 1
                mn = lo[i + 1:i + 1 + h].min() / c - 1
                if "corridor" in row:
                    x = row["corridor"]
                    out.append({"sym": sym, "h": h, "kind": "коридор", "p": 0.8,
                                "y": float(mx < x and mn > -x)})
                else:
                    pct = row["pct"]
                    y = mx >= pct if pct > 0 else mn <= pct
                    out.append({"sym": sym, "h": h, "kind": "касание",
                                "p": row["p"], "y": float(y)})
    return pd.DataFrame(out)


def verify_text(path: Path = JOURNAL, candles: dict | None = None) -> str:
    t = outcomes(path, candles)
    if t.empty:
        return ("📓 СВЕРКА ШАНСОВ: созревших прогнозов пока нет. Журнал пишется "
                "раз в час; первые часовые — через час, суточные — через сутки.")
    first = pd.to_datetime(min(int(json.loads(ln)["ts_ms"])
                               for ln in path.open(encoding="utf-8") if ln.strip()),
                           unit="ms", utc=True)
    out = [f"📓 СВЕРКА ШАНСОВ С ЖИВЫМ РЫНКОМ · с {first:%d.%m %H:%M} UTC",
           "обещали → случилось (число проверок)"]
    touch = t[t["kind"] == "касание"].copy()
    if not touch.empty:
        touch["bin"] = pd.cut(touch["p"], [0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0],
                              include_lowest=True)
        out.append("КАСАНИЕ:")
        g = touch.groupby("bin", observed=True).agg(p=("p", "mean"), y=("y", "mean"),
                                                    n=("y", "count"))
        for r in g.itertuples():
            out.append(f"  {r.p:.0%} → {r.y:.0%} ({r.n})")
        brier = float(((touch["p"] - touch["y"]) ** 2).mean())
        out.append(f"  ошибка (Brier) {brier:.3f}")
    cor = t[t["kind"] == "коридор"]
    if not cor.empty:
        out.append("КОРИДОР 80% (цена не вышла):")
        for (sym, h), g in cor.groupby(["sym", "h"]):
            out.append(f"  {sym[:3]} {h}ч: {g['y'].mean():.0%} ({len(g)})")
    if len(touch) < 500:
        out.append("выборка ещё мала: часовые прогнозы идут внахлёст, честный вывод — "
                   "через 1–2 недели")
    return "\n".join(out)


async def odds_journal_loop(stop_event=None) -> None:
    logger.info("odds_journal.start poll=%ds", POLL_SEC)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            n = await asyncio.to_thread(record)
            if n:
                logger.info("odds_journal.recorded n=%d", n)
        except Exception:                                   # noqa: BLE001
            logger.exception("odds_journal.tick_failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), POLL_SEC)
                return
            await asyncio.sleep(POLL_SEC)
        except asyncio.TimeoutError:
            continue
