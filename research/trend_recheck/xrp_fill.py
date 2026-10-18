"""Дополнение §7а протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md (commit 6ed43ad) — объявленная
чувствительность: XRPUSDT, где 7 200 минут дыр месячных архивов (2022-02-26 00:00…02-28 23:59 и 2022-04-01 00:00…
04-02 23:59) взяты из дневных архивов Binance UM 1m, сверенных с .CHECKSUM (скачивает fetch_um_daily.py).

Ряд строится ТОЛЬКО в памяти: backtests/frozen/XRPUSDT_UM_1m_early.csv и прочие frozen-файлы не меняются. Основной
расчёт и ворота — по ряду с дырами (протокол §1 как есть); этот ряд — только чувствительность рядом с основными числами.

Проверки (любая не прошла — отказ DataError):
  - каждый архив ещё раз сверяется с сохранённым рядом .CHECKSUM (build_early.read_archive), состав архива — один CSV
    <SYM>-1m-<день>.csv, open_time в миллисекундах, только сетка k·60 000;
  - в дне заполнения ровно 1 440 минут, все внутри своего дня UTC, без дублей;
  - ни одна вставленная минута не была в ряду (вставка только в дыры), после вставки в P1 XRP пропусков 0;
  - контрольные соседние дни (02-25, 03-01, 03-31, 04-03) — дневной архив против минут из месячных архивов: OHLCV
    численно равны во всех 1 440 минутах (иначе отказ: источники несовместимы).
Запись чисел (F7 шага данных) здесь не нужна: значения разбираются как числа, файл не пишется.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path("/Users/alexeychechikov/code/bot7")
DAILY = ROOT / "backtests" / "um_daily"
FETCH_REPORT = ROOT / "research" / "trend_recheck" / "out" / "um_daily_fetch.json"
SYM = "XRPUSDT"
FILL_DAYS = ("2022-02-26", "2022-02-27", "2022-02-28", "2022-04-01", "2022-04-02")
CHECK_DAYS = ("2022-02-25", "2022-03-01", "2022-03-31", "2022-04-03")
MIN = 60_000
DAY = 86_400_000
P1_END = 1715731200000


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BE = _load("research/trend_recheck/build_early.py", "tr_build_early")
DataError = BE.DataError


def day_ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def read_day(day: str, sym: str = SYM, root: Path = DAILY) -> np.ndarray:
    """Дневной архив → массив (n, 8): ts, open, high, low, close, volume, taker_buy, trades (float)."""
    rows, st = BE.read_archive(root / sym / f"{sym}-1m-{day}.zip", sym, day)
    a = day_ms(day)
    ts = [t for t, _ in rows]
    if any(not (a <= t < a + DAY) for t in ts):
        raise DataError(f"{sym} {day}: минуты вне своего дня UTC")
    if len(set(ts)) != len(ts):
        raise DataError(f"{sym} {day}: дубли минут")
    return np.array([[float(x) for x in r] for _, r in rows], dtype=float).reshape(-1, 8)


def fill(m: dict, days=FILL_DAYS, check_days=CHECK_DAYS, sym: str = SYM, root: Path = DAILY,
         fetch_report: Path | None = FETCH_REPORT) -> tuple[dict, dict]:
    """m — минуты replay.read_minutes(sym). → (новый словарь минут с заполненными днями, отчёт)."""
    ts = m["ts"]
    add = []
    per_day = {}
    for day in days:
        a = read_day(day, sym, root)
        if len(a) != 1440:
            raise DataError(f"{sym} {day}: в дневном архиве {len(a)} минут, ожидалось 1440")
        dts = a[:, 0].astype(np.int64)
        if np.isin(dts, ts).any():
            raise DataError(f"{sym} {day}: минуты дня уже есть в ряду — это не дыра")
        add.append(a)
        per_day[day] = {"minutes": int(len(a)), "first_open": float(a[0, 1]), "last_close": float(a[-1, 4])}
    checks = {}
    for day in check_days:
        a = read_day(day, sym, root)
        dts = a[:, 0].astype(np.int64)
        idx = np.searchsorted(ts, dts)
        ok = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == dts)
        if not ok.all():
            raise DataError(f"{sym} {day}: контрольный день — минут из дневного архива нет в ряду: {int((~ok).sum())}")
        ref = np.stack([m["o"][idx], m["h"][idx], m["l"][idx], m["c"][idx], m["v"][idx]], axis=1)
        diff = int(np.sum(np.any(a[:, 1:6] != ref, axis=1)))
        if diff or len(a) != 1440:
            raise DataError(f"{sym} {day}: дневной архив и месячный расходятся в {diff} минутах (минут {len(a)})")
        checks[day] = {"minutes": int(len(a)), "numeric_equal_ohlcv": int(len(a) - diff)}
    A = np.concatenate(add)
    nts = np.concatenate([ts, A[:, 0].astype(np.int64)])
    order = np.argsort(nts, kind="stable")
    out = {"ts": nts[order]}
    for k, col in (("o", 1), ("h", 2), ("l", 3), ("c", 4), ("v", 5)):
        out[k] = np.concatenate([m[k], A[:, col]])[order]
    if np.any(np.diff(out["ts"]) <= 0):
        raise DataError(f"{sym}: после вставки минуты не строго по возрастанию")
    p1 = out["ts"][out["ts"] < P1_END]
    missing_p1 = int((p1[-1] - p1[0]) // MIN + 1 - len(p1))
    if missing_p1:
        raise DataError(f"{sym}: после вставки в P1 осталось {missing_p1} пропущенных минут")
    out["p1_rows"] = int(len(p1))
    out["p2_rows"] = m["p2_rows"]
    # стыки: close минуты перед дырой против open первой вставленной и наоборот
    seams, seen = [], set()
    for day in days:
        a0 = day_ms(day)
        for left, right in ((a0 - MIN, a0), (a0 + DAY - MIN, a0 + DAY)):
            if left in seen:
                continue
            seen.add(left)
            i, j = np.searchsorted(out["ts"], [left, right])
            if i < len(out["ts"]) and j < len(out["ts"]) and out["ts"][i] == left and out["ts"][j] == right:
                seams.append({"left_utc": BE.utc(int(left)), "close_left": float(out["c"][i]),
                              "open_right": float(out["o"][j]),
                              "jump_pct": float(100 * (out["o"][j] / out["c"][i] - 1))})
    if fetch_report is not None:
        fr = json.loads(fetch_report.read_text(encoding="utf-8"))     # нет отчёта скачивания — отказ (FileNotFound)
    else:
        fr = {"per_day": {}}
    sha = {}
    for day in tuple(days) + tuple(check_days):
        p = root / sym / f"{sym}-1m-{day}.zip"
        got = BE.sha256_file(p)
        want = fr["per_day"].get(day, {}).get("sha256")
        if fetch_report is not None and want != got:
            raise DataError(f"{p.name}: sha256 {got} ≠ отчёту скачивания {want}")
        sha[str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name] = got
    valid = BE.GRID.valid_bar
    invalid = int(sum(not valid(tuple(r[1:6])) for r in A))
    rep = {"symbol": sym, "fill_days": list(days), "check_days": list(check_days), "inserted_minutes": int(len(A)),
           "invalid_inserted_minutes": invalid, "p1_rows_after": out["p1_rows"], "p1_missing_after": missing_p1,
           "per_day": per_day, "check_vs_monthly": checks, "seams": seams, "archives_sha256": sha,
           "note": "ряд только в памяти; frozen-файлы не менялись"}
    return out, rep
