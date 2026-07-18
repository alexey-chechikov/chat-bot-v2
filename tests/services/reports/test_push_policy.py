"""push_policy: оператор 2026-07-18 — регулярные отчёты только по команде."""
from __future__ import annotations

from pathlib import Path

import services.reports.push_policy as pp


def test_default_enabled_when_no_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pp, "CONFIG_PATH", tmp_path / "nope.json")
    assert pp.scheduled_push_enabled() is True


def test_disabled_by_config(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "rd.json"
    cfg.write_text('{"scheduled_push": false}', encoding="utf-8")
    monkeypatch.setattr(pp, "CONFIG_PATH", cfg)
    assert pp.scheduled_push_enabled() is False


def test_garbage_config_fails_open(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "rd.json"
    cfg.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(pp, "CONFIG_PATH", cfg)
    assert pp.scheduled_push_enabled() is True


def test_daily_self_report_respects_push_off(monkeypatch, tmp_path: Path) -> None:
    """Пуш выключен → отчёт не шлётся, окно закрывается (mark_sent)."""
    import services.reports.daily_self_report as dsr
    cfg = tmp_path / "rd.json"
    cfg.write_text('{"scheduled_push": false}', encoding="utf-8")
    monkeypatch.setattr(pp, "CONFIG_PATH", cfg)
    monkeypatch.setattr(dsr, "should_send", lambda now: True)
    marked = []
    monkeypatch.setattr(dsr, "mark_sent", lambda now: marked.append(now))
    sent: list = []
    assert dsr.maybe_send_daily(send_fn=sent.append) is False
    assert not sent
    assert marked  # не пересобираем каждый тик


def test_daily_digest_builds_dry_run_when_push_off(monkeypatch, tmp_path: Path) -> None:
    import services.reports.daily_digest as dd
    cfg = tmp_path / "rd.json"
    cfg.write_text('{"scheduled_push": false}', encoding="utf-8")
    monkeypatch.setattr(pp, "CONFIG_PATH", cfg)
    monkeypatch.setattr(dd, "_build_report", lambda now: "digest text")
    monkeypatch.setattr(dd, "_last_sent_date", lambda: None)
    marked = []
    monkeypatch.setattr(dd, "_mark_sent", lambda d: marked.append(d))
    from datetime import datetime, timezone
    in_window = datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)
    sent: list = []
    assert dd.maybe_send_daily_digest(send_fn=sent.append, now=in_window) is True
    assert not sent      # dry_run: собрано в лог, в TG не ушло
    assert marked
