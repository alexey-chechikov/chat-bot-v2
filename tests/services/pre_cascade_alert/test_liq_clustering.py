"""Tests for liq_clustering pre-cascade alert."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from services.pre_cascade_alert.liq_clustering import (
    check_and_alert,
    _liq_window_sums,
)


def _write_liqs(path: Path, events: list[tuple[datetime, str, float]]) -> None:
    lines = ["ts_utc,exchange,side,qty,price"]
    for ts, side, qty in events:
        lines.append(f"{ts.isoformat()},test,{side},{qty},80000")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_no_alert_when_below_threshold(tmp_path: Path) -> None:
    liq = tmp_path / "liq.csv"
    now = datetime(2026, 5, 13, 16, 30, tzinfo=timezone.utc)
    _write_liqs(liq, [(now - timedelta(minutes=2), "long", 0.1)])
    send = MagicMock()
    fired = check_and_alert(
        send_fn=send, now=now,
        state_path=tmp_path / "s.json",
        journal_path=tmp_path / "j.jsonl",
        liq_csv=liq,
    )
    assert fired == []
    send.assert_not_called()


def test_alert_when_cluster_threshold_met(tmp_path: Path) -> None:
    liq = tmp_path / "liq.csv"
    now = datetime(2026, 5, 13, 16, 30, tzinfo=timezone.utc)
    # 4 small long-liqs summing to 0.5 BTC > 0.3 threshold
    _write_liqs(liq, [
        (now - timedelta(minutes=4), "long", 0.15),
        (now - timedelta(minutes=3), "long", 0.10),
        (now - timedelta(minutes=2), "long", 0.20),
        (now - timedelta(minutes=1), "long", 0.05),
    ])
    send = MagicMock()
    fired = check_and_alert(
        send_fn=send, now=now,
        state_path=tmp_path / "s.json",
        journal_path=tmp_path / "j.jsonl",
        liq_csv=liq,
    )
    assert len(fired) == 1
    assert fired[0]["side"] == "long"
    assert abs(fired[0]["qty_btc"] - 0.5) < 0.001
    send.assert_called_once()
    assert "PRE-CASCADE" in send.call_args[0][0]
    assert "LONG" in send.call_args[0][0]


def test_no_alert_when_cascade_in_window(tmp_path: Path) -> None:
    """If single liq >=5 BTC — каскад уже сработал, pre-signal suppressed."""
    liq = tmp_path / "liq.csv"
    now = datetime(2026, 5, 13, 16, 30, tzinfo=timezone.utc)
    _write_liqs(liq, [(now - timedelta(minutes=1), "long", 6.0)])
    send = MagicMock()
    fired = check_and_alert(
        send_fn=send, now=now,
        state_path=tmp_path / "s.json",
        journal_path=tmp_path / "j.jsonl",
        liq_csv=liq,
    )
    assert fired == []
    send.assert_not_called()


def test_cooldown_blocks_repeat_alert(tmp_path: Path) -> None:
    liq = tmp_path / "liq.csv"
    sp = tmp_path / "s.json"
    jp = tmp_path / "j.jsonl"
    now1 = datetime(2026, 5, 13, 16, 30, tzinfo=timezone.utc)
    _write_liqs(liq, [(now1 - timedelta(minutes=2), "short", 0.5)])
    send = MagicMock()
    check_and_alert(send_fn=send, now=now1, state_path=sp, journal_path=jp, liq_csv=liq)
    send.reset_mock()
    # 10 min later — still within 30min cooldown
    now2 = now1 + timedelta(minutes=10)
    _write_liqs(liq, [(now2 - timedelta(minutes=2), "short", 0.5)])
    fired = check_and_alert(send_fn=send, now=now2, state_path=sp, journal_path=jp, liq_csv=liq)
    assert fired == []
    send.assert_not_called()


def test_both_sides_same_tick_one_card(tmp_path: Path) -> None:
    """2026-06-10 (Win-фидбек): обе стороны в одном тике → ОДНА TG-карточка
    (сторона с бОльшим qty), обе — в журнал. План у сторон один (inverted
    SHORT), две карточки = чистый дубль."""
    liq = tmp_path / "liq.csv"
    sp = tmp_path / "s.json"
    jp = tmp_path / "j.jsonl"
    now = datetime(2026, 5, 13, 16, 30, tzinfo=timezone.utc)
    _write_liqs(liq, [
        (now - timedelta(minutes=2), "long", 0.6),
        (now - timedelta(minutes=1), "short", 0.55),
    ])
    send = MagicMock()
    fired = check_and_alert(send_fn=send, now=now, state_path=sp, journal_path=jp, liq_csv=liq)
    sides = {f["side"] for f in fired}
    assert sides == {"long", "short"}  # журнал — обе стороны (статистика)
    assert send.call_count <= 1  # TG — максимум одна карточка


def test_global_cooldown_blocks_other_side(tmp_path: Path) -> None:
    """Глобальный дебаунс: другая сторона через 10 мин после карточки —
    только журнал, без TG (молчи 30 мин после любого алерта)."""
    liq = tmp_path / "liq.csv"
    sp = tmp_path / "s.json"
    jp = tmp_path / "j.jsonl"
    t1 = datetime(2026, 5, 13, 16, 30, tzinfo=timezone.utc)
    _write_liqs(liq, [(t1 - timedelta(minutes=2), "short", 0.7)])
    send = MagicMock()
    check_and_alert(send_fn=send, now=t1, state_path=sp, journal_path=jp, liq_csv=liq)
    first_sends = send.call_count

    t2 = t1 + timedelta(minutes=10)
    _write_liqs(liq, [(t2 - timedelta(minutes=2), "long", 0.8)])
    fired2 = check_and_alert(send_fn=send, now=t2, state_path=sp, journal_path=jp, liq_csv=liq)
    assert send.call_count == first_sends  # TG молчит
    if first_sends:  # если первая карточка ушла — вторая сторона журналится
        assert [f["side"] for f in fired2] == ["long"]


def test_journal_appended(tmp_path: Path) -> None:
    liq = tmp_path / "liq.csv"
    sp = tmp_path / "s.json"
    jp = tmp_path / "j.jsonl"
    now = datetime(2026, 5, 13, 16, 30, tzinfo=timezone.utc)
    _write_liqs(liq, [(now - timedelta(minutes=2), "long", 0.5)])
    send = MagicMock()
    check_and_alert(send_fn=send, now=now, state_path=sp, journal_path=jp, liq_csv=liq)
    assert jp.exists()
    lines = jp.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json
    e = json.loads(lines[0])
    assert e["side"] == "long"
    assert e["qty_btc"] == 0.5


def test_window_sums_exclude_old_events(tmp_path: Path) -> None:
    liq = tmp_path / "liq.csv"
    now = datetime(2026, 5, 13, 16, 30, tzinfo=timezone.utc)
    _write_liqs(liq, [
        (now - timedelta(minutes=10), "long", 1.0),  # outside 5-min window
        (now - timedelta(minutes=2), "long", 0.3),
    ])
    long_btc, _ = _liq_window_sums(now, 5, liq_csv=liq)
    assert abs(long_btc - 0.3) < 0.001
