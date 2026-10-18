"""Описи данных для GPT 18.10 (только чтение): запись стакана WEEX v2 и данные шага A (OI 5m, ликвидации).

    .venv/bin/python3 research/weex/data_inventory_1018.py <out_dir>
Пишет <out_dir>/WEEX_BOOK_INVENTORY_2026-10-18.json и LPX_DATA_INVENTORY_2026-10-18.json. Сырые данные не копирует."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
csv.field_size_limit(1 << 30)


def utc(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(float(ms)) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"
    except (TypeError, ValueError, OSError):
        return None


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def scan_csv(p: Path, tcols: tuple[str, ...]) -> dict:
    rows, kinds, applied0, sessions = 0, Counter(), 0, set()
    tmin = {c: None for c in tcols}
    tmax = {c: None for c in tcols}
    with open(p, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        header = r.fieldnames
        for row in r:
            rows += 1
            if "session" in row:
                sessions.add(row["session"])
            if "kind" in row:
                kinds[row["kind"]] += 1
            if row.get("applied") == "0":
                applied0 += 1
            for c in tcols:
                v = row.get(c)
                if v in (None, ""):
                    continue
                try:
                    x = int(float(v))
                except ValueError:
                    continue
                tmin[c] = x if tmin[c] is None else min(tmin[c], x)
                tmax[c] = x if tmax[c] is None else max(tmax[c], x)
    out = {"header": header, "rows": rows, "sessions": len(sessions),
           "time": {c: {"min_utc": utc(tmin[c]), "max_utc": utc(tmax[c])} for c in tcols}}
    if kinds:
        out["kind_counts"] = dict(kinds)
        out["applied_0_rows"] = applied0
    return out


def book_inventory() -> dict:
    d = ROOT / "state" / "weex_book"
    files = []
    for p in sorted(d.glob("*_*_*.csv")):
        m = re.match(r"([A-Z]+)_(\d{8})_(depth|trades2|events|book|trades)\.csv$", p.name)
        if not m:
            continue
        sym, day, kind = m.groups()
        rec = {"file": p.name, "symbol": sym, "utc_day": day, "kind": kind, "bytes": p.stat().st_size,
               "sha256": sha(p), "format": "v2" if kind in ("depth", "trades2", "events") else "legacy"}
        if kind == "depth":
            rec.update(scan_csv(p, ("E", "recv_ms")))
        elif kind == "trades2":
            rec.update(scan_csv(p, ("T", "E", "recv_ms")))
        elif kind == "events":
            rec.update(scan_csv(p, ("recv_ms",)))
            with open(p, newline="", encoding="utf-8") as f:
                ev = list(csv.DictReader(f))
            rec["event_counts"] = dict(Counter(e.get("event") for e in ev))
            rec["events"] = [{"utc": utc(e.get("recv_ms")), "session": e.get("session"), "event": e.get("event"),
                              "detail": (e.get("detail") or "")[:160]} for e in ev]
        files.append(rec)
    return {"source": "services/weex_book/recorder.py (v2 depth/trades2/events с 13.10.2026; legacy book/trades)",
            "generated_utc": utc(datetime.now(timezone.utc).timestamp() * 1000),
            "note": "Опись только; сырые файлы не опубликованы. Пропуски/ресинки — по events.csv, не восстановлены.",
            "files": files}


def oi_inventory(p: Path) -> dict:
    ts = []
    with open(p, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        for row in r:
            try:
                ts.append(int(row[0]))
            except (ValueError, IndexError):
                pass
    ts.sort()
    steps = Counter()
    gaps = []
    for a, b in zip(ts, ts[1:]):
        steps[b - a] += 1
        if b - a > 300_000:
            gaps.append((b - a, a, b))
    gaps.sort(reverse=True)
    return {"file": str(p.relative_to(ROOT)), "header": header, "rows": len(ts), "first_utc": utc(ts[0]),
            "last_utc": utc(ts[-1]), "step_ms_counts": {str(k): v for k, v in steps.most_common(5)},
            "gaps_over_5m": len(gaps), "largest_gaps": [{"minutes": g // 60000, "from_utc": utc(a), "to_utc": utc(b)}
                                                        for g, a, b in gaps[:8]],
            "sha256": sha(p)}


def liq_inventory() -> dict:
    p = ROOT / "market_live" / "liquidations.csv"
    by, first, last, empty = Counter(), None, None, 0
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by[(row["exchange"], row["side"])] += 1
            t = row["ts_utc"]
            first = first or t
            last = t
            if not row.get("qty") or not row.get("price"):
                empty += 1
    raw = []
    for q in sorted((ROOT / "market_live" / "liq_raw").glob("*.jsonl")):
        n, fields, basis, units, tmin, tmax = 0, set(), Counter(), Counter(), None, None
        with open(q, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                n += 1
                fields.update(r.keys())
                basis[r.get("price_basis")] += 1
                units[r.get("qty_unit")] += 1
                x = r.get("recv_ms")
                if isinstance(x, (int, float)):
                    tmin = x if tmin is None else min(tmin, x)
                    tmax = x if tmax is None else max(tmax, x)
        raw.append({"file": q.name, "rows": n, "fields": sorted(fields), "price_basis": dict(basis),
                    "qty_unit": dict(units), "recv_min_utc": utc(tmin), "recv_max_utc": utc(tmax),
                    "sha256": sha(q)})
    return {"normalized_csv": {"file": "market_live/liquidations.csv", "header": "ts_utc,exchange,side,qty,price",
                               "rows": sum(by.values()), "first": first, "last": last,
                               "rows_without_qty_or_price": empty,
                               "by_exchange_side": {f"{e}/{s}": n for (e, s), n in sorted(by.items())},
                               "side_semantics": "сторона ЛИКВИДИРОВАННОЙ позиции; метки Bybit исправлены 23.07.2026 "
                                                 "(allLiquidation.S — сторона позиции; копия до исправления — .bak)",
                               "price_basis": "неизвестно по строке (сырые поля не сохранялись до 13.10)"},
            "raw_jsonl_since_2026_10_13": raw}


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "WEEX_BOOK_INVENTORY_2026-10-18.json").write_text(
        json.dumps(book_inventory(), ensure_ascii=False, indent=1), encoding="utf-8")
    lpx = {"generated_utc": utc(datetime.now(timezone.utc).timestamp() * 1000),
           "oi_5m": [oi_inventory(ROOT / "data" / "pump_research" / f"{s}_oi_5min.csv")
                     for s in ("BTCUSDT", "ETHUSDT", "XRPUSDT")],
           "oi_units": "open_interest в монетах контракта (Binance UM sumOpenInterest), источник — data.binance.vision "
                       "daily metrics (services/derivatives_ingest/data_portal_client.py); после 2026-05-22 не докачано",
           "liquidations": liq_inventory(),
           "mark_price_1m": "локально НЕТ (frozen UM — last-price klines). Публичные markPriceKlines Binance можно "
                            "скачать отдельно — только по RUN_PLAN, не молча."}
    (out / "LPX_DATA_INVENTORY_2026-10-18.json").write_text(json.dumps(lpx, ensure_ascii=False, indent=1),
                                                           encoding="utf-8")
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
