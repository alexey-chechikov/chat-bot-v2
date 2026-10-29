"""Контрпримеры GPT a7d799b (§3): исход теневого решения считался от закрытия бара, а не от исполнения после решения;
карточка за прошлый момент читала решение, записанное позже; выгрузка CoinGlass признавалась устойчивой по одним
размерам, хотя значения закрытых баров менялись каждый опрос."""
import json

import pandas as pd
import pytest

from services.coinglass_web import scenarios, tv_export


def _minutes(start, end, before, after, jump_at):
    idx = pd.date_range(start, end, freq="1min", inclusive="left")
    px = [before if t < jump_at else after for t in idx]
    return pd.DataFrame({"open": px, "high": px, "low": px, "close": px}, index=idx)


def test_scenario_forward_return_excludes_move_before_decision(tmp_path):
    t = pd.Timestamp("2026-10-28 10:00", tz="UTC")
    # Бар признаков кончился в 11:00 по 100. В 11:01 цена прыгнула до 110 и стоит там же.
    # Решение записано в 11:16 — войти можно только по 110; ход за 6 ч от исполнения — ноль.
    rec = {"kind": "decision", "v": scenarios.VERSION, "sym": "BTCUSDT", "id": "synthetic",
           "bar": t.isoformat(), "decision_at": (t + pd.Timedelta(hours=1, minutes=16)).isoformat(),
           "forward": True, "state": {"price": "UP_CONFIRMED", "flow": "UP_CONFIRMED"},
           "f": {"close": 100., "atr": 1.}}
    j = tmp_path / "journal.jsonl"
    j.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    idx = pd.date_range(t, periods=9, freq="1h")
    df = pd.DataFrame({"px_open": [100.] + [110.] * 8, "px_close": [100.] + [110.] * 8,
                       "px_high": [100.] + [110.] * 8, "px_low": [100.] + [110.] * 8}, index=idx)
    mins = _minutes(t + pd.Timedelta(hours=1), t + pd.Timedelta(hours=10), 100., 110.,
                    t + pd.Timedelta(hours=1, minutes=1))
    scenarios.update("BTCUSDT", df, (t + pd.Timedelta(hours=9)).to_pydatetime(),
                     journal=j, state_path=tmp_path / "state.json",
                     minute_px=lambda sym, a, b: mins[(mins.index >= a) & (mins.index < b)])
    outs = [json.loads(s) for s in j.read_text(encoding="utf-8").splitlines()]
    got = next(r for r in outs if r.get("kind") == "outcome" and r.get("ref") == "synthetic" and r["h"] == "6h")
    assert got["ret_pct"] == pytest.approx(0), got            # было +10%: ход до решения входил в исход
    assert got["exec_price"] == pytest.approx(110.)
    assert got["bar_close_ret_pct"] == pytest.approx(10.)    # «ход от закрытия бара» — отдельное описательное поле


def test_scenario_outcome_waits_for_minute_prices(tmp_path):
    """Нет минутных цен после решения — исход не пишется (а не угадывается по часовой свече)."""
    t = pd.Timestamp("2026-10-28 10:00", tz="UTC")
    rec = {"kind": "decision", "v": scenarios.VERSION, "sym": "BTCUSDT", "id": "nomin", "bar": t.isoformat(),
           "decision_at": (t + pd.Timedelta(hours=1, minutes=16)).isoformat(), "forward": True,
           "state": {"price": "RANGE", "flow": "RANGE"}, "f": {"close": 100., "atr": 1.}}
    j = tmp_path / "journal.jsonl"
    j.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    idx = pd.date_range(t, periods=9, freq="1h")
    df = pd.DataFrame({c: [100.] * 9 for c in ("px_open", "px_close", "px_high", "px_low")}, index=idx)
    scenarios.update("BTCUSDT", df, (t + pd.Timedelta(hours=9)).to_pydatetime(), journal=j,
                     state_path=tmp_path / "state.json", minute_px=lambda sym, a, b: None)
    outs = [json.loads(s) for s in j.read_text(encoding="utf-8").splitlines()]
    assert not [r for r in outs if r.get("kind") == "outcome" and r.get("ref") == "nomin"]


