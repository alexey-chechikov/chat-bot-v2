"""Экспорт данных живого альт-грид прогона 2026-06-10 для анализа на Win.

Вытаскивает из выгрузки трекера (ginarea_live/*.csv — НЕ в гите) все строки
по ботам WLD/SOL/XRP за 2026-06-10 в docs/CONTEXT/data/alt_run_2026-06-10/
(коммитится в ветку). Плюс summary.json с итогами.
"""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ginarea_tracker.storage import SNAPSHOTS_HEADERS, EVENTS_HEADERS, PARAMS_HEADERS

OUT = ROOT / "docs" / "CONTEXT" / "data" / "alt_run_2026-06-10"
OUT.mkdir(parents=True, exist_ok=True)

BOTS = {
    "5617871752": "WLD",
    "5693279219": "SOL",
    "4306550166": "XRP",
}
SINCE = "2026-06-10T00:00"


def export(src: str, headers: list[str]) -> int:
    path = ROOT / "ginarea_live" / f"{src}.csv"
    n = 0
    with (OUT / f"{src}.csv").open("w", newline="", encoding="utf-8") as out_fh:
        w = csv.writer(out_fh)
        w.writerow(headers)
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            cleaned = (line.replace("\x00", "") for line in fh)
            for rec in csv.reader(cleaned):
                if len(rec) != len(headers):
                    continue
                if rec[1] in BOTS and rec[0] >= SINCE:
                    w.writerow(rec)
                    n += 1
    return n


counts = {src: export(src, h) for src, h in (
    ("snapshots", SNAPSHOTS_HEADERS),
    ("events", EVENTS_HEADERS),
    ("params", PARAMS_HEADERS),
)}

summary = {
    "date": "2026-06-10",
    "bots": BOTS,
    "rows": counts,
    "outcomes": {
        "WLD": {"result_usd": -98.96, "how": "tsl=-175 сработал 16:58 UTC (статус 16); "
                "short-нога +71 профита, реверс в LONG 4403@0.4588, мешок до -181"},
        "SOL": {"result_usd": -33.0, "how": "оператор закрыл руками ~17:3X UTC (паттерн net-0)"},
        "XRP": {"result_usd": None, "how": "жив на момент экспорта; LONG-нога +694@1.1079 против MARKDOWN"},
    },
    "notes": [
        "tsl (total SL) GinArea меряет НЕРЕАЛИЗОВАННЫЙ мешок позиции, не общий PnL бота",
        "статус 16 = стоп по TP/SL (эмпирика)",
        "фактический охват ботов был ~6% вместо 12% сканера (step меньше + узкий бордер)",
        "BTC 4h: MARKDOWN весь день (regime_v2), SHORT-зона vs красная TEMA200",
    ],
}
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
print(json.dumps(counts, indent=1))
print("→", OUT)
