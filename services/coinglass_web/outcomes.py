"""Досверка снимков CoinGlass: какая магнитная зона сработала первой — «обучение на собственном анализе» (оператор
18.10). Правила заданы до накопления исходов (GPT уточняет — docs/COINGLASS_MAC_PIPELINE_2026-10-18.md):

  - для снимка: цена P, зона шортов №1 сверху (её нижняя граница U), зона лонгов №1 снизу (её верхняя граница L);
    номер 1 — так сортирует CoinGlass (по силе);
  - горизонты 4 ч и 24 ч, Binance USDⓈ-M 1m после времени снимка: первая минута с high ≥ U — «сверху»,
    с low ≤ L — «снизу», обе в одной минуте — «обе», ни одной — «нет»;
  - база (случайное блуждание без сноса, первое касание): доля «сверху» среди сработавших = dL/(dU+dL),
    где dU = (U−P)/P, dL = (P−L)/P;
  - основная серия — первый снимок каждого дня (дни независимее часов); все часовые — вспомогательная.

Пишет state/coinglass/outcomes.jsonl (добавлением, один исход на снимок и горизонт), не переписывает.
"""
from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone

from services.coinglass_web.collector import DIR

HORIZONS = {"4h": 4 * 3600, "24h": 24 * 3600}


def _klines(start_ms: int, end_ms: int) -> list:
    out, t = [], start_ms
    while t < end_ms:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=1500&startTime={t}"
               f"&endTime={end_ms - 1}")
        rows = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                                 timeout=20).read())
        if not rows:
            break
        out += rows
        t = int(rows[-1][0]) + 60_000
    return out


def first_touch(rows: list, upper: float, lower: float) -> str:
    for r in rows:
        hi, lo = float(r[2]), float(r[3])
        if hi >= upper and lo <= lower:
            return "both"
        if hi >= upper:
            return "upper"
        if lo <= lower:
            return "lower"
    return "none"


def _snapshots() -> list[dict]:
    p = DIR / "snapshots.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        lv = r.get("levels") or {}
        if lv.get("zones_short") and lv.get("zones_long"):
            out.append(r)
    return out


def done_keys() -> set:
    p = DIR / "outcomes.jsonl"
    if not p.exists():
        return set()
    return {(json.loads(x)["ts"], json.loads(x)["horizon"]) for x in p.read_text(encoding="utf-8").splitlines() if x}


def update(now: datetime | None = None) -> int:
    """Досверить созревшие снимки. Возвращает число новых исходов."""
    now = now or datetime.now(timezone.utc)
    have, new = done_keys(), 0
    with open(DIR / "outcomes.jsonl", "a", encoding="utf-8") as f:
        for r in _snapshots():
            ts = datetime.fromisoformat(r["ts"])
            lv = r["levels"]
            p = lv["price"]
            up = lv["zones_short"][0]["lo"]
            dn = lv["zones_long"][0]["hi"]
            for h, sec in HORIZONS.items():
                if (r["ts"], h) in have or now < ts + timedelta(seconds=sec + 120):
                    continue
                a = int(ts.timestamp() * 1000) // 60_000 * 60_000 + 60_000      # с минуты ПОСЛЕ снимка
                rows = _klines(a, a + sec * 1000)
                if len(rows) < sec // 60 * 0.99:
                    continue                                    # дыра в минутках — досверим позже
                du, dl = (up - p) / p, (p - dn) / p
                rec = {"ts": r["ts"], "horizon": h, "price": p, "upper": up, "lower": dn, "du": du, "dl": dl,
                       "base_up": dl / (du + dl) if du + dl > 0 else None, "outcome": first_touch(rows, up, dn),
                       "near_short_pct": (lv.get("near") or {}).get("short_pct"),
                       "ret": float(rows[-1][4]) / p - 1}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                new += 1
    return new


def stats(horizon: str = "24h", daily: bool = True) -> dict:
    """Наблюдаемая доля «сверху» среди сработавших против базы по расстояниям; daily — первый снимок дня."""
    p = DIR / "outcomes.jsonl"
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x] if p.exists() else []
    rows = [r for r in rows if r["horizon"] == horizon and r["outcome"] in ("upper", "lower") and r["base_up"]]
    if daily:
        seen, keep = set(), []
        for r in sorted(rows, key=lambda r: r["ts"]):
            d = r["ts"][:10]
            if d not in seen:
                seen.add(d)
                keep.append(r)
        rows = keep
    n = len(rows)
    if not n:
        return {"n": 0}
    obs = sum(r["outcome"] == "upper" for r in rows) / n
    base = sum(r["base_up"] for r in rows) / n
    var = sum(r["base_up"] * (1 - r["base_up"]) for r in rows) / n / n     # дисперсия доли при базе (Бернулли)
    z = (obs - base) / math.sqrt(var) if var > 0 else 0.0
    return {"n": n, "obs_up": obs, "base_up": base, "z": z, "differs": n >= 30 and abs(z) > 2.58}
