"""Дневные сводки CoinGlass 14:00/16:00 — синтетика, без сети и без Telegram."""
import json
from datetime import datetime, timezone

import pytest

from services.coinglass_web import day_range as dr
from services.coinglass_web import intraday

UTC = timezone.utc
MIN = 60_000


def snap(cap: str, price: float, zs: tuple, zl: tuple, short_pct: int):
    return {"levels_captured": cap, "levels": {
        "price": price, "near": {"short_pct": short_pct, "long_pct": 100 - short_pct},
        "zones_short": [{"lo": zs[0], "hi": zs[1], "strength": zs[2]}],
        "zones_long": [{"lo": zl[0], "hi": zl[1], "strength": zl[2]}]},
        "liquidations": {"windows": {"4h": {"long": 2e6, "short": 1e5}, "12h": {"long": 2.26e7, "short": 1.7e6}}}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(intraday, "DIR", tmp_path)
    monkeypatch.setattr(intraday, "LOG", tmp_path / "intraday_log.jsonl")
    monkeypatch.setattr(intraday, "ROOT", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "report_delivery.json").write_text(json.dumps({"coinglass_intraday": True}))
    rows = [snap("2026-10-20T06:00:12+00:00", 81668, (83152, 83792, 716), (79951, 80591, 750), 43),
            snap("2026-10-20T12:00:15+00:00", 81481, (83152, 83792, 679), (79908, 80591, 720), 40)]
    (tmp_path / "snapshots.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(dr, "_mine", lambda kind: [])                 # без прогноза — только CoinGlass
    return tmp_path


def test_build_compares_with_0800_snapshot(env):
    t = intraday.build(datetime(2026, 10, 20, 12, 1, tzinfo=UTC))
    assert t.startswith("🧲 CoinGlass 14:00") and "не сигнал" in t
    assert "81,668 → 81,481 (-0.2%)" in t
    assert "сила 716 → 679 (-5%)" in t and "края сдвинулись с 79,951–80,591" in t
    assert "шорты 43% → 40% (-3 п.п.)" in t and "за 4 ч лонги $2.0M" in t


def test_forecast_progress_reports_touch_time(env, monkeypatch):
    a = int(datetime(2026, 10, 20, 6, 13, tzinfo=UTC).timestamp() * 1000)
    f = {"algo": dr.ALGO, "kind": "forecast", "date": "2026-10-20", "sym": "BTCUSDT", "A_ms": a,
         "corridor": [79435.0, 84056.0],
         "levels": [{"name": "зоны шортов сверху", "price": 83152.0, "side": "up", "chance": 0.23}]}
    monkeypatch.setattr(dr, "_mine", lambda kind: [f] if kind == "forecast" else [])
    touch = a + 100 * MIN
    monkeypatch.setattr(dr, "klines", lambda sym, i, s, e: [[t, "81500", "83200" if t == touch else "81600", "81400",
                                                              "81500"] for t in range(s, e, MIN)])
    t = intraday.build(datetime(2026, 10, 20, 12, 1, tzinfo=UTC))
    assert "коридор дня 79,435–84,056 пока внутри" in t
    assert "83,152: задета в 09:53 (утром шанс 23%)" in t           # 06:13 UTC + 100 мин = 07:53 UTC = 09:53


def test_maybe_send_only_at_14_16_once_and_respects_flag(env):
    sent = []
    send = lambda text: sent.append(text) or True                   # noqa: E731
    assert intraday.maybe_send(datetime(2026, 10, 20, 11, 1, tzinfo=UTC), send) is False   # 13:01 — не время
    assert intraday.maybe_send(datetime(2026, 10, 20, 12, 1, tzinfo=UTC), send) is True    # 14:01
    assert intraday.maybe_send(datetime(2026, 10, 20, 12, 30, tzinfo=UTC), send) is False  # уже отправлено
    assert len(sent) == 1
    (env / "state" / "report_delivery.json").write_text(json.dumps({"coinglass_intraday": False}))
    assert intraday.maybe_send(datetime(2026, 10, 20, 14, 1, tzinfo=UTC), send) is False   # 16:01, выключено


def test_failed_send_is_logged_and_retried_same_hour(env):
    assert intraday.maybe_send(datetime(2026, 10, 20, 12, 1, tzinfo=UTC), lambda t: False) is False
    log = [json.loads(x) for x in (env / "intraday_log.jsonl").read_text().splitlines()]
    assert log[-1]["ok"] is False
    assert intraday.maybe_send(datetime(2026, 10, 20, 12, 20, tzinfo=UTC), lambda t: True) is True


def test_progress_does_not_deny_touch_on_missing_minutes(monkeypatch):
    """25.10 (аудит GPT A2): 2 из 5 минут — нельзя писать «пока внутри» и «не задета»; в пропуске мог быть пробой."""
    a = int(datetime(2026, 10, 20, 6, 13, tzinfo=UTC).timestamp() * 1000)
    now = datetime.fromtimestamp((a + 5 * MIN) / 1000, UTC)
    f = {"algo": dr.ALGO, "kind": "forecast", "date": dr.issue_day(now).isoformat(), "sym": "BTCUSDT", "A_ms": a,
         "corridor": [95.0, 105.0], "levels": [{"name": "test upper", "price": 105.0, "side": "up", "chance": 0.4}]}
    monkeypatch.setattr(dr, "_mine", lambda kind: [f] if kind == "forecast" else [])
    monkeypatch.setattr(dr, "klines", lambda sym, i, s, e: [[t, "100", "100", "100", "100"] for t in (a, a + 4 * MIN)])
    text = "\n".join(intraday._forecast_progress(now))
    assert "не задета" not in text and "пока внутри" not in text
    assert "неполные: 2 из 5" in text and "неизвестно" in text
