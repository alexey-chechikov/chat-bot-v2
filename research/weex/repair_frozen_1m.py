"""Перекачка испорченных минут в backtests/frozen/<SYM>_1m_2y.csv с Binance spot (ревью скилов 12.10).

Причина: com.bot7.ohlcv-gapfill (scripts/ohlcv_gapfill_all.sh, launchd StartInterval=3600 — минута запуска плывёт
по часу) до 12.10 звал ingest с target-end = «сейчас»: каждый прогон записывал ещё не закрытую минуту, следующий
начинал с last_ts+60с — обрезанный бар оставался навсегда (≈3 тыс. минут на монету с 14.05.2026, объём ~53%).
Счёт строк, дубли и OHLC-согласованность такие бары не ловят — только сверка с Binance (этот скрипт без --apply).

Что делает: качает с Binance все закрытые минуты окна [--from; последняя минута файла], сравнивает с файлом.
Расходящиеся строки заменяются, отсутствующие у файла (есть у Binance) вставляются. Файл читается и пишется
БАЙТАМИ: формат строк ingest (csv.writer, окончание CRLF) сохраняется; строки с другим окончанием (LF после
неудачной перекачки 12.10) приводятся к CRLF. Часовой <SYM>_1h_2y.csv: часы с изменёнными минутами пересчитываются
из исправленных минут (объём округлён до 8 знаков), окончания — тоже CRLF. Без --apply — только отчёт.

    .venv/bin/python3 research/weex/repair_frozen_1m.py [BTCUSDT ETHUSDT XRPUSDT] [--from 2026-04-01] [--apply]

Защита: копия исходника рядом (<SYM>_1m_2y.pre_repair_<дата_время>.csv, в .gitignore; существующую не
перезаписывает). Гонка с gapfill (ревью GPT 13.10, вопрос 4: дозапись между проверкой и os.replace терялась) закрыта
общим межпроцессным lock backtests/frozen/.ingest.lock (fcntl.flock, тот же держит scripts/ohlcv_ingest.py на каждой
дозаписи 1m и пересчёте 1h и открывает путь заново под ним): чтение → сборка → замена 1m и пересчёт 1h идут под lock,
файл под lock перечитывается целиком — дописанное за время скачивания сохраняется. Дополнительно перед заменой размер
и mtime сверяются с прочитанными под lock (писатель без lock — замена отменяется). Временный файл — уникальный
(mkstemp), fsync + os.replace, права исходника сохраняются.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:                                    # Windows: межпроцессного lock нет — repair там не запускать
    fcntl = None

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "backtests" / "frozen"
API = "https://api.binance.com/api/v3/klines"
MIN = 60_000
HOUR = 3_600_000
EOL = b"\r\n"                                          # как пишет ingest (csv.writer по умолчанию)
LOCK_NAME = ".ingest.lock"                             # общий с scripts/ohlcv_ingest.py — имя не менять в одном месте


@contextmanager
def frozen_lock(folder: Path):
    """Эксклюзивный межпроцессный lock каталога frozen (тот же файл, что у gapfill scripts/ohlcv_ingest.py)."""
    if fcntl is None:
        sys.exit("нет fcntl — без общего lock с gapfill repair не запускается")
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / LOCK_NAME, "a+b") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def fetch(symbol: str, start: int, end: int) -> dict[int, tuple]:
    out, cur = {}, start
    while cur <= end:
        url = f"{API}?symbol={symbol}&interval=1m&startTime={cur}&endTime={end}&limit=1000"
        for attempt in range(6):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    raw = json.load(r)
                break
            except Exception:                                   # noqa: BLE001
                if attempt == 5:
                    raise
                time.sleep(min(2 ** attempt * 0.5, 30))
        if not raw:
            break
        now = int(time.time() * 1000)
        for k in raw:
            if int(k[6]) < now - 5_000:                          # только закрытые минуты (с запасом 5 с)
                out[int(k[0])] = tuple(float(x) for x in k[1:6])
        cur = int(raw[-1][0]) + MIN
        time.sleep(0.12)
    return out


def same(a: tuple, b: tuple) -> bool:
    return all(abs(x - y) <= 1e-9 * max(1.0, abs(y)) for x, y in zip(a, b))


def fmt(ts: int, v: tuple) -> bytes:
    # как csv.writer: repr(float) для чисел
    return (",".join([str(ts)] + [repr(float(x)) for x in v])).encode() + EOL


def split_lines(data: bytes) -> list[bytes]:
    """Строки с окончаниями; последняя без окончания получает CRLF."""
    parts = data.split(b"\n")
    out = [p + b"\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1] + EOL)
    return out


def canon(line: bytes) -> bytes:
    return line.rstrip(b"\r\n") + EOL


def vals(line: bytes) -> tuple:
    return tuple(float(x) for x in line.rstrip(b"\r\n").split(b",")[1:6])


def _changed(path: Path, stat0: os.stat_result) -> bool:
    st = path.stat()
    return (st.st_size, st.st_mtime_ns) != (stat0.st_size, stat0.st_mtime_ns)


def write_atomic(path: Path, chunks: list[bytes], stat0: os.stat_result) -> bool:
    """Вызывать под frozen_lock: stat0 снят под ним же. Уникальный tmp (не трогает чужие *.tmp), права исходника."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            for c in chunks:
                f.write(c)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, stat0.st_mode & 0o777)                   # mkstemp создаёт 0600
        if _changed(path, stat0):                              # писатель БЕЗ lock (старый gapfill) — не заменять
            print(f"   {path.name}: файл изменился во время работы (писатель без lock) — замена ОТМЕНЕНА, перезапусти")
            return False
        os.replace(tmp, path)
        return True
    finally:
        if tmp.exists():
            tmp.unlink()


def backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = path.with_name(path.name.replace(".csv", f".pre_repair_{stamp}.csv"))
    if dst.exists():
        sys.exit(f"копия {dst.name} уже есть — не перезаписываю")
    shutil.copy2(path, dst)
    return dst


def _plan(lines: list[bytes], ref: dict[int, tuple], from_ms: int, last: int):
    """Что менять в минутках: расходящиеся с Binance, отсутствующие (до last), строки не с CRLF."""
    body = lines[1:]
    idx = {}
    for i, line in enumerate(body):
        ts = int(line.split(b",", 1)[0])
        if ts >= from_ms:
            idx[ts] = i
    changed = [ts for ts, i in idx.items() if ts in ref and not same(vals(body[i]), ref[ts])]
    missing = sorted(ts for ts in ref if ts not in idx and from_ms <= ts <= last)
    bad_eol = sum(1 for l in lines if not l.endswith(EOL))
    return body, idx, changed, missing, bad_eol


def _build(header: bytes, body: list[bytes], idx: dict, changed: list, missing: list, ref: dict) -> list[bytes]:
    body = list(body)
    for ts in changed:
        body[idx[ts]] = fmt(ts, ref[ts])
    if missing:
        rows = {int(l.split(b",", 1)[0]): l for l in body}
        rows.update({ts: fmt(ts, ref[ts]) for ts in missing})
        body = [rows[t] for t in sorted(rows)]
    return [canon(header)] + [canon(l) for l in body]


