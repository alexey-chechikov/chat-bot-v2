"""Только чтение: события weex_* за день — ERROR с ПРИЧИНОЙ (последняя строка трейсбека) и WARNING о деньгах.

Источники (ревью скилов 12.10): logs/errors.log.3 … .1, errors.log (только ERROR, ротация по 1 МБ — при всплеске
за минуты) и logs/launchd_app_runner.err (консоль WARNING+ без ротации). WARNING пишутся ТОЛЬКО во второй:
place_rejected, place_failed, orphan_order, external_close, flatten_*, pending_not_found, tp_qty_mismatch,
fee_unresolved — по ним деньги, «ошибок нет» без них = ложное «всё ок». Если самый ранний файл errors.log* начинается
позже начала дня — печатается «ПОКРЫТИЕ НЕПОЛНОЕ».

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
HEAD = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d+ \| (\w+) \| ([^|]+) \| (.*)$")


def blocks(lines):
    cur = None
    for line in lines:
        m = HEAD.match(line)
        if m:
            if cur:
                yield cur
            cur = {"day": m.group(1), "time": m.group(2), "level": m.group(3), "logger": m.group(4).strip(),
                   "msg": m.group(5).strip(), "tail": []}
        elif cur is not None and line.strip():
            cur["tail"].append(line.rstrip())
    if cur:
        yield cur


def read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    needle = (sys.argv[2] if len(sys.argv) > 2 else "weex").lower()
    err_blocks = [b for p in ERR_FILES for b in blocks(read(p))]
    earliest = min((b["day"] + " " + b["time"] for b in err_blocks), default=None)
    coverage_ok = earliest is not None and earliest <= f"{day} 00:00:00"
    console = list(blocks(read(CONSOLE)))
    c_earliest = console[0]["day"] + " " + console[0]["time"] if console else None
    c_ok = c_earliest is not None and c_earliest <= f"{day} 00:00:00"
    errors = [b for b in err_blocks if b["day"] == day and needle in (b["logger"] + b["msg"]).lower()]
    warns = [b for b in console if b["day"] == day and b["level"] == "WARNING"
             and needle in (b["logger"] + b["msg"]).lower()]
    print(f"{day}: ERROR «{needle}» {len(errors)}, WARNING «{needle}» {len(warns)}"
          + ("" if coverage_ok else f"; ПОКРЫТИЕ ERROR НЕПОЛНОЕ — самые ранние записи errors.log* с {earliest}")
          + ("" if c_ok else f"; ПОКРЫТИЕ WARNING НЕПОЛНОЕ — консольный лог с {c_earliest}"))
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
