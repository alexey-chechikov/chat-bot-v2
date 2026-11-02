"""CoinGlass — остатки разбора GPT 29.10 (docs/WEEX_GPT_CRITICAL_REPLY_RECHECK_2026-10-29.md §2, P2): свежесть выгрузки
смотрела последний ИМЕЮЩИЙСЯ закрытый час, а не ожидаемый; у нейтрального диапазона выход вверх «подтверждал» тезис
«торговля внутри диапазона»."""
from datetime import timedelta

import pandas as pd

from services.coinglass_web import hypothesis, tv_export


def _hour(s):
    return int(pd.Timestamp(s).timestamp())


def _full():
    return {c: 1.0 for c in tv_export.COLUMNS}


# ── свежесть: ожидаемый час floor(now) − 1ч ────────────────────────────────────────────────────────────────────────

def test_freshness_rejects_a_missing_latest_closed_hour():
    """Контрпример GPT: в 12:20 UTC есть заполненный 10:00, но нет уже закрытого 11:00."""
    now = pd.Timestamp("2026-10-29T12:20:00Z").timestamp()
    stale = {_hour("2026-10-29T10:00:00Z"): {c: 1. for c in tv_export.FRESH}}
    assert tv_export.fresh_missing(stale, now), "latest closed hour is absent but freshness returned no problem"


def test_freshness_ok_when_expected_hour_is_full_and_current_bar_is_live():
    now = pd.Timestamp("2026-10-29T12:20:00Z").timestamp()
    rows = {_hour("2026-10-29T10:00:00Z"): _full(), _hour("2026-10-29T11:00:00Z"): _full(),
            _hour("2026-10-29T12:00:00Z"): {"close": 1.0}}          # незакрытый час может быть неполным
    assert tv_export.fresh_missing(rows, now) == []


def test_freshness_lists_empty_fields_of_the_expected_hour():
    now = pd.Timestamp("2026-10-29T12:00:00Z").timestamp()          # 11:00 закрылся ровно сейчас
    full = _full()
    rows = {_hour("2026-10-29T10:00:00Z"): full, _hour("2026-10-29T11:00:00Z"): {**full, "taker_delta": None}}
    assert tv_export.fresh_missing(rows, now) == ["taker_delta"]


# ── нейтральный диапазон: оба выхода — отмена ──────────────────────────────────────────────────────────────────────

def _range_rec(state="RANGE"):
    t = pd.Timestamp("2026-10-29T10:00:00Z")
    return t, {"bar": (t - pd.Timedelta(hours=1)).isoformat(),
               "state": {"price": state, "flow": state},
               "box": {"L": 100., "H": 110., "width_pct": 10.},
               "move": None, "pend": None,
               "f": {"close": 105., "atr": 1., "er": 0.1, "d6": 0., "d6_thr": 1., "mv6": 0.}}


def test_neutral_range_hypothesis_is_not_confirmed_by_upward_escape():
    """Контрпример GPT: тезис «торговля внутри диапазона» не подтверждается выходом вверх."""
    t, rec = _range_rec()
    df = pd.DataFrame({"px_close": [105.]}, index=[t])
    h = hypothesis.build(rec, "ETHUSDT", df, t.to_pydatetime())
    assert "выход вверх" not in (h["confirm"] or ""), h


def test_neutral_range_both_escapes_cancel_and_holding_confirms():
    t, rec = _range_rec()
    df = pd.DataFrame({"px_close": [105.]}, index=[t])
    h = hypothesis.build(rec, "ETHUSDT", df, t.to_pydatetime())
    assert h["confirm"].startswith("удержание") and "6 ч" in h["confirm"]
    assert "выше 110" in h["cancel"] and "ниже 100" in h["cancel"]
    assert h["tilt"] is None and h["dir"] == 0


def test_range_pressure_is_a_separate_hypothesis(tmp_path):
    t, rec = _range_rec("RANGE_SELL_PRESSURE")
    df = pd.DataFrame({"px_close": [105.]}, index=[t])
    h = hypothesis.build(rec, "ETHUSDT", df, t.to_pydatetime())
    assert h["confirm"].startswith("удержание") and "выше 110" in h["cancel"] and "ниже 100" in h["cancel"]
    tl = h["tilt"]
    assert tl["dir"] == -1 and "продавцов" in tl["conclusion"]
    assert tl["confirm"].startswith("выход вниз") and "ниже 100" in tl["confirm"]
    assert tl["cancel"].startswith("выход вверх") and "выше 110" in tl["cancel"]
    assert any(line.startswith("Отдельная гипотеза — перекос") for line in hypothesis.lines(h))
    path = tmp_path / "h.jsonl"
    hypothesis.log_shown(h, t.to_pydatetime(), path)
    got = hypothesis.last_shown("ETHUSDT", path, before=t + timedelta(minutes=1))
    assert got["v"] == hypothesis.VERSION and got["tilt"]["dir"] == -1 and got["tilt"]["confirm"] == tl["confirm"]
