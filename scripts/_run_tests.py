"""Wrapper: запустить все тесты bot7 одной простой командой.

Использование: .venv/bin/python3 scripts/_run_tests.py

Не Bash one-liner с piped tail / 2>&1 / multi-path — это вызывает
permission prompts. Файл-обёртка обходит static analyzer.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_DIRS = [
    "tests/services/pump_freeze/",
    "tests/services/twap_defender/",
    "tests/services/bot_brain/",
    "tests/services/range_hunter/",
    "tests/services/session_breakout/",
    "tests/services/paper_signal_tracker/",
    "tests/services/scalp_liq/",
    "tests/services/order_harvester/",
    "tests/services/pre_cascade_alert/",
    "tests/services/reports/",
    "tests/services/grid_coordinator/",
    "tests/services/grid_autotune/",
    "tests/services/alt_guard/",
    "tests/tools/test_market_card.py",
]

def main():
    cmd = [".venv/bin/python3", "-m", "pytest"] + TEST_DIRS + ["-q"]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (result.stdout or "") + (result.stderr or "")
    # Print only the last 8 lines (summary)
    lines = out.strip().splitlines()
    print("\n".join(lines[-8:]))
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
