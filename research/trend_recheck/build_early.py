"""Ранние минуты P1 для протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md §1 — из месячных архивов
backtests/um_monthly/<SYM>/ (скачивает и сверяет research/trend_recheck/fetch_um_monthly.py).

    .venv/bin/python3 -I research/trend_recheck/build_early.py [SYM ...]

Выход: backtests/frozen/<SYM>_UM_1m_early.csv (в .gitignore) — те же колонки, порядок, запись чисел и окончания
строк (CRLF, csv.writer), что у backtests/frozen/<SYM>_UM_1m.csv (research/atlas_data/fetch_binance_um_1m.py):
ts,open,high,low,close,volume,taker_buy,trades = поля архива 0,1,2,3,4,5,9,8 как строки, без пересчёта (кроме F7).
Минуты строго до 2024-05-15 00:00 UTC. Пропуски не заполняются. Отчёт — research/trend_recheck/out/early_<SYM>.json.

Перед разбором каждый архив ещё раз сверяется с сохранённым рядом .CHECKSUM биржи (не сошёлся — отказ).
Архив читается только как CSV из этого скрипта; на диск не распаковывается.

Формализации (выбраны до расчётов протокола, записаны здесь и в отчёте):
  F1. Архив отвечает только за свой месяц: строки с open_time вне месяца архива не пишутся и считаются.
  F2. Строки вне сетки k·60 000 мс не пишутся и считаются (протокол §1: «только минуты k·60 000 мс»).
  F3. Дубль метки с теми же полями — пишется одна строка, дубль считается; дубль с другими полями — отказ
      (файл не пишется).
  F4. Строка с невалидным OHLCV (критерий scripts/ohlc_grid.valid_bar: конечные числа, 0 < low ≤ min(open, close),
      high ≥ max(open, close), объём ≥ 0) пишется как есть и перечисляется в отчёте: сырые данные не правятся,
      полнота 4h-свечи (240 валидных минут) решается при расчёте.
  F5. Единица open_time — миллисекунды: 1e12 ≤ open_time < 1e13 и close_time − open_time = 59 999; иначе отказ.
  F6. Шов: минуты 2024-05-15 00:00 … 2024-05-31 23:59 из архива 2024-05 сверяются с существующим <SYM>_UM_1m.csv
      по всем полям; «совпадает» = строки равны; «формат» = строки разные, числа равны; иначе «расхождение».
      Любое расхождение или минута только с одной стороны — громко и код выхода 3 (существующий файл не меняется).
  F7. Запись чисел — как в существующем <SYM>_UM_1m.csv (ответы REST API): у каждой колонки open…taker_buy ненулевые
      значения имеют одно число знаков после точки, а нуль записан одним способом («0» у объёма); это проверяется по
      всему существующему файлу, разнобой — отказ. Часть архивов (2020-01, 2023 г.) пишет целые значения без дробной
      части («7172» вместо «7172.00», объём «42» вместо «42.000») — такие строки дополняются нулями справа до этого
      числа знаков; нуль записывается так же, как в существующем файле. Значение не меняется, округления нет; строка с
      БОЛЬШИМ числом знаков или не в виде цифр с точкой — отказ. trades — целое, как есть. Счётчики — в отчёте.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
ARCH = ROOT / "backtests" / "um_monthly"
FROZEN = ROOT / "backtests" / "frozen"
OUT = ROOT / "research" / "trend_recheck" / "out"
SYMS = ("ETHUSDT", "XRPUSDT", "BTCUSDT")
CUT = 1715731200000                      # 2024-05-15 00:00 UTC — начало P2 и существующих <SYM>_UM_1m.csv
SEAM_END = 1717200000000                 # 2024-06-01 00:00 UTC
MIN = 60_000
H4 = 4 * 3_600_000
HEADER = ["ts", "open", "high", "low", "close", "volume", "taker_buy", "trades"]
ARCH_HEADER = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
               "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
PICK = (0, 1, 2, 3, 4, 5, 9, 8)          # → ts,open,high,low,close,volume,taker_buy,trades


def _load(rel: str):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GRID = _load("scripts/ohlc_grid.py")
AGG = _load("research/atlas_data/fetch_aggtrades_daily.py")
valid_bar, expected_sha, sha256_file = GRID.valid_bar, AGG.expected_sha, AGG.sha256_file


class DataError(RuntimeError):
    pass


def utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def month_bounds(month: str) -> tuple[int, int]:
    y, m = int(month[:4]), int(month[5:7])
    a = datetime(y, m, 1, tzinfo=timezone.utc)
    b = datetime(y + 1, 1, 1, tzinfo=timezone.utc) if m == 12 else datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return int(a.timestamp() * 1000), int(b.timestamp() * 1000)


def decimals(s: str) -> int:
    return len(s) - s.index(".") - 1 if "." in s else 0


NUM = re.compile(r"\d+(\.\d+)?")
INT = re.compile(r"\d+")


def existing_style(sym: str) -> dict[str, dict]:
    """Запись чисел колонок open…taker_buy существующего <SYM>_UM_1m.csv: ненулевые значения — одно число знаков
    после точки на колонку; нули — одна запись на колонку (у API Binance нулевой объём — «0»). Разнобой — отказ."""
    dec = {c: Counter() for c in HEADER[1:7]}
    zero = {c: Counter() for c in HEADER[1:7]}
    with (FROZEN / f"{sym}_UM_1m.csv").open(newline="") as f:
        rd = csv.reader(f)
        if next(rd) != HEADER:
            raise DataError(f"{sym}: шапка существующего файла не {HEADER}")
        for r in rd:
            for c, s in zip(HEADER[1:7], r[1:7]):
                if not NUM.fullmatch(s):
                    raise DataError(f"{sym}: в существующем файле число вида {s!r} ({c})")
                if float(s) == 0:
                    zero[c][s] += 1
                else:
                    dec[c][decimals(s)] += 1
    out = {}
    for c in HEADER[1:7]:
        if len(dec[c]) != 1 or len(zero[c]) > 1:
            raise DataError(f"{sym}: в существующем файле у {c} разная запись: знаков {dict(dec[c])}, нули {dict(zero[c])}")
        d = next(iter(dec[c]))
        out[c] = {"decimals": d, "zero": next(iter(zero[c])) if zero[c] else ("0." + "0" * d if d else "0"),
                  "zero_seen": dict(zero[c])}
    return out


def normalize(r: tuple[str, ...], style: dict[str, dict], padded: Counter, where: str) -> tuple[str, ...]:
    """F7: ненулевое — дополнить нулями справа до числа знаков существующего файла (больше знаков — отказ);
    нуль — записать, как нуль записан в существующем файле; не цифры с точкой — отказ."""
    out = [r[0]]
    for c, s in zip(HEADER[1:7], r[1:7]):
        if not NUM.fullmatch(s):
            raise DataError(f"{where}: {c}={s!r} — не цифры с точкой")
        want = style[c]["decimals"]
        if float(s) == 0:
            if s != style[c]["zero"]:
                s = style[c]["zero"]
                padded[f"{c}:zero"] += 1
            out.append(s)
            continue
        d = decimals(s)
        if d > want:
            raise DataError(f"{where}: {c}={s!r} — знаков больше, чем в существующем файле ({want})")
        if d < want:
            s = (s if "." in s else s + ".") + "0" * (want - d)
            padded[c] += 1
        out.append(s)
    if not INT.fullmatch(r[7]):
        raise DataError(f"{where}: trades={r[7]!r} — не целое")
    out.append(r[7])
    return tuple(out)


def read_archive(path: Path, sym: str, month: str) -> tuple[list[tuple[int, tuple[str, ...]]], dict]:
    """Строки архива → [(ts, (ts, open, high, low, close, volume, taker_buy, trades) как строки)], статистика.
    Отказ (DataError): сумма не сходится с .CHECKSUM, чужой состав архива, неизвестная шапка, не 12 полей,
    не миллисекунды, нечисловая строка не первой строкой."""
    name = path.name
    ck = path.with_name(name + ".CHECKSUM")
    if not ck.exists():
        raise DataError(f"{name}: нет сохранённого .CHECKSUM")
    want = expected_sha(ck.read_bytes(), name)
    if want is None:
        raise DataError(f"{name}: .CHECKSUM не разобран")
    got = sha256_file(path)
    if got != want:
        raise DataError(f"{name}: sha256 {got} ≠ .CHECKSUM {want}")
    lo, hi = month_bounds(month)
    st = Counter()
    rows: list[tuple[int, tuple[str, ...]]] = []
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) != 1 or infos[0].filename != f"{sym}-1m-{month}.csv":
            raise DataError(f"{name}: состав архива {[i.filename for i in infos]}")
        with z.open(infos[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="ascii", newline="")
            for i, f in enumerate(csv.reader(text)):
                if not f:
                    st["empty_lines"] += 1
                    continue
                if not f[0].strip().isdigit():
                    if i == 0 and [x.strip() for x in f] == ARCH_HEADER:
                        st["header"] = 1
                        continue
                    raise DataError(f"{name}: строка {i + 1} не числовая: {f[:3]}")
                if len(f) != 12:
                    raise DataError(f"{name}: строка {i + 1}: {len(f)} полей вместо 12")
                ts, ct = int(f[0]), int(f[6])
                if not (10 ** 12 <= ts < 10 ** 13 and ct - ts == MIN - 1):
                    raise DataError(f"{name}: строка {i + 1}: open_time {ts}, close_time {ct} — не миллисекунды "
                                    f"(ожидалось 13 знаков и close_time − open_time = 59999)")
                if not (lo <= ts < hi):
                    st["outside_month"] += 1
                    continue
                if ts % MIN:
                    st["off_grid"] += 1
                    continue
                rows.append((ts, tuple(f[k].strip() for k in PICK)))
    st["rows_in"] = len(rows)
    srt = sorted(rows, key=lambda r: r[0])
    st["unsorted"] = int(srt != rows)
    return srt, dict(st)


def months_of(sym: str) -> list[str]:
    rep = json.loads((OUT / "um_monthly_fetch.json").read_text())
    info = rep["symbols"][sym]
    bad = [m for m, r in info["per_month"].items() if r["status"] not in ("ok", "new", "refetched")]
    if bad:
        raise DataError(f"{sym}: месяцы не сверены при скачивании: {bad}")
    return sorted(info["per_month"])


def build(sym: str) -> tuple[dict, int]:
    months = months_of(sym)
    want_dec = existing_style(sym)
    padded: Counter = Counter()
    out = FROZEN / f"{sym}_UM_1m_early.csv"
    seam_rows: dict[int, tuple[str, ...]] = {}
    gaps: list[tuple[int, int]] = []           # (первая пропущенная минута, число пропущенных)
    invalid: list[dict] = []
    dup_same = 0
    stats = Counter()
    dec = {c: Counter() for c in HEADER[1:7]}
    h4: Counter = Counter()                    # 4h-свеча (UTC 00 + n·4h) → валидных минут
    prev = None
    first = last = None
    n = 0
    fd, tmp = tempfile.mkstemp(dir=FROZEN, prefix=f".{out.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as fh:
            w = csv.writer(fh)                 # lineterminator \r\n — как у существующего <SYM>_UM_1m.csv
            w.writerow(HEADER)
            for m in months:
                rows, st = read_archive(ARCH / sym / f"{sym}-1m-{m}.zip", sym, m)
                for k, v in st.items():
                    if isinstance(v, int):
                        stats[k] += v
                for ts, r in rows:
                    r = normalize(r, want_dec, padded, f"{sym} {utc(ts)} (архив {m})")
                    if ts >= CUT:
                        if ts < SEAM_END:
                            if ts in seam_rows and seam_rows[ts] != r:
                                raise DataError(f"{sym}: конфликтующий дубль {utc(ts)} в архиве {m}")
                            seam_rows[ts] = r
                        continue
                    if prev is not None and ts == prev[0]:
                        if r != prev[1]:
                            raise DataError(f"{sym}: конфликтующий дубль {utc(ts)} в архиве {m}: {prev[1]} ≠ {r}")
                        dup_same += 1
                        continue
                    if prev is not None and ts - prev[0] > MIN:
                        gaps.append((prev[0] + MIN, (ts - prev[0]) // MIN - 1))
                    ok = valid_bar(r[1:6])
                    try:
                        tb, tr = float(r[6]), int(r[7])
                        aux_ok = math.isfinite(tb) and tb >= 0 and tr >= 0
                    except ValueError:
                        aux_ok = False
                    if not ok or not aux_ok:
                        invalid.append({"ts": utc(ts), "row": list(r), "ohlcv_valid": ok, "taker_trades_valid": aux_ok})
                    if ok:
                        h4[ts // H4 * H4] += 1
                    for c, s in zip(HEADER[1:7], r[1:7]):
                        dec[c][decimals(s)] += 1
                    w.writerow(r)
                    n += 1
                    first = ts if first is None else first
                    last = ts
                    prev = (ts, r)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    # шов P1 → P2: последняя минута P1 должна быть 2024-05-14 23:59
    tail_missing = (CUT - last) // MIN - 1 if last is not None else None
    if tail_missing:
        gaps.append((last + MIN, tail_missing))
    total_missing = sum(g[1] for g in gaps)
    span = (last - first) // MIN + 1
    buckets = Counter()
    for _, k in gaps:
        buckets["1" if k == 1 else "2-5" if k <= 5 else "6-60" if k <= 60 else "61-1440" if k <= 1440 else ">1440"] += 1
    largest = sorted(gaps, key=lambda g: -g[1])[:15]
    first4 = first // H4 * H4
    all4 = range(first4, CUT, H4)
    full4 = sum(1 for b in all4 if h4.get(b, 0) == 240)
    empty4 = sum(1 for b in all4 if h4.get(b, 0) == 0)
    partial4 = len(all4) - full4 - empty4

    seam = seam_check(sym, seam_rows)
    rep = {
        "symbol": sym,
        "file": str(out.relative_to(ROOT)),
        "sha256": sha256_file(out),
        "bytes": out.stat().st_size,
        "rows": n,
        "first_utc": utc(first), "last_utc": utc(last),
        "first_ms": first, "last_ms": last,
        "archives": {"first_month": months[0], "last_month": months[-1], "count": len(months)},
        "grid_span_minutes": span,
        "missing_minutes": total_missing,
        "missing_minutes_inside_span": total_missing - (tail_missing or 0),
        "missing_minutes_at_seam_before_2024-05-15": tail_missing or 0,
        "gap_ranges": len(gaps),
        "gap_size_buckets": dict(buckets),
        "largest_gaps": [{"from_utc": utc(a), "to_utc": utc(a + (k - 1) * MIN), "minutes": k} for a, k in largest],
        "duplicates_identical_dropped": dup_same,
        "off_grid_dropped": stats.get("off_grid", 0),
        "outside_month_dropped": stats.get("outside_month", 0),
        "archives_with_header": stats.get("header", 0),
        "archives_unsorted": stats.get("unsorted", 0),
        "invalid_rows": len(invalid),
        "invalid_sample": invalid[:20],
        "decimals_written": {c: dict(v) for c, v in dec.items()},
        "number_style_existing_file": want_dec,
        "padded_integer_strings_F7": dict(padded),
        "h4_candles_utc00": {"total": len(all4), "full_240_valid": full4, "partial": partial4, "empty": empty4},
        "line_endings": "CRLF (csv.writer), как у существующего файла",
        "seam": seam,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"early_{sym}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep, (3 if not seam["ok"] else 0)


def seam_check(sym: str, arch: dict[int, tuple[str, ...]]) -> dict:
    """Минуты [2024-05-15, 2024-06-01) из архива 2024-05 против существующего <SYM>_UM_1m.csv (не меняется)."""
    path = FROZEN / f"{sym}_UM_1m.csv"
    raw_head = path.open("rb").readline()
    cur: dict[int, tuple[str, ...]] = {}
    first_cur = None
    dec = {c: Counter() for c in HEADER[1:7]}
    with path.open(newline="") as f:
        rd = csv.reader(f)
        head = next(rd)
        for r in rd:
            ts = int(r[0])
            first_cur = ts if first_cur is None else first_cur
            if ts < SEAM_END:
                cur[ts] = tuple(r)
                for c, s in zip(HEADER[1:7], r[1:7]):
                    dec[c][decimals(s)] += 1
            else:
                break
    both = sorted(set(arch) & set(cur))
    same = fmt = diff = 0
    maxabs = {c: 0.0 for c in HEADER[1:]}
    field_diff = Counter()
    sample = []
    for ts in both:
        a, b = arch[ts], cur[ts]
        if a == b:
            same += 1
            continue
        num_eq = True
        for c, x, y in zip(HEADER[1:], a[1:], b[1:]):
            dx = abs(float(x) - float(y))
            maxabs[c] = max(maxabs[c], dx)
            if dx != 0:
                num_eq = False
                field_diff[c] += 1
        if num_eq:
            fmt += 1
        else:
            diff += 1
            if len(sample) < 10:
                sample.append({"ts": utc(ts), "archive": list(a), "existing": list(b)})
    only_a = sorted(set(arch) - set(cur))
    only_c = sorted(set(cur) - set(arch))
    ohlcv_diff = sum(field_diff[c] for c in HEADER[1:6])
    ok = (diff == 0 and not only_a and not only_c and first_cur == CUT and head == HEADER)
    return {
        "existing_file": str(path.relative_to(ROOT)),
        "existing_sha256": sha256_file(path),
        "existing_header_equal": head == HEADER,
        "existing_header_bytes": raw_head.decode("ascii", "replace"),
        "existing_first_utc": utc(first_cur) if first_cur is not None else None,
        "existing_starts_2024-05-15": first_cur == CUT,
        "window_utc": [utc(CUT), utc(SEAM_END - MIN)],
        "minutes_archive": len(arch), "minutes_existing": len(cur), "minutes_both": len(both),
        "identical": same, "format_only": fmt, "different": diff,
        "different_by_field": dict(field_diff), "ohlcv_field_differences": ohlcv_diff,
        "max_abs_diff": maxabs,
        "only_in_archive": [utc(t) for t in only_a[:20]], "only_in_archive_count": len(only_a),
        "only_in_existing": [utc(t) for t in only_c[:20]], "only_in_existing_count": len(only_c),
        "diff_sample": sample,
        "existing_decimals_in_window": {c: dict(v) for c, v in dec.items()},
        "ok": ok,
    }


def main(argv: list[str] | None = None) -> int:
    syms = list(sys.argv[1:] if argv is None else argv) or list(SYMS)
    code = 0
    for sym in syms:
        try:
            rep, c = build(sym)
        except DataError as exc:
            print(f"ОТКАЗ {sym}: {exc}")
            code = max(code, 1)
            continue
        s = rep["seam"]
        print(f"{sym}: {rep['rows']:,} минут {rep['first_utc']} … {rep['last_utc']} UTC, пропущено {rep['missing_minutes']:,} "
              f"в {rep['gap_ranges']} дырах (крупнейшая {rep['largest_gaps'][0]['minutes'] if rep['largest_gaps'] else 0}), "
              f"невалидных {rep['invalid_rows']}, дублей {rep['duplicates_identical_dropped']}, вне сетки "
              f"{rep['off_grid_dropped']}, вне месяца {rep['outside_month_dropped']}; 4h: {rep['h4_candles_utc00']}")
        sty = {c: (v["decimals"], v["zero"]) for c, v in rep["number_style_existing_file"].items()}
        print(f"   запись как в существующем файле (знаков, нуль) {sty}; записано знаков {rep['decimals_written']}; "
              f"дополнено нулями (F7) {rep['padded_integer_strings_F7']}")
        print(f"   sha256 {rep['sha256']}")
        print(f"   шов 15–31.05.2024: общих {s['minutes_both']:,}, совпадает {s['identical']:,}, только формат "
              f"{s['format_only']}, РАСХОДИТСЯ {s['different']} (по полям {s['different_by_field']}), только в архиве "
              f"{s['only_in_archive_count']}, только в файле {s['only_in_existing_count']}; макс. |Δ| {s['max_abs_diff']}")
        if not s["ok"]:
            print(f"   !!! ШОВ НЕ СОШЁЛСЯ ({sym}) — см. research/trend_recheck/out/early_{sym}.json, diff_sample")
        code = max(code, c)
    return code


if __name__ == "__main__":
    sys.exit(main())
