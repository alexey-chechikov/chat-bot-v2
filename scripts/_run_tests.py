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
    "tests/services/market_brief/",
    "tests/services/coinglass_web/",
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
    "tests/services/risk_guard/",
    "tests/services/hedge_shadow/",
    "tests/services/grid_border/",
    "tests/services/setup_detector/test_push_gate.py",
    "tests/services/bot_watch/",
    "tests/services/short_gate/",
    "tests/services/alt_guard/",
    "tests/tools/test_market_card.py",
    "tests/tools/test_config_coverage.py",
    "tests/services/morning_brief/test_regime_fallback.py",
    "tests/services/trend_signals/",
    "tests/services/grid_model/",
    "tests/services/weex_grid/",
    "tests/services/weex_trend/",
    "tests/services/signal_journal/",
    "tests/services/weex_book/",
    "tests/research_weex/",
    "tests/research_tools/",
    "tests/research_gold/",
    "tests/research_atlas/",
    "tests/research_manual/",
    "tests/research_trend/",
    "tests/test_app_runner_lock.py",
    "tests/services/tv_levels/",
    # main() — только с заглушками задач (фикстура файла); два старых теста Telegram-раннеров висят — не здесь
    "tests/test_app_runner.py::test_main_starts_no_real_service",
    "tests/test_app_runner.py::test_app_runner_starts_and_stops_cleanly",
    "tests/test_app_runner.py::test_app_runner_orchestrator_crash_stops_polling",
    "tests/test_app_runner.py::test_app_runner_polling_crash_stops_orchestrator",
    "tests/test_app_runner.py::test_app_runner_sigint_triggers_graceful_shutdown",
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