def repair(symbol: str, from_ms: int, apply: bool) -> None:
    path = FROZEN / f"{symbol}_1m_2y.csv"
    with frozen_lock(FROZEN):                                  # целые строки: gapfill дописывает только под lock
        lines = split_lines(path.read_bytes())
    last = int(lines[-1].split(b",", 1)[0])
    ref = fetch(symbol, from_ms, last)                         # минуты; lock на скачивание не держим
    body, idx, changed, missing, bad_eol = _plan(lines, ref, from_ms, last)
    by_minute = Counter((ts // MIN) % 60 for ts in changed)
    top = ", ".join(f":{m:02d}×{n}" for m, n in by_minute.most_common(4))
    print(f"{symbol}: окно {datetime.fromtimestamp(from_ms / 1000, timezone.utc):%Y-%m-%d}…"
          f"{datetime.fromtimestamp(last / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, минут в файле {len(idx)}, "
          f"у Binance {len(ref)}; расходятся {len(changed)} ({top}); нет в файле {len(missing)}; "
          f"строк не с CRLF {bad_eol}")
    if changed:
        ex = changed[-1]
        print(f"   пример {datetime.fromtimestamp(ex / 1000, timezone.utc):%m-%d %H:%M}: файл "
              f"{body[idx[ex]].strip().decode()} → binance {ref[ex]}")
    if not apply:
        if changed or missing:
            return                                           # отчёт: часы сверяются по исправленным минутам
        with frozen_lock(FROZEN):                            # 1h читается целым, не посреди дозаписи gapfill
            fix_hours(symbol, body, from_ms, False)
        return
    with frozen_lock(FROZEN):
        # gapfill пишет только под этим lock и открывает путь заново → под ним файл перечитан целиком: минуты,
        # дописанные за время скачивания, переносятся как есть (новее last они не сверяются), 1m и 1h — одна версия
        stat0 = path.stat()
        lines = split_lines(path.read_bytes())
        body, idx, changed, missing, bad_eol = _plan(lines, ref, from_ms, last)
        if changed or missing or bad_eol:
            out = _build(lines[0], body, idx, changed, missing, ref)
            dst = backup(path)
            if not write_atomic(path, out, stat0):
                return
            print(f"   записано: заменено {len(changed)}, вставлено {len(missing)}, окончаний исправлено {bad_eol}; "
                  f"копия исходника — {dst.name}")
            body = out[1:]
        fix_hours(symbol, body, from_ms, True)


def _valid_bar(v: tuple) -> bool:
    o, h, l, c, vol = v
    return (all(math.isfinite(x) for x in v) and 0 < l <= min(o, c) and h >= max(o, c) and vol >= 0)


def _full_hours(body_1m: list[bytes], from_ms: int) -> tuple[dict[int, list[tuple]], int]:
    """Полные часы: ровно 60 разных UTC-меток hour + k·60000, k=0..59, без дублей, с валидными OHLCV (ревью GPT
    13.10: 60 строк с дублем минуты 0 и без минуты 17 принимались за полный час). Бары — в порядке времени."""
    by_hour: dict[int, dict[int, tuple]] = defaultdict(dict)
    dup: set[int] = set()
    for line in body_1m:
        ts = int(line.split(b",", 1)[0])
        if ts >= from_ms:
            h = ts // HOUR * HOUR
            if ts in by_hour[h]:
                dup.add(h)
            by_hour[h][ts] = vals(line)
    full = {}
    for h, m in by_hour.items():
        grid = [h + k * MIN for k in range(60)]
        if h not in dup and len(m) == 60 and all(t in m for t in grid) and all(_valid_bar(m[t]) for t in grid):
            full[h] = [m[t] for t in grid]
    return full, len(by_hour) - len(full)


def fix_hours(symbol: str, body_1m: list[bytes], from_ms: int, apply: bool) -> None:
    """Каждый ПОЛНЫЙ час окна, пересчитанный из минут, против часового файла (ревью 12.10, раунд 2: в 1h оставались
    часы, испорченные до перекачки, минуты которых уже целы — пересчёт только «изменённых сейчас» их не видел).
    С apply вызывать под frozen_lock (repair так и делает)."""
    path = FROZEN / f"{symbol}_1h_2y.csv"
    if not path.exists():
        return
    stat0 = path.stat()
    lines = split_lines(path.read_bytes())
    bad_eol = sum(1 for l in lines if not l.endswith(EOL))
    full, rejected = _full_hours(body_1m, from_ms)
    diff = []
    for i, line in enumerate(lines[1:], start=1):
        h = int(line.split(b",", 1)[0])
        m = full.get(h)
        if m is None:                                        # неполный/с дублями/битый час — не трогаем
            continue
        v = (m[0][0], max(x[1] for x in m), min(x[2] for x in m), m[-1][3], round(sum(x[4] for x in m), 8))
        if not same(vals(line), v):
            diff.append(h)
            lines[i] = fmt(h, v)
    ex = (f"; пример {datetime.fromtimestamp(diff[0] / 1000, timezone.utc):%m-%d %H:%M}" if diff else "")
    print(f"   часовой файл: полных часов окна {len(full)} (неполных/с дублями/битых {rejected} — не трогаются), "
          f"расходятся с минутами {len(diff)}{ex}; строк не с CRLF {bad_eol}")
    if apply and (diff or bad_eol):
        dst = backup(path)
        if write_atomic(path, [canon(l) for l in lines], stat0):
            print(f"   часовой файл: пересчитано {len(diff)}, окончаний исправлено {bad_eol}; копия — {dst.name}")


def main() -> None:
    args = sys.argv[1:]
    apply = "--apply" in args
    frm = args[args.index("--from") + 1] if "--from" in args else "2026-04-01"
    syms = [a for a in args if a.isupper() and a.endswith("USDT")] or ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
    from_ms = int(datetime.fromisoformat(frm).replace(tzinfo=timezone.utc).timestamp() * 1000)
    for s in syms:
        repair(s, from_ms, apply)


if __name__ == "__main__":
    main()
