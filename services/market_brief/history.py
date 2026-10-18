"""История дневных признаков рынка для утренней сводки (оператор 18.10: «вывод на день на основании данных
CoinGlass + как изменилась картина со вчера + статистика, чтобы анализ улучшался»).

CoinGlass без API автоматически не читается; его панели — агрегаты биржевых данных. Берём публичные первоисточники:
  - data.binance.vision daily metrics (5 мин): OI, top-trader L/S, global L/S, taker long/short vol ratio;
  - Binance spot дневные свечи (цена, объём), фандинг USDⓈ-M.
Дневная строка (UTC): close, ret_1d, oi (последняя точка дня), oi_chg_pct, top_ls, global_ls, taker_ratio (среднее за
день), funding_day (сумма 3 начислений). Файл: state/market_brief/features_<SYM>.csv — дописывается, не переписывается.

    .venv/bin/python3 -m services.market_brief.history backfill BTCUSDT 2024-05-15
"""
from __future__ import annotations

import csv
import json
import logging
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "state" / "market_brief"
FIELDS = ["day", "close", "ret_1d", "oi", "oi_chg_pct", "top_ls", "global_ls", "taker_ratio", "funding_day"]


def _get(url: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=20).read())


def features_path(sym: str) -> Path:
    return DIR / f"features_{sym}.csv"


def read_features(sym: str) -> list[dict]:
    p = features_path(sym)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _daily_close(sym: str, start: date, end: date) -> dict[str, float]:
    out, t = {}, int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp() * 1000)
    stop = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() * 1000)
    while t <= stop:
        rows = _get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&startTime={t}&limit=1000")
        if not rows:
            break
        for r in rows:
            if int(r[6]) < datetime.now(timezone.utc).timestamp() * 1000:      # только закрытые дни
                out[datetime.fromtimestamp(int(r[0]) / 1000, timezone.utc).strftime("%Y-%m-%d")] = float(r[4])
        t = int(rows[-1][0]) + 86_400_000
    return out


def _funding(sym: str, start: date) -> dict[str, float]:
    out, t = {}, int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp() * 1000)
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    while t < now:
        rows = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={t}&limit=1000")
        if not rows:
            break
        for r in rows:
            d = datetime.fromtimestamp(int(r["fundingTime"]) / 1000, timezone.utc).strftime("%Y-%m-%d")
            out[d] = out.get(d, 0.0) + float(r["fundingRate"])
        t = int(rows[-1]["fundingTime"]) + 1
    return out


def _metrics_day(client, sym: str, day: date) -> dict | None:
    try:
        df = client.fetch_metrics_day(sym, day)
    except Exception as exc:                                    # noqa: BLE001 — дня может ещё не быть в портале
        logger.info("market_brief.metrics_missing %s %s %s", sym, day, exc)
        return None
    if df.empty:
        return None
    df = df.sort_values("ts_ms")
    return {"oi": float(df["sum_open_interest"].iloc[-1]), "top_ls": float(df["top_trader_ls_ratio"].iloc[-1]),
            "global_ls": float(df["global_ls_ratio"].iloc[-1]), "taker_ratio": float(df["taker_vol_ratio"].mean())}


def update(sym: str, start: date | None = None) -> int:
    """Дописать недостающие закрытые дни (до вчера UTC). Возвращает число новых строк."""
    from services.derivatives_ingest.data_portal_client import DataPortalClient
    DIR.mkdir(parents=True, exist_ok=True)
    rows = read_features(sym)
    have = {r["day"] for r in rows}
    last = date.fromisoformat(rows[-1]["day"]) if rows else (start or date(2024, 5, 15)) - timedelta(days=1)
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    if last >= yesterday:
        return 0
    first = last + timedelta(days=1)
    closes = _daily_close(sym, first - timedelta(days=1), yesterday)
    funding = _funding(sym, first)
    client = DataPortalClient()
    prev_close = float(rows[-1]["close"]) if rows else closes.get((first - timedelta(days=1)).isoformat())
    prev_oi = float(rows[-1]["oi"]) if rows and rows[-1]["oi"] else None
    new = 0
    p = features_path(sym)
    write_header = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            w.writeheader()
        d = first
        while d <= yesterday:
            key = d.isoformat()
            m = _metrics_day(client, sym, d)
            c = closes.get(key)
            if key in have or c is None or m is None:
                if m is None and d >= yesterday - timedelta(days=1):
                    break                                       # портал ещё не выложил день — дописать позже
                d += timedelta(days=1)
                continue
            row = {"day": key, "close": c, "ret_1d": (c / prev_close - 1) if prev_close else "",
                   "oi": m["oi"], "oi_chg_pct": ((m["oi"] / prev_oi - 1) * 100) if prev_oi else "",
                   "top_ls": m["top_ls"], "global_ls": m["global_ls"], "taker_ratio": m["taker_ratio"],
                   "funding_day": funding.get(key, "")}
            w.writerow(row)
            f.flush()
            prev_close, prev_oi, new = c, m["oi"], new + 1
            d += timedelta(days=1)
    return new


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) >= 3 and sys.argv[1] == "backfill":
        st = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None
        print(sys.argv[2], "новых дней", update(sys.argv[2], st))
