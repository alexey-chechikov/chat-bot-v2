"""Только чтение: события weex_* за день — ERROR с ПРИЧИНОЙ (последняя строка трейсбека) и WARNING о деньгах.

Источники (ревью скилов 12.10, разбор GPT 13.10): logs/errors.log.3 … .1, errors.log (только ERROR, ротация по 1 МБ —
при всплеске за минуты) и logs/launchd_app_runner.err (консоль, без ротации). ERROR берутся из ОБОИХ источников
(после ротации errors.log сегодняшняя ошибка остаётся только в консоли) и склеиваются по времени до мс + уровню +
логгеру + тексту — одна запись в обоих файлах считается один раз. WARNING пишутся ТОЛЬКО в консоль: place_rejected,
place_failed, orphan_order, external_close, flatten_*, pending_not_found, tp_qty_mismatch, fee_unresolved — по ним
деньги, «ошибок нет» без них = ложное «всё ок». Покрытие печатается по каждому источнику (с какой записи он
начинается); источник отсутствует, пуст или начинается позже начала дня — «ПОКРЫТИЕ НЕПОЛНОЕ». Покрытие — это
начало хранения, а не непрерывность: простой процесса внутри дня по логам не виден.
Время в логах — местное (как и день по умолчанию).

    .venv/bin/python3 research/weex/errors_today.py [YYYY-MM-DD] [подстрока, по умолчанию weex]
"""
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

LOGS = Path(__file__).resolve().parents[2] / "logs"
ERR_FILES = [LOGS / n for n in ("errors.log.3", "errors.log.2", "errors.log.1", "errors.log")]
CONSOLE = LOGS / "launchd_app_runner.err"
HEAD = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),(\d+) \| (\w+) \| ([^|]+) \| (.*)$")
ERROR_LEVELS = ("ERROR", "CRITICAL")


def blocks(lines):
    cur = None
    for line in lines:
        m = HEAD.match(line)
        if m:
            if cur:
                yield cur
            cur = {"day": m.group(1), "time": m.group(2), "ms": m.group(3), "level": m.group(4),
                   "logger": m.group(5).strip(), "msg": m.group(6).strip(), "tail": []}
        elif cur is not None and line.strip():
            cur["tail"].append(line.rstrip())
    if cur:
        yield cur


def read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []


def coverage(name: str, items: list, exists: bool, day: str) -> tuple[str, bool]:
    """(текст, покрывает ли источник весь день с полуночи)."""
    if not exists:
        return f"{name}: нет файла", False
    start = min((b["day"] + " " + b["time"] for b in items), default=None)
    if start is None:
        return f"{name}: файл без записей", False
    return f"{name} с {start}", start <= f"{day} 00:00:00"


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    needle = (sys.argv[2] if len(sys.argv) > 2 else "weex").lower()
    err_blocks = [b for p in ERR_FILES for b in blocks(read(p))]
    console = list(blocks(read(CONSOLE)))
    cov = [coverage("errors.log*", err_blocks, any(p.exists() for p in ERR_FILES), day),
           coverage("консоль", console, CONSOLE.exists(), day)]
    merged: dict = {}
    for src, items in (("file", err_blocks), ("console", console)):
        for b in items:
            if b["level"] not in ERROR_LEVELS:
                continue
            key = (b["day"], b["time"], b["ms"], b["level"], b["logger"], b["msg"])
            have = merged.get(key)
            if have is None:
                merged[key] = {**b, "src": {src}}
            else:
                have["src"].add(src)
                if len(b["tail"]) > len(have["tail"]):
                    have["tail"] = b["tail"]
    errors = sorted((b for b in merged.values() if b["day"] == day and needle in (b["logger"] + b["msg"]).lower()),
                    key=lambda b: (b["time"], b["ms"]))
    n_file = sum(1 for b in errors if b["src"] == {"file"})
    n_cons = sum(1 for b in errors if b["src"] == {"console"})
    n_both = len(errors) - n_file - n_cons
    warns = [b for b in console if b["day"] == day and b["level"] == "WARNING"
             and needle in (b["logger"] + b["msg"]).lower()]
    gaps = [text for text, ok in cov if not ok]
    print(f"{day}: ERROR «{needle}» {len(errors)} (в обоих источниках {n_both}, только errors.log* {n_file}, "
          f"только консоль {n_cons}), WARNING «{needle}» {len(warns)}")
    print("покрытие: " + "; ".join(text for text, _ in cov)
          + (f" → ПОКРЫТИЕ НЕПОЛНОЕ ({', '.join(gaps)})" if gaps else ""))
    for title, items, use_tail in (("ERROR", errors, True), ("WARNING", warns, False)):
        groups, last = Counter(), {}
        for b in items:
            event = b["msg"].split()[0] if b["msg"] else "?"
            if use_tail and b["tail"]:
                cause = b["tail"][-1].strip()
            else:
                cause = b["msg"][len(event):].strip() or "(без текста)"
                cause = re.sub(r"\b(id|price|entry|qty|rest|exch_size|est_pnl|lot|order)=\S+", r"\1=…", cause)
            key = (event, cause[:160])
            groups[key] += 1
            last[key] = b["time"]
        for (event, cause), n in groups.most_common():
            print(f"  {title} {n:>3}× {event}  посл. {last[(event, cause)]}\n       {cause}")


if __name__ == "__main__":
    main()
