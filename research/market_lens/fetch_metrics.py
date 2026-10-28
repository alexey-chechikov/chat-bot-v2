"""Качает 5-минутные метрики Binance USDⓈ-M с data.binance.vision (OI, топ-трейдеры L/S по позициям, все аккаунты L/S,
агрессор) за 15.05.2024 → вчера и кладёт в parquet по символу. Только чтение публичного портала."""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.derivatives_ingest.data_portal_client import DataPortalClient  # noqa: E402

OUT = Path(__file__).resolve().parent / "data"
OUT.mkdir(exist_ok=True)


def main(sym: str) -> None:
    out = OUT / f"{sym}_metrics_5m.parquet"
    parts = []
    have = set()
    if out.exists():
        old = pd.read_parquet(out)
        parts.append(old)
        have = set(pd.to_datetime(old["ts_ms"], unit="ms", utc=True).dt.date)
    c = DataPortalClient(interval_s=0.2)
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    d, n = date(2024, 5, 15), 0
    while d <= end:
        if d not in have:
            try:
                parts.append(c.fetch_metrics_day(sym, d))
                n += 1
            except FileNotFoundError:
                print(sym, d, "нет файла", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(sym, d, "сбой", exc, flush=True)
            if n and n % 50 == 0:
                pd.concat(parts).drop_duplicates("ts_ms").sort_values("ts_ms").to_parquet(out, index=False)
                print(sym, d, "сохранено", n, flush=True)
        d += timedelta(days=1)
    df = pd.concat(parts).drop_duplicates("ts_ms").sort_values("ts_ms")
    df.to_parquet(out, index=False)
    print(sym, "готово: строк", len(df), "дней новых", n, "с", pd.to_datetime(df.ts_ms.min(), unit="ms"),
          "по", pd.to_datetime(df.ts_ms.max(), unit="ms"), flush=True)


if __name__ == "__main__":
    for s in sys.argv[1:]:
        main(s)
