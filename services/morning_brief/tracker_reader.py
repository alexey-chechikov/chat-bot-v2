"""Чтение выгрузки ginarea-tracker (ginarea_live/*.csv) — БЕЗ GinArea API.

GinArea = одна сессия на одну машину; сессию держит com.bot7.ginarea-tracker,
поэтому брифинг берёт состояние ботов с диска. Файлы append-only и большие
(snapshots.csv ~150MB+) — читаем только хвост через seek.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ginarea_tracker.storage import PARAMS_HEADERS, SNAPSHOTS_HEADERS

ROOT = Path(__file__).resolve().parents[2]
LIVE_DIR = ROOT / "ginarea_live"
MSK = timezone(timedelta(hours=3))

# статусы GinArea (services/short_bots_guard/control.py)
STATUS_ACTIVE = 2
STATUS_PAUSED = 3
STATUS_FAILED = 10
STATUS_STOPPED = 12
STATUS_LABEL = {2: "активен", 3: "пауза", 10: "FAILED", 12: "выключен"}

# хвоста в 12MB хватает на >24ч снапшотов (~20 ботов × 60с × ~150 байт ≈ 4.5MB/сутки)
SNAP_TAIL_BYTES = 12_000_000
PARAMS_TAIL_BYTES = 16_000_000

# бот «свежий», если его последний снапшот в текущем цикле трекера; иначе бот
# удалён из GinArea (трекер перестал его писать) — призраков не показываем
FRESH_WINDOW_SEC = 300.0


def _tail_lines(path: Path, max_bytes: int) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()  # дропаем обрезанную строку
        data = fh.read()
    return data.decode("utf-8", errors="replace").splitlines()


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_rows(lines: list[str], headers: list[str]) -> list[dict]:
    rows = []
    for rec in csv.reader(lines):
        if len(rec) != len(headers) or rec[0] == "ts_utc":
            continue  # заголовок / чужая схема / битая строка
        rows.append(dict(zip(headers, rec)))
    return rows


def read_snapshots(path: Path | None = None, now: datetime | None = None) -> dict:
    """→ {"bots": {bot_id: {"latest": row, "day0": row|None, "fresh": bool}}, "stale_min": float|None}

    latest — последний снапшот бота; day0 — первый снапшот текущих суток (мск),
    для дневного Δ. Числовые поля приведены к float (пустые → None).
    fresh — бот есть в текущем цикле трекера (False = удалён из GinArea, призрак).
    stale_min — минут с последнего снапшота трекера (None если файла нет).
    """
    path = path or (LIVE_DIR / "snapshots.csv")
    now = now or datetime.now(timezone.utc)
    if not path.exists():
        return {"bots": {}, "stale_min": None}
    rows = _parse_rows(_tail_lines(path, SNAP_TAIL_BYTES), SNAPSHOTS_HEADERS)
    today_msk = now.astimezone(MSK).date()
    bots: dict[str, dict] = {}
    last_ts = None
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts_utc"])
        except ValueError:
            continue
        for k in ("position", "profit", "current_profit", "average_price",
                  "balance", "liquidation_price", "trade_volume"):
            r[k] = _f(r[k])
        for k in ("in_filled_count", "out_filled_count"):
            v = _f(r[k])
            r[k] = int(v) if v is not None else None
        r["status"] = int(_f(r["status"]) or 0)
        r["_ts"] = ts
        slot = bots.setdefault(r["bot_id"], {"latest": None, "day0": None, "fresh": False})
        slot["latest"] = r  # строки идут хронологически — последняя побеждает
        if slot["day0"] is None and ts.astimezone(MSK).date() == today_msk:
            slot["day0"] = r
        if last_ts is None or ts > last_ts:
            last_ts = ts
    if last_ts:
        for slot in bots.values():
            slot["fresh"] = (last_ts - slot["latest"]["_ts"]).total_seconds() <= FRESH_WINDOW_SEC
    stale_min = (now - last_ts).total_seconds() / 60.0 if last_ts else None
    return {"bots": bots, "stale_min": stale_min}


def read_params(path: Path | None = None) -> dict[str, dict]:
    """→ {bot_id: последняя params-строка} (border, total_sl/tp, instop...)."""
    path = path or (LIVE_DIR / "params.csv")
    if not path.exists():
        return {}
    rows = _parse_rows(_tail_lines(path, PARAMS_TAIL_BYTES), PARAMS_HEADERS)
    out: dict[str, dict] = {}
    for r in rows:
        for k in ("border_top", "border_bottom", "total_sl", "total_tp"):
            r[k] = _f(r[k])
        out[r["bot_id"]] = r
    return out
