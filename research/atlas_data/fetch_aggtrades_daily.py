"""Дневные архивы aggTrades Binance USDⓈ-M (data.binance.vision) — сделки с флагом агрессора для footprint.

Каждый день — свой zip + файл .CHECKSUM биржи (sha256 сверяется). Архивы — внешние недоверенные данные: лежат в
backtests/aggtrades/<SYM>/ (в .gitignore), читаются только как CSV. Слово оператора 14.10: «не целый архив, недели».

Ревью GPT 15.10 (docs/WEEX_GPT_REVIEW_AND_MANUAL_STRATEGIES_2026-10-15.md §2 п.7): уже скачанный zip раньше не
сверялся — битый кэш принимался молча («не сошлась: нет»). Теперь .CHECKSUM скачивается для КАЖДОГО дня, и кэш
сверяется так же, как новый архив:
  - кэш сошёлся — день принят без повторного скачивания;
  - кэш не сошёлся — файл откладывается в <имя>.zip.bad (не удаляется; читатели берут только <имя>.zip), день
    качается заново и сверяется; в отчёте — отдельной строкой с датой;
  - скачанный архив не сошёлся — не записывается (день в «не сошлась»);
  - .CHECKSUM не получен или не похож на sha256 этого архива — день «не проверен» (кэш не трогается, но не принят).
Запись zip — атомарно (временный файл + os.replace): прерванная запись не оставляет полу-архив под рабочим именем.
Код выхода 1, если хоть один день не сошёлся или не проверен.

    .venv/bin/python3 research/atlas_data/fetch_aggtrades_daily.py BTCUSDT 2026-08-19 2026-10-13
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
SHA256 = re.compile(r"[0-9a-f]{64}")
ACCEPTED = ("ok", "new", "refetched")                      # день сверен с .CHECKSUM биржи


def get(url: str) -> bytes:
    for k in range(5):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}), timeout=120).read()
        except Exception:                                   # noqa: BLE001
            if k == 4:
                raise
            time.sleep(2 ** k)


def expected_sha(raw: bytes, name: str) -> str | None:
    """sha256 из .CHECKSUM формата sha256sum («<hex>  <имя>»); None — не sha256 или сумма другого архива."""
    try:
        parts = raw.decode("ascii").split()
    except (UnicodeDecodeError, AttributeError):
        return None
    if not parts or not SHA256.fullmatch(parts[0].lower()):
        return None
    if len(parts) > 1 and Path(parts[1].lstrip("*")).name != name:
        return None
    return parts[0].lower()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_atomic(dst: Path, blob: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)                                # mkstemp создаёт 0600
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _quarantine(dst: Path) -> Path:
    """Битый кэш — в <имя>.bad (<имя>.bad2, … если уже есть): не удаляется, но и под рабочим именем не лежит."""
    bad, n = dst.with_name(dst.name + ".bad"), 1
    while bad.exists():
        n += 1
        bad = dst.with_name(f"{dst.name}.bad{n}")
    os.replace(dst, bad)
    return bad


def fetch_day(out: Path, sym: str, d: date, getter=None) -> tuple[str, str]:
    """Один день → (статус, пояснение). Статусы: ok — кэш сверен; new — скачан и сверен; refetched — кэш НЕ сошёлся,
    отложен в .bad, скачан заново и сверен; bad — архив не скачан или не сходится (не записан); unverified —
    .CHECKSUM не получен/не разобран (кэш не тронут, но не принят)."""
    getter = getter or get
    name = f"{sym}-aggTrades-{d.isoformat()}.zip"
    dst = out / name
    url = f"{BASE}/{sym}/{name}"
    try:
        want = expected_sha(getter(f"{url}.CHECKSUM"), name)
    except Exception as exc:                                # noqa: BLE001
        return "unverified", f".CHECKSUM не скачан ({exc})"
    if want is None:
        return "unverified", ".CHECKSUM не похож на sha256 этого архива"
    note = ""
    if dst.exists():
        got = sha256_file(dst)
        if got == want:
            return "ok", ""
        moved = _quarantine(dst)
        note = f"кэш не сошёлся с .CHECKSUM ({got[:12]}… ≠ {want[:12]}…), отложен в {moved.name}; "
    try:
        blob = getter(url)
    except Exception as exc:                                # noqa: BLE001
        return "bad", note + f"архив не скачан ({exc})"
    if hashlib.sha256(blob).hexdigest() != want:
        return "bad", note + "скачанный архив не сходится с .CHECKSUM — не записан"
    _write_atomic(dst, blob)
    return ("refetched", note + "скачан заново и сверен") if note else ("new", "")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    sym, a, b = argv[0], date.fromisoformat(argv[1]), date.fromisoformat(argv[2])
    out = ROOT / "backtests" / "aggtrades" / sym
    out.mkdir(parents=True, exist_ok=True)
    by: dict[str, list[str]] = {k: [] for k in (*ACCEPTED, "bad", "unverified")}
    notes, total, d = [], 0, a
    while d <= b:
        st, why = fetch_day(out, sym, d)
        by[st].append(d.isoformat())
        if why:
            notes.append(f"   {d.isoformat()}: {why}")
        if st in ACCEPTED:
            total += (out / f"{sym}-aggTrades-{d.isoformat()}.zip").stat().st_size
        d += timedelta(days=1)
    print(f"{sym}: {(b - a).days + 1} дней, сверенных архивов {total / 1e6:,.0f} МБ; кэш сверен {len(by['ok'])}, "
          f"скачано {len(by['new'])}, кэш битый — перекачан {by['refetched'] or 'нет'}; "
          f"контрольная сумма не сошлась: {by['bad'] or 'нет'}; не проверено: {by['unverified'] or 'нет'}")
    for line in notes:
        print(line)
    return 1 if by["bad"] or by["unverified"] else 0


if __name__ == "__main__":
    sys.exit(main())