def test_historical_card_does_not_read_a_later_decision(tmp_path):
    j = tmp_path / "journal.jsonl"
    rec = {"kind": "decision", "v": scenarios.VERSION, "sym": "BTCUSDT", "bar": "2026-10-28T10:00:00Z",
           "decision_at": "2026-10-28T11:45:00Z"}
    j.write_text(json.dumps(rec), encoding="utf-8")
    assert scenarios.latest_decision("BTCUSDT", j, before=pd.Timestamp("2026-10-28T11:10:00Z")) is None
    assert scenarios.latest_decision("BTCUSDT", j, before=pd.Timestamp("2026-10-28T11:50:00Z")) is not None


def test_export_requires_stable_values_not_only_nonnull_counts(monkeypatch):
    # Настоящий цикл выгрузки, подменён только браузер. Цены закрытых баров меняются каждый опрос.
    monkeypatch.setattr(tv_export, "COLUMNS", ("close",))
    monkeypatch.setattr(tv_export, "STUDIES", [("metric", "metric", {"x": "close"})])
    monkeypatch.setattr(tv_export, "rows_of", lambda export, ids: export["rows"])
    monkeypatch.setattr(tv_export, "check_legend", lambda *a: {"ok": True})

    class Page:
        n = 0
        def goto(self, *a, **kw): pass
        def wait_for_function(self, *a, **kw): pass
        def wait_for_timeout(self, *a): pass
        def close(self): pass
        def evaluate(self, script, *a):
            if script == tv_export.SETUP_JS:
                return {"ready": True, "ids": {"metric": "id"}, "names": {}}
            if script == tv_export.EXPORT_JS:
                self.n += 1
                return {"rows": {3600 * i: {"close": float(100 + self.n)} for i in range(24)}}
            return {}
        def locator(self, *a): return self
        @property
        def first(self): return self
        @property
        def mouse(self): return self
        def move(self, *a): pass
        def bounding_box(self): return {"x": 0, "y": 0, "width": 1000, "height": 1000}

    class Browser:
        def new_page(self, **kw): return Page()

    got = tv_export.export_symbol(Browser(), "BTCUSDT", days=1)
    assert got["stable"] is False, got


def test_export_stable_when_closed_values_settle(monkeypatch):
    """Контроль: значения закрытых баров не меняются (меняется только незакрытый) — выгрузка устойчива."""
    monkeypatch.setattr(tv_export, "COLUMNS", ("close",))
    monkeypatch.setattr(tv_export, "STUDIES", [("metric", "metric", {"x": "close"})])
    monkeypatch.setattr(tv_export, "rows_of", lambda export, ids: export["rows"])
    monkeypatch.setattr(tv_export, "check_legend", lambda *a: {"ok": True})
    import time as _t
    now_bar = int(_t.time()) // 3600 * 3600

    class Page:
        n = 0
        def goto(self, *a, **kw): pass
        def wait_for_function(self, *a, **kw): pass
        def wait_for_timeout(self, *a): pass
        def close(self): pass
        def evaluate(self, script, *a):
            if script == tv_export.SETUP_JS:
                return {"ready": True, "ids": {"metric": "id"}, "names": {}}
            if script == tv_export.EXPORT_JS:
                self.n += 1
                rows = {now_bar - 3600 * i: {"close": 100.0} for i in range(1, 25)}
                rows[now_bar] = {"close": float(100 + self.n)}     # текущий бар живой
                return {"rows": rows}
            return {}
        def locator(self, *a): return self
        @property
        def first(self): return self
        @property
        def mouse(self): return self
        def move(self, *a): pass
        def bounding_box(self): return {"x": 0, "y": 0, "width": 1000, "height": 1000}

    class Browser:
        def new_page(self, **kw): return Page()

    assert tv_export.export_symbol(Browser(), "BTCUSDT", days=1)["stable"] is True
