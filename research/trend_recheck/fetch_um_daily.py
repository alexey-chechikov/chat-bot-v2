"""Дневные архивы 1m Binance USDⓈ-M (data.binance.vision) для дополнения §7а протокола
docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md (commit 6ed43ad): объявленная чувствительность «XRP с 5 днями из дневных
архивов» — 2022-02-26, 02-27, 02-28, 2022-04-01, 04-02 (этих минут нет в месячных архивах).

    .venv/bin/python3 -I research/trend_recheck/fetch_um_daily.py

Плюс 4 соседних дня (2022-02-25, 2022-03-01, 2022-03-31, 2022-04-03) — ТОЛЬКО для сверки: их минуты есть в
<SYM>_UM_1m_early.csv (из месячных архивов), и xrp_fill.py проверяет, что дневной архив с ними совпадает по OHLCV.

Каждый день: <имя>.zip.CHECKSUM биржи качается заново всегда и сохраняется рядом; кэш сверяется; несошедшийся кэш
откладывается в .bad и перекачивается; скачанный архив, не сошедшийся с .CHECKSUM, не записывается (вторая попытка,
потом отказ с кодом 1). Хелперы сверки — из research/atlas_data/fetch_aggtrades_daily.py (как у fetch_um_monthly.py).

Архивы — внешние недоверенные данные: backtests/um_daily/<SYM>/ (там .gitignore «*»), здесь не распаковываются и не
исполняются; существующие frozen-файлы не меняются. Итог — research/trend_recheck/out/um_daily_fetch.json.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
OUT_DIR = ROOT / "backtests" / "um_daily"
REPORT = ROOT / "research" / "trend_recheck" / "out" / "um_daily_fetch.json"
BASE = "https://data.binance.vision/data/futures/um/daily/klines"
SYM = "XRPUSDT"
FILL_DAYS = ("2022-02-26", "2022-02-27", "2022-02-28", "2022-04-01", "2022-04-02")
CHECK_DAYS = ("2022-02-25", "2022-03-01", "2022-03-31", "2022-04-03")
GITIGNORE = ("# Дневные архивы Binance UM 1m (data.binance.vision) — внешние недоверенные данные, в git не коммитятся.\n"
             "# research/trend_recheck/fetch_um_daily.py. Шаблон «*» скрывает и сам этот файл.\n*\n")


def _load(rel: str):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MON = _load("research/trend_recheck/fetch_um_monthly.py")
AGG = MON.AGG
expected_sha, sha256_file, write_atomic, quarantine = (AGG.expected_sha, AGG.sha256_file, AGG._write_atomic,
                                                       AGG._quarantine)
ACCEPTED = ("ok", "new", "refetched")


def fetch_day(out: Path, sym: str, day: str, getter=MON.http_get) -> tuple[str, str, str | None]:
    """→ (статус, пояснение, sha256 принятого архива или None). Логика — как fetch_um_monthly.fetch_month."""
    name = f"{sym}-1m-{day}.zip"
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


def main() -> int:
    out = OUT_DIR / SYM
    out.mkdir(parents=True, exist_ok=True)
    gi = OUT_DIR / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE, encoding="utf-8")
    rep = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "source": BASE, "symbol": SYM,
           "protocol_section": "7a (commit 6ed43ad)", "fill_days": list(FILL_DAYS), "check_days": list(CHECK_DAYS),
           "per_day": {}}
    failed = False
    for day in FILL_DAYS + CHECK_DAYS:
        st, why, sha = fetch_day(out, SYM, day)
        rep["per_day"][day] = {"status": st, "sha256": sha, "note": why,
                               "role": "fill" if day in FILL_DAYS else "check"}
        failed |= st not in ACCEPTED
        print(f"{SYM} {day}: {st}{' — ' + why if why else ''}")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(REPORT, json.dumps(rep, ensure_ascii=False, indent=1).encode())
    if failed:
        print("ОШИБКА: есть архивы, не сошедшиеся с .CHECKSUM или не проверенные")
        return 1
    print("все дневные архивы сверены с .CHECKSUM биржи; отчёт", REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
