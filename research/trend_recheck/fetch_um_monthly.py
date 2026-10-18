"""Месячные архивы 1m Binance USDⓈ-M (data.binance.vision) для протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md §1
(период P1 — до 2024-05-14 23:59 UTC; архив 2024-05 нужен целиком — по нему сверяется шов с <SYM>_UM_1m.csv).

    .venv/bin/python3 -I research/trend_recheck/fetch_um_monthly.py [SYM ...] [--end 2024-05]

По умолчанию ETHUSDT XRPUSDT BTCUSDT, с первого месяца, который есть в архиве символа, по --end включительно.

Первый месяц — из листинга бакета data.binance.vision (S3, с постраничной выдачей); проверяется, что месяца перед ним
нет (404 на .CHECKSUM). Листинг недоступен — месяцы перебираются с 2019-01 до первого существующего .CHECKSUM.
Месяц внутри диапазона, которого нет в листинге, всё равно запрашивается — и падает громко, если его нет.

Каждый месяц: <имя>.zip.CHECKSUM биржи качается заново всегда (и для уже скачанного архива) и сохраняется рядом —
по нему build_early.py сверяет архив ещё раз перед разбором:
  - кэш сошёлся — месяц принят без скачивания (ok);
  - кэш не сошёлся — откладывается в <имя>.zip.bad (bad2, …), архив качается заново и сверяется (refetched);
  - скачанный архив не сошёлся — не записывается, вторая попытка; не сошёлся снова — bad, код выхода 1;
  - .CHECKSUM не получен или не sha256 этого архива — unverified, код выхода 1.
Запись атомарная (временный файл + os.replace). Хелперы сверки — из research/atlas_data/fetch_aggtrades_daily.py
(тот же код, что у aggTrades, с тестами tests/research_tools/test_aggtrades_checksum.py).

Архивы — внешние недоверенные данные: лежат в backtests/um_monthly/<SYM>/ (там .gitignore «*»), здесь не
распаковываются и не исполняются. Итог — research/trend_recheck/out/um_monthly_fetch.json.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
OUT_DIR = ROOT / "backtests" / "um_monthly"
REPORT = ROOT / "research" / "trend_recheck" / "out" / "um_monthly_fetch.json"
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix={p}{m}"
SYMS = ("ETHUSDT", "XRPUSDT", "BTCUSDT")
END = "2024-05"
PROBE_FROM = "2019-01"                    # фьючерсы USDⓈ-M Binance — с 09.2019; раньше месяцев нет
ACCEPTED = ("ok", "new", "refetched")


def _load(rel: str):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AGG = _load("research/atlas_data/fetch_aggtrades_daily.py")
expected_sha, sha256_file, write_atomic, quarantine = (AGG.expected_sha, AGG.sha256_file, AGG._write_atomic,
                                                       AGG._quarantine)


def http_get(url: str, tries: int = 5) -> bytes | None:
    """Тело ответа; None — 404 (объекта нет). Прочие ошибки — повтор с паузой, потом исключение."""
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bot7"})
            return urllib.request.urlopen(req, timeout=120).read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if k == tries - 1:
                raise
        except Exception:                                   # noqa: BLE001
            if k == tries - 1:
                raise
        time.sleep(2 ** k)
    return None


def month_range(a: str, b: str) -> list[str]:
    y, m = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    out = []
    while (y, m) <= (yb, mb):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def prev_month(s: str) -> str:
    y, m = int(s[:4]), int(s[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def listed_months(sym: str) -> list[str]:
    """Месяцы, у которых в бакете лежит <SYM>-1m-YYYY-MM.zip (листинг S3, постранично через marker)."""
    prefix = f"data/futures/um/monthly/klines/{sym}/1m/"
    pat = re.compile(rf"{re.escape(prefix)}{sym}-1m-(\d{{4}}-\d{{2}})\.zip$")
    months, marker = set(), ""
    while True:
        raw = http_get(LIST.format(p=prefix, m=f"&marker={marker}" if marker else ""))
        if raw is None:
            raise RuntimeError("листинг бакета: 404")
        text = raw.decode("utf-8", "replace")
        keys = re.findall(r"<Key>([^<]+)</Key>", text)
        for k in keys:
            hit = pat.match(k)
            if hit:
                months.add(hit.group(1))
        if "<IsTruncated>true</IsTruncated>" not in text or not keys:
            break
        marker = keys[-1]
    return sorted(months)


def first_month(sym: str, end: str) -> tuple[str, str, list[str]]:
    """(первый месяц, источник, месяцы диапазона, которых нет в листинге)."""
    try:
        listed = [m for m in listed_months(sym) if m <= end]
    except Exception as exc:                                # noqa: BLE001
        print(f"{sym}: листинг недоступен ({exc}) — перебор месяцев с {PROBE_FROM}")
        listed = []
    if listed:
        first = listed[0]
        before = prev_month(first)
        if http_get(f"{BASE}/{sym}/1m/{sym}-1m-{before}.zip.CHECKSUM") is not None:
            raise RuntimeError(f"{sym}: листинг начинается с {first}, но .CHECKSUM за {before} существует")
        missing = [m for m in month_range(first, end) if m not in set(listed)]
        return first, "listing", missing
    for m in month_range(PROBE_FROM, end):
        if http_get(f"{BASE}/{sym}/1m/{sym}-1m-{m}.zip.CHECKSUM") is not None:
            return m, "probe", []
    raise RuntimeError(f"{sym}: ни одного месяца до {end}")


def fetch_month(out: Path, sym: str, month: str, getter=http_get) -> tuple[str, str, str | None]:
    """→ (статус, пояснение, sha256 принятого архива или None)."""
    name = f"{sym}-1m-{month}.zip"
    dst = out / name
    url = f"{BASE}/{sym}/1m/{name}"
    try:
        raw = getter(f"{url}.CHECKSUM")
    except Exception as exc:                                # noqa: BLE001
        return "unverified", f".CHECKSUM не скачан ({exc})", None
    if raw is None:
        return "unverified", ".CHECKSUM: 404", None
    want = expected_sha(raw, name)
    if want is None:
        return "unverified", ".CHECKSUM не похож на sha256 этого архива", None
    write_atomic(out / f"{name}.CHECKSUM", raw)
    note = ""
    if dst.exists():
        got = sha256_file(dst)
        if got == want:
            return "ok", "", want
        moved = quarantine(dst)
        note = f"кэш не сошёлся с .CHECKSUM ({got[:12]}… ≠ {want[:12]}…), отложен в {moved.name}; "
    for attempt in (1, 2):
        try:
            blob = getter(url)
        except Exception as exc:                            # noqa: BLE001
            blob, why = None, f"архив не скачан ({exc})"
        else:
            why = "архив: 404" if blob is None else ""
        if blob is not None:
            if hashlib.sha256(blob).hexdigest() == want:
                write_atomic(dst, blob)
                return ("refetched", note + "скачан заново и сверен", want) if note else ("new", "", want)
            why = f"скачанный архив не сходится с .CHECKSUM (попытка {attempt}) — не записан"
        note += why + "; "
    return "bad", note.rstrip("; "), None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    end = END
    if "--end" in argv:
        i = argv.index("--end")
        end = argv[i + 1]
        del argv[i:i + 2]
    syms = argv or list(SYMS)
    report = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "end_month": end,
              "source": BASE, "symbols": {}}
    failed = False
    for sym in syms:
        out = OUT_DIR / sym
        out.mkdir(parents=True, exist_ok=True)
        first, how, missing_listing = first_month(sym, end)
        months = month_range(first, end)
        by: dict[str, list[str]] = {k: [] for k in (*ACCEPTED, "bad", "unverified")}
        rows, total = {}, 0
        for m in months:
            st, why, sha = fetch_month(out, sym, m)
            by[st].append(m)
            rows[m] = {"status": st, "sha256": sha, "note": why}
            if st in ACCEPTED:
                total += (out / f"{sym}-1m-{m}.zip").stat().st_size
            if why:
                print(f"   {sym} {m}: {st} — {why}")
        bad = by["bad"] + by["unverified"]
        failed |= bool(bad)
        print(f"{sym}: месяцы {first}…{end} ({len(months)}, первый по {how}); сверенных архивов {total / 1e6:,.1f} МБ; "
              f"кэш сверен {len(by['ok'])}, скачано {len(by['new'])}, кэш битый — перекачан {by['refetched'] or 'нет'}; "
              f"НЕ СОШЛОСЬ/НЕ ПРОВЕРЕНО: {bad or 'нет'}; нет в листинге: {missing_listing or 'нет'}")
        report["symbols"][sym] = {"first_month": first, "first_month_source": how, "months": len(months),
                                  "missing_in_listing": missing_listing, "bytes": total,
                                  "status_counts": {k: len(v) for k, v in by.items()}, "per_month": rows}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(REPORT, json.dumps(report, ensure_ascii=False, indent=1).encode())
    if failed:
        print("ОШИБКА: есть архивы, не сошедшиеся с .CHECKSUM или не проверенные — данные НЕ готовы")
        return 1
    print("все архивы сверены с .CHECKSUM биржи; отчёт", REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
