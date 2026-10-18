"""Фандинг Binance USDⓈ-M с начала истории символа для протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md §1, §3.

    .venv/bin/python3 -I research/trend_recheck/fetch_funding_full.py [SYM ...]

Загрузка — та же функция fetch() из research/manual_pullback/fetch_funding.py (публичный /fapi/v1/fundingRate,
без ключей), импортом, без копии. Выход — НОВЫЕ файлы backtests/frozen/<SYM>_funding_full.csv (в .gitignore) того
же вида (fundingTime,fundingRate,markPrice; csv.writer). Существующие <SYM>_funding.csv НЕ трогаются — их sha256
закреплён в research/manual_pullback/out/manifest.json; с ними только сверяются общие начисления.

Формализации:
  F8. Начало запроса — 2019-09-01 00:00 UTC (до запуска USDⓈ-M перпетуалов Binance), биржа отдаёт с первого начисления.
  F9. Конец — конец последней минуты существующего <SYM>_UM_1m.csv (ts последней строки + 59 999 мс), включительно.
  F10. Интервал «8 ч» — |Δ − 8 ч| ≤ 60 с (метки начислений плавают на десятки мс); всё прочее — «другой» и
      перечисляется; «пропуск» — интервал > 8 ч + 60 с.
Отчёт — research/trend_recheck/out/funding_full_<SYM>.json.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
FROZEN = ROOT / "backtests" / "frozen"
OUT = ROOT / "research" / "trend_recheck" / "out"
SYMS = ("ETHUSDT", "XRPUSDT", "BTCUSDT")
START_MS = int(datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
H8 = 8 * 3_600_000
TOL = 60_000


def _load(rel: str):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FF = _load("research/manual_pullback/fetch_funding.py")


def utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def num_equal(p: tuple[str, str], q: tuple[str, str]) -> bool:
    """Ставка и markPrice равны как числа; пустой markPrice равен только пустому."""
    if float(p[0]) != float(q[0]):
        return False
    if not p[1] or not q[1]:
        return not p[1] and not q[1]
    return float(p[1]) == float(q[1])


def last_um_ts(sym: str) -> int:
    path = FROZEN / f"{sym}_UM_1m.csv"
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 4096))
        tail = f.read().decode("ascii").strip().splitlines()
    return int(tail[-1].split(",")[0])


def main(argv: list[str] | None = None) -> int:
    syms = list(sys.argv[1:] if argv is None else argv) or list(SYMS)
    for sym in syms:
        out = FROZEN / f"{sym}_funding_full.csv"
        assert out.name != f"{sym}_funding.csv"
        last_min = last_um_ts(sym)
        end = last_min + 59_999
        rows = FF.fetch(sym, START_MS, end)
        rows = {t: v for t, v in rows.items() if START_MS <= t <= end}
        fd, tmp = tempfile.mkstemp(dir=FROZEN, prefix=f".{out.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["fundingTime", "fundingRate", "markPrice"])
                for t in sorted(rows):
                    w.writerow([t, *rows[t]])
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, out)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        ts = sorted(rows)
        deltas = [(a, b - a) for a, b in zip(ts, ts[1:])]
        hours = Counter(round(d / 3_600_000, 2) for _, d in deltas)
        eight = sum(1 for _, d in deltas if abs(d - H8) <= TOL)
        other = [{"from": utc(a), "to": utc(a + d), "hours": round(d / 3_600_000, 3)} for a, d in deltas
                 if abs(d - H8) > TOL]
        gaps = [o for o in other if o["hours"] * 3_600_000 > H8 + TOL]
        jitter = Counter(min(t % 3_600_000, 3_600_000 - t % 3_600_000) for t in ts)
        miss_mark = [t for t in ts if not rows[t][1]]
        bad_rate = [t for t in ts if not rows[t][0]]
        # сверка с существующим файлом (только чтение)
        old = FROZEN / f"{sym}_funding.csv"
        cmp = {}
        if old.exists():
            with old.open(newline="") as f:
                rd = csv.reader(f)
                next(rd)
                prev = {int(r[0]): (r[1], r[2]) for r in rd}
            common = sorted(set(prev) & set(rows))
            same = sum(1 for t in common if prev[t] == rows[t])
            num_same = sum(1 for t in common if prev[t] != rows[t] and num_equal(prev[t], rows[t]))
            cmp = {"file": str(old.relative_to(ROOT)), "sha256": sha(old), "rows": len(prev), "common": len(common),
                   "identical": same, "numeric_equal_format_diff": num_same,
                   "different": len(common) - same - num_same,
                   "only_in_existing": len(set(prev) - set(rows)),
                   "only_in_existing_inside_new_range": sum(1 for t in set(prev) - set(rows) if ts[0] <= t <= ts[-1])}
        rep = {
            "symbol": sym, "file": str(out.relative_to(ROOT)), "sha256": sha(out), "rows": len(ts),
            "request_from_utc": utc(START_MS), "request_to_utc": utc(end),
            "first_utc": utc(ts[0]), "last_utc": utc(ts[-1]), "first_ms": ts[0], "last_ms": ts[-1],
            "um_last_minute_utc": utc(last_min),
            "intervals_hours": {str(k): v for k, v in sorted(hours.items())},
            "intervals_8h": eight, "intervals_other": len(other), "other_list": other[:200],
            "gaps_over_8h": len(gaps), "gaps_list": gaps[:200],
            "jitter_ms_from_hour": {"max": max(jitter) if jitter else None,
                                    "exact_hour": jitter.get(0, 0), "nonzero": len(ts) - jitter.get(0, 0)},
            "missing_markPrice": len(miss_mark),
            "missing_markPrice_first_utc": utc(miss_mark[0]) if miss_mark else None,
            "missing_markPrice_last_utc": utc(miss_mark[-1]) if miss_mark else None,
            "missing_rate": len(bad_rate),
            "vs_existing_funding_csv": cmp,
        }
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"funding_full_{sym}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
        print(f"{sym}: {len(ts)} начислений {rep['first_utc']} … {rep['last_utc']} UTC; интервалы 8ч {eight}, другие "
              f"{len(other)} (из них пропусков >8ч {len(gaps)}); часы {rep['intervals_hours']}; без markPrice "
              f"{len(miss_mark)} ({rep['missing_markPrice_first_utc']} … {rep['missing_markPrice_last_utc']}); "
              f"сверка с {old.name}: {cmp.get('identical')}/{cmp.get('common')} совпадают, "
              f"различий {cmp.get('different')}")
        print(f"   {out} sha256 {rep['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
