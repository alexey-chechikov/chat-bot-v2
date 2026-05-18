"""Сколько TB на паузе vs active за последние 7d."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_FILES = [ROOT / "logs" / "app.log",
             ROOT / "logs" / "app.log.1",
             ROOT / "logs" / "app.log.2",
             ROOT / "logs" / "app.log.3"]

TB_ID = "4525648417"
PAUSE_RE = re.compile(rf"^(\S+ \S+).*short_bots_guard\.paused bot={TB_ID}.*trigger=(\S+)")
RESUME_RE = re.compile(rf"^(\S+ \S+).*short_bots_guard\.resumed bot={TB_ID}.*trigger=(\S+)")


def main():
    pauses = []
    resumes = []
    for log in LOG_FILES:
        if not log.exists():
            continue
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = PAUSE_RE.match(line)
            if m:
                try:
                    ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
                    ts = ts.replace(tzinfo=timezone.utc)
                    pauses.append((ts, m.group(2)))
                except ValueError:
                    pass
                continue
            m = RESUME_RE.match(line)
            if m:
                try:
                    ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
                    ts = ts.replace(tzinfo=timezone.utc)
                    resumes.append((ts, m.group(2)))
                except ValueError:
                    pass

    pauses.sort()
    resumes.sort()
    print(f"TB pause events (всё в логе):  {len(pauses)}")
    print(f"TB resume events (всё в логе): {len(resumes)}")
    print()

    if pauses:
        print(f"Pauses by trigger:")
        from collections import Counter
        for trig, n in Counter(t for _, t in pauses).most_common():
            print(f"  {trig:32} {n} раз")
        print()
        print(f"Last 10 pauses:")
        for ts, trig in pauses[-10:]:
            print(f"  {ts.strftime('%Y-%m-%d %H:%M')}  trigger={trig}")

    # Compute paused% of time
    if pauses and resumes:
        # Pair pauses to resumes
        intervals = []
        i = 0
        for p_ts, _ in pauses:
            # Find next resume after p_ts
            for r_ts, _ in resumes:
                if r_ts > p_ts:
                    intervals.append((p_ts, r_ts))
                    break
        if intervals:
            total_paused_sec = sum((r - p).total_seconds() for p, r in intervals)
            first_ts = pauses[0][0]
            last_ts = max(pauses[-1][0], resumes[-1][0])
            total_window_sec = (last_ts - first_ts).total_seconds()
            print()
            print(f"Total paused time:  {total_paused_sec/3600:.1f}h")
            print(f"Total window:       {total_window_sec/3600:.1f}h")
            print(f"  → TB paused {100 * total_paused_sec / total_window_sec:.1f}% времени в окне логов")


if __name__ == "__main__":
    main()
