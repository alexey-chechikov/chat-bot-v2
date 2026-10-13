"""research/weex/errors_today.py — разбор GPT 13.10 (абзац errors_today): ERROR из консольного лога тоже считаются
(с дедупликацией против errors.log* по времени+логгеру+тексту), покрытие печатается по каждому источнику, пропавший
или начавшийся после начала дня источник — «ПОКРЫТИЕ НЕПОЛНОЕ»."""
import contextlib
import importlib.util
import io
import sys

from tests.research_weex.harness import SCRIPTS

DAY = "2026-10-13"
OLD_ERR = "2026-10-12 23:00:00,001 | ERROR | services.weex_grid.loop | weex_grid.tick_failed BTC\nTimeoutError: earlier\n"
NEW_ERR = "2026-10-13 10:00:00,002 | ERROR | services.weex_grid.loop | weex_grid.tick_failed BTC\nTimeoutError: current\n"
WARN = "2026-10-13 11:00:00,003 | WARNING | services.weex_grid.engine | weex_grid.orphan_order id=1 cid=b7g side=LONG\n"


def run(tmp_path, monkeypatch, errors_log: str | None, console: str | None, day=DAY):
    spec = importlib.util.spec_from_file_location("rw_errors_today_under_test", SCRIPTS / "errors_today.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if errors_log is not None:
        (tmp_path / "errors.log").write_text(errors_log, encoding="utf-8")
    if console is not None:
        (tmp_path / "launchd_app_runner.err").write_text(console, encoding="utf-8")
    monkeypatch.setattr(mod, "LOGS", tmp_path)
    monkeypatch.setattr(mod, "ERR_FILES", [tmp_path / n for n in ("errors.log.3", "errors.log.2", "errors.log.1",
                                                                  "errors.log")])
    monkeypatch.setattr(mod, "CONSOLE", tmp_path / "launchd_app_runner.err")
    monkeypatch.setattr(sys, "argv", ["errors_today.py", day])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        mod.main()
    return out.getvalue()


def test_console_error_missing_from_errors_log_is_counted(tmp_path, monkeypatch):
    """errors.log без сегодняшней записи, консоль с ней — раньше ERROR 0 без предупреждения."""
    out = run(tmp_path, monkeypatch, OLD_ERR, OLD_ERR + NEW_ERR + WARN)
    assert "ERROR «weex» 1" in out, out
    assert "TimeoutError: current" in out


def test_same_error_in_both_sources_counted_once(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch, OLD_ERR + NEW_ERR, OLD_ERR + NEW_ERR + WARN)
    assert "ERROR «weex» 1" in out, out
    assert "WARNING «weex» 1" in out


def test_distinct_errors_same_second_different_ms_both_counted(tmp_path, monkeypatch):
    second = NEW_ERR.replace(",002", ",900")
    out = run(tmp_path, monkeypatch, OLD_ERR + NEW_ERR, OLD_ERR + NEW_ERR + second)
    assert "ERROR «weex» 2" in out, out


def test_coverage_start_printed_for_each_source(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch, OLD_ERR + NEW_ERR, OLD_ERR + NEW_ERR)
    assert "errors.log* с 2026-10-12 23:00:00" in out, out
    assert "консоль с 2026-10-12 23:00:00" in out
    assert "НЕПОЛНОЕ" not in out


def test_missing_console_is_incomplete_coverage(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch, OLD_ERR + NEW_ERR, None)
    assert "ПОКРЫТИЕ НЕПОЛНОЕ" in out, out
    assert "консоль" in out and "нет файла" in out


def test_missing_errors_log_is_incomplete_but_console_errors_still_counted(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch, None, OLD_ERR + NEW_ERR)
    assert "ПОКРЫТИЕ НЕПОЛНОЕ" in out, out
    assert "errors.log*" in out and "нет файла" in out
    assert "ERROR «weex» 1" in out


def test_source_starting_after_day_start_is_incomplete(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch, NEW_ERR, OLD_ERR + NEW_ERR)
    assert "ПОКРЫТИЕ НЕПОЛНОЕ" in out, out
    assert "errors.log* с 2026-10-13 10:00:00" in out
