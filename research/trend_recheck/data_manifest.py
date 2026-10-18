"""Манифест замороженных входных данных протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md (§1, §7).

    .venv/bin/python3 -I research/trend_recheck/data_manifest.py

Читает отчёты fetch_um_monthly.py / build_early.py / fetch_funding_full.py из research/trend_recheck/out/,
заново считает sha256 и проверки сетки по самим файлам (P1 — <SYM>_UM_1m_early.csv, P2 — существующий
<SYM>_UM_1m.csv, фандинг — <SYM>_funding_full.csv) и пишет research/trend_recheck/out/data_manifest.json.
Сеть не нужна. Ничего, кроме манифеста, не пишет.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
FROZEN = ROOT / "backtests" / "frozen"
OUT = ROOT / "research" / "trend_recheck" / "out"
SYMS = ("ETHUSDT", "XRPUSDT", "BTCUSDT")
PROTOCOL = "docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md"
CUT = 1715731200000
MIN = 60_000
H4 = 4 * 3_600_000
PINNED = ROOT / "research" / "manual_pullback" / "out" / "manifest.json"
# справка check_api_start.py 15.10: первая минута REST /fapi/v1/klines (startTime=0); 2019-архивов нет (404)
API_FIRST_MINUTE = {"ETHUSDT": "2019-11-27 07:45", "XRPUSDT": "2020-01-06 08:21", "BTCUSDT": "2019-09-08 17:57"}
# справка check_xrp_gaps.py 15.10: дыры XRP — только в месячных архивах; НЕ заполнены (протокол §1 и задание)
ARCHIVE_HOLES = {"XRPUSDT": "2022-02-26…2022-02-28 и 2022-04-01…2022-04-02 (7 200 минут, 30 пустых 4h-свечей) нет в "
                            "месячных архивах 2022-02 и 2022-04; REST /fapi/v1/klines отдаёт по 1 440 минут за каждый из "
                            "5 дней, дневные архивы data.binance.vision с .CHECKSUM за эти дни существуют. Не заполнено: "
                            "источник P1 по протоколу — месячные архивы, пропуски не заполняются. Решение — за "
                            "автором протокола до расчётов."}
SCRIPTS = ("research/trend_recheck/fetch_um_monthly.py", "research/trend_recheck/build_early.py",
           "research/trend_recheck/fetch_funding_full.py", "research/trend_recheck/data_manifest.py",
           "research/trend_recheck/check_api_start.py", "research/trend_recheck/check_xrp_gaps.py",
           "tests/research_tools/test_trend_recheck_data.py",
           "research/atlas_data/fetch_aggtrades_daily.py", "scripts/ohlc_grid.py",
           "research/manual_pullback/fetch_funding.py", "research/atlas_data/fetch_binance_um_1m.py")
FORMALIZATIONS = [
    "F0. P1 начинается с первой минуты первого месячного архива символа (протокол: источник P1 — месячные архивы с "
    ".CHECKSUM). У ETH и BTC REST /fapi/v1/klines знает минуты раньше (API_FIRST_MINUTE), но месячных и дневных "
    "архивов 1m за 2019 нет (404) — эти минуты в P1 не входят и не докачиваются из REST.",
    "F1. Архив отвечает только за свой месяц: строки вне месяца архива не пишутся и считаются.",
    "F2. Строки вне сетки k·60 000 мс не пишутся и считаются.",
    "F3. Дубль метки с теми же полями — одна строка, дубль считается; дубль с другими полями — отказ.",
    "F4. Невалидный OHLCV (scripts/ohlc_grid.valid_bar) пишется как есть и перечисляется; полнота 4h — при расчёте.",
    "F5. open_time — миллисекунды: 13 знаков и close_time − open_time = 59 999, иначе отказ.",
    "F6. Шов: 2024-05-15 00:00 … 2024-05-31 23:59 архива 2024-05 против существующего <SYM>_UM_1m.csv по всем "
    "полям; расхождение — громко, код выхода 3; существующий файл не меняется.",
    "F7. Запись чисел <SYM>_UM_1m_early.csv — как в существующем <SYM>_UM_1m.csv (REST API): колонки — поля архива "
    "0,1,2,3,4,5,9,8, CRLF через csv.writer; у каждой колонки ненулевые значения с одним числом знаков, нуль объёма — "
    "«0». Архивы 2020-01 и 2023 г. пишут целые значения без дробной части («7172», «42») — дополняются нулями справа; "
    "нуль — «0». Значение не меняется, округления нет; больше знаков, чем в существующем файле, — отказ. Счётчики — "
    "padded_integer_strings_F7 в early_<SYM>.json. На шве 2024-05 строки совпадают байт в байт.",
    "F8. Фандинг запрашивается с 2019-09-01 00:00 UTC; биржа отдаёт с первого начисления символа.",
    "F9. Конец фандинга — конец последней минуты существующего <SYM>_UM_1m.csv включительно.",
    "F10. Интервал фандинга «8 ч» — |Δ − 8 ч| ≤ 60 с; остальное перечисляется; пропуск — Δ > 8 ч + 60 с.",
]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc(ms: int | None, sec: bool = False) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S" if sec else "%Y-%m-%d %H:%M")


def _load(rel: str):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


valid_bar = _load("scripts/ohlc_grid.py").valid_bar


def scan_minutes(path: Path, until: int | None = None) -> dict:
    """Проверки сетки по файлу минут: сортировка, дубли, вне сетки, пропуски, валидность, 4h-свечи (UTC 00)."""
    rows = dup = off = unsorted = invalid = zero_vol = 0
    runs: list[tuple[int, int]] = []           # серии минут с нулевым объёмом (начало, длина) — техработы биржи
    run_a = run_n = 0
    gaps: list[tuple[int, int]] = []
    h4: Counter = Counter()
    first = last = prev = None
    with path.open(newline="") as f:
        rd = csv.reader(f)
        head = next(rd)
        for r in rd:
            ts = int(r[0])
            if until is not None and ts >= until:
                break
            rows += 1
            if ts % MIN:
                off += 1
                continue
            if prev is not None:
                if ts == prev:
                    dup += 1
                    continue
                if ts < prev:
                    unsorted += 1
                    continue
                if ts - prev > MIN:
                    gaps.append((prev + MIN, (ts - prev) // MIN - 1))
            ok = valid_bar(r[1:6])
            invalid += not ok
            if ok:
                h4[ts // H4 * H4] += 1
            if float(r[5]) == 0:
                zero_vol += 1
                if run_n and ts == run_a + run_n * MIN:
                    run_n += 1
                else:
                    if run_n:
                        runs.append((run_a, run_n))
                    run_a, run_n = ts, 1
            first = ts if first is None else first
            last = prev = ts
    if run_n:
        runs.append((run_a, run_n))
    n4 = range(first // H4 * H4, last // H4 * H4 + H4, H4)
    full = sum(1 for b in n4 if h4.get(b, 0) == 240)
    empty = sum(1 for b in n4 if h4.get(b, 0) == 0)
    return {"header": head, "rows": rows, "first_utc": utc(first), "last_utc": utc(last), "first_ms": first,
            "last_ms": last, "duplicates": dup, "off_grid": off, "unsorted": unsorted, "invalid_ohlcv": invalid,
            "missing_minutes": sum(k for _, k in gaps), "gap_ranges": len(gaps),
            "largest_gaps": [{"from_utc": utc(a), "to_utc": utc(a + (k - 1) * MIN), "minutes": k}
                             for a, k in sorted(gaps, key=lambda g: -g[1])[:10]],
            "zero_volume_minutes": zero_vol, "zero_volume_runs": len(runs),
            "longest_zero_volume_runs": [{"from_utc": utc(a), "to_utc": utc(a + (k - 1) * MIN), "minutes": k}
                                         for a, k in sorted(runs, key=lambda g: -g[1])[:5]],
            "h4_candles_utc00": {"total": len(n4), "full_240_valid": full, "partial": len(n4) - full - empty,
                                 "empty": empty,
                                 "last_candle_full": h4.get(last // H4 * H4, 0) == 240}}


def funding_cov(sym: str, p1_first: int, p2_last: int) -> dict:
    path = FROZEN / f"{sym}_funding_full.csv"
    with path.open(newline="") as f:
        rd = csv.reader(f)
        next(rd)
        rows = [(int(r[0]), r[1], r[2]) for r in rd]
    rep = json.loads((OUT / f"funding_full_{sym}.json").read_text())
    inside = [r for r in rows if p1_first <= r[0] <= p2_last + MIN - 1]
    p1 = [r for r in inside if r[0] < CUT]
    p2 = [r for r in inside if r[0] >= CUT]
    zero_mark = sum(1 for r in rows if r[2] and float(r[2]) == 0)
    return {"file": str(path.relative_to(ROOT)), "sha256": sha(path), "rows": len(rows),
            "first_utc": utc(rows[0][0], True), "last_utc": utc(rows[-1][0], True),
            "settlements_P1": len(p1), "settlements_P2": len(p2),
            "missing_markPrice_P1": sum(1 for r in p1 if not r[2]),
            "missing_markPrice_P2": sum(1 for r in p2 if not r[2]),
            "zero_markPrice": zero_mark,
            "missing_markPrice_range_utc": [rep["missing_markPrice_first_utc"], rep["missing_markPrice_last_utc"]],
            "intervals_hours": rep["intervals_hours"], "intervals_other": rep["intervals_other"],
            "gaps_over_8h": rep["gaps_over_8h"], "jitter_ms_from_hour": rep["jitter_ms_from_hour"],
            "first_settlement_after_P1_start": utc(min(r[0] for r in rows if r[0] > p1_first), True),
            "funding_starts_before_P1_first_minute": rows[0][0] <= p1_first,
            "covers_to_P2_last_minute": rows[-1][0] <= p2_last + MIN - 1
            and p2_last + MIN - 1 - rows[-1][0] < 8 * 3_600_000 + MIN,
            "vs_existing_funding_csv": rep["vs_existing_funding_csv"],
            "note": "нет markPrice → по протоколу §3 берётся close минуты расчёта"}


def main() -> int:
    pinned = json.loads(PINNED.read_text())["inputs"] if PINNED.exists() else {}
    fetch = json.loads((OUT / "um_monthly_fetch.json").read_text())
    commit = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h", "--", PROTOCOL],
                            capture_output=True, text=True).stdout.strip()
    man = {"protocol": PROTOCOL, "protocol_commit": commit, "protocol_sha256": sha(ROOT / PROTOCOL),
           "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
           "p1_end_exclusive_utc": utc(CUT), "formalizations": FORMALIZATIONS,
           "scripts_sha256": {s: sha(ROOT / s) for s in SCRIPTS},
           "minutes": {}, "funding": {}}
    ok = True
    for sym in SYMS:
        early = json.loads((OUT / f"early_{sym}.json").read_text())
        p1_path = FROZEN / f"{sym}_UM_1m_early.csv"
        p2_path = FROZEN / f"{sym}_UM_1m.csv"
        p1 = scan_minutes(p1_path)
        p2 = scan_minutes(p2_path)
        p1_sha, p2_sha = sha(p1_path), sha(p2_path)
        if p1_sha != early["sha256"]:
            print(f"!!! {sym}: sha256 P1 изменился после build_early ({p1_sha} ≠ {early['sha256']})")
            ok = False
        seam_gap = (p2["first_ms"] - p1["last_ms"]) // MIN - 1
        fi = fetch["symbols"][sym]
        arch = {"dir": f"backtests/um_monthly/{sym}/", "first_month": fi["first_month"],
                "first_month_source": fi["first_month_source"], "months": fi["months"],
                "status_counts": fi["status_counts"], "missing_in_listing": fi["missing_in_listing"],
                "bytes": fi["bytes"],
                "zip_sha256": {m: r["sha256"] for m, r in sorted(fi["per_month"].items())}}
        pin = pinned.get(sym, {})
        man["minutes"][sym] = {
            "api_first_minute_utc": API_FIRST_MINUTE[sym],
            "archive_holes_note": ARCHIVE_HOLES.get(sym),
            "archives": arch,
            "P1_early": {"file": str(p1_path.relative_to(ROOT)), "sha256": p1_sha, **p1,
                         "gap_size_buckets": early["gap_size_buckets"],
                         "missing_minutes_at_seam_before_2024-05-15": early["missing_minutes_at_seam_before_2024-05-15"],
                         "dropped": {"duplicates_identical": early["duplicates_identical_dropped"],
                                     "off_grid": early["off_grid_dropped"],
                                     "outside_month": early["outside_month_dropped"]},
                         "invalid_sample": early["invalid_sample"],
                         "decimals_written": early["decimals_written"],
                         "padded_integer_strings_F7": early["padded_integer_strings_F7"],
                         "line_endings": "CRLF"},
            "P2_existing": {"file": str(p2_path.relative_to(ROOT)), "sha256": p2_sha, **p2,
                            "pinned_sha256_manual_pullback": pin.get("sha256"),
                            "same_as_pinned": pin.get("sha256") == p2_sha if pin else None},
            "join": {"P1_last_utc": p1["last_utc"], "P2_first_utc": p2["first_utc"],
                     "missing_minutes_between": seam_gap,
                     "continuous_no_gap_no_overlap": seam_gap == 0},
            "seam_2024_05_15_31": early["seam"],
        }
        ok &= bool(early["seam"]["ok"]) and p1["duplicates"] == 0 and p1["off_grid"] == 0 and p1["unsorted"] == 0
        man["funding"][sym] = funding_cov(sym, p1["first_ms"], p2["last_ms"])
        print(f"{sym}: P1 {p1['rows']:,} строк {p1['first_utc']} … {p1['last_utc']}, пропущено {p1['missing_minutes']:,}; "
              f"P2 {p2['rows']:,} строк {p2['first_utc']} … {p2['last_utc']}, пропущено {p2['missing_minutes']:,}; "
              f"между P1 и P2 пропущено {seam_gap}; шов ok={early['seam']['ok']}")
    (OUT / "data_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
    print("манифест", OUT / "data_manifest.json", "sha256", sha(OUT / "data_manifest.json"))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
