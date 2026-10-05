"""Внутридневные шансы обязаны держать замер 29.09.2026 на 9 годах часовых свечей.

Если тест упал — правили модель, не перепроверив её вне выборки.
"""
from __future__ import annotations

import numpy as np
import pytest

from services.grid_model import odds_intraday as oi
from services.grid_model import odds_z as oz

needs_hourly = pytest.mark.skipif(
    not (oi.DATA / "1h_BTCUSDT.csv").exists() or not (oi.DATA / "1h_ETHUSDT.csv").exists(),
    reason="нет часовой истории: tools/fetch_daily_history.py 1h")


@pytest.fixture(scope="module")
def btc():
    d = oi.load_hourly("BTCUSDT", refresh=False)
    assert len(d) > 70_000, "нужна история с 2017"
    return d


@pytest.fixture(scope="module")
def eth():
    return oi.load_hourly("ETHUSDT", refresh=False)


@pytest.fixture
def model(btc, tmp_path, monkeypatch):
    monkeypatch.setattr(oi, "CACHE", tmp_path)
    m, _ = oi.get_model("BTCUSDT", btc)
    return m


def test_fomc_multiplier_hits_statement_hour_and_next():
    """Заявление 18:00 UTC, прогноз с 16:00: свечи 18:00 и 19:00 (индексы 2, 3) ×2.5."""
    import pandas as pd
    start = pd.Timestamp("2026-10-28T16:00:00Z")
    ev = [pd.Timestamp("2026-10-28T18:00:00Z")]
    mult = oi.event_multipliers(start, 4, ev)
    assert list(mult) == [1.0, 1.0, oi.FOMC_FACTOR, oi.FOMC_FACTOR]
    assert list(oi.event_multipliers(start, 1, ev)) == [1.0]
    assert oi.next_fomc(start, 24, ev) == ev[0]
    assert oi.next_fomc(start + pd.Timedelta(hours=3), 24, ev) is None


def test_cpi_inside_hour_hits_its_candle_only():
    """CPI в 12:30 UTC: свеча 12:00 ×2.5, одна; если прогноз начат в 13:00 — мимо."""
    import pandas as pd
    cpi = [(pd.Timestamp("2026-10-14T12:30:00Z"), 2.5, 1, "Инфляция США (CPI)")]
    mult = oi.event_multipliers(pd.Timestamp("2026-10-14T11:00:00Z"), 4, cpi)
    assert list(mult) == [1.0, 2.5, 1.0, 1.0]
    after = oi.event_multipliers(pd.Timestamp("2026-10-14T13:00:00Z"), 4, cpi)
    assert list(after) == [1.0, 1.0, 1.0, 1.0]
    nxt = oi.next_event(pd.Timestamp("2026-10-14T00:00:00Z"), 24, cpi)
    assert nxt[1] == "Инфляция США (CPI)" and nxt[2] == 2.5


def test_calendar_has_all_three_event_types():
    names = {label for *_, label in oi.macro_events()}
    assert {"Решение ФРС", "Инфляция США (CPI)", "Рынок труда США (NFP)"} <= names


def test_path_scale_flat_profile_is_sqrt_h():
    s = np.ones(168)
    for h in oi.HOURS:
        assert float(oi.path_scale(s, 5, h)) == pytest.approx(np.sqrt(h))


@needs_hourly
def test_season_profile_us_open_vs_asia_night(btc):
    """Открытие США активнее азиатской ночи, выходные тише будней."""
    s = oi.season_profile(btc)
    assert s.mean() == pytest.approx(1.0, abs=1e-9)
    by_hour = s.reshape(7, 24).mean(axis=0)
    assert by_hour[14] > 1.05 > 0.95 > by_hour[5]
    by_day = s.reshape(7, 24).mean(axis=1)
    assert by_day[5] < 0.95 and by_day[6] < 0.95 and by_day[:5].min() > 1.0


@needs_hourly
@pytest.mark.parametrize("fixture,skill_min", [("btc", 0.14), ("eth", 0.12)])
def test_out_of_sample_skill_and_fresh_year(fixture, skill_min, request):
    """Замер: BTC +16.8% / свежий год +17.3%, ETH +15.1% / +15.0%."""
    r = oi.oos_check(request.getfixturevalue(fixture))
    assert r["skill"] > skill_min
    assert r["fresh_skill"] > skill_min, "свежий год обязан держаться сам (ворота №2)"


@needs_hourly
@pytest.mark.parametrize("fixture", ["btc", "eth"])
def test_touch_calibrated_on_every_horizon(fixture, request):
    """Кривые по горизонтам: касание ≤3 п.п. от факта (общая кривая давала 6)."""
    cal = oi.oos_check(request.getfixturevalue(fixture))["cal"]
    touch = cal[cal.index.get_level_values("kind") != "stay"]
    assert (touch["pred"] - touch["fact"]).abs().max() < 0.04


@needs_hourly
def test_intraday_beats_daily_sigma(btc):
    """Размах 24 часа знает о ближайших часах больше, чем дневная σ за 20 дней."""
    daily = oz.load_daily("BTCUSDT", refresh=False)
    s = np.ones(168)
    d = btc.copy()
    t_intra = oi.build_table(d, s)
    ds = daily["sigma"].shift(1).reindex(d.index, method="ffill") / np.sqrt(24)
    d2 = d.assign(pk=ds * 1.0)
    # σ_дня как постоянный «размах часа»: окно 1, чтобы не сглаживать дважды
    old_w = oi.WINDOW
    try:
        oi.WINDOW = 1
        t_daily = oi.build_table(d2, s)
    finally:
        oi.WINDOW = old_w
    half = len(d) // 2

    def skill(t):
        t = t[t["kind"] != "stay"]
        tr, te = t[t["i"] < half], t[t["i"] >= half]
        p = oi.predict(oi.fit(tr), te)
        pb = te.join(tr.groupby(["h", "thr", "kind"])["y"].mean().rename("pb"),
                     on=["h", "thr", "kind"])["pb"].to_numpy()
        y = te["y"].to_numpy()
        return 1 - ((p - y) ** 2).mean() / ((pb - y) ** 2).mean()

    assert skill(t_intra) > skill(t_daily) + 0.02


@needs_hourly
def test_model_is_monotone(model):
    sp = {h: 0.004 * np.sqrt(h) for h in oi.HOURS}
    for h in oi.HOURS:
        assert model.touch(0.005, h, sp[h]) >= model.touch(0.01, h, sp[h]) \
            >= model.touch(0.02, h, sp[h])
        assert model.stay(0.01, h, sp[h]) <= model.stay(0.02, h, sp[h])
    assert model.touch(0.01, 1, sp[1]) < model.touch(0.01, 4, sp[4]) \
        < model.touch(0.01, 24, sp[24])
    cors = [model.corridor(h, sp[h]) for h in oi.HOURS]
    assert cors == sorted(cors) and cors[0] > 0


@needs_hourly
def test_card_near_levels_only(btc, tmp_path, monkeypatch):
    monkeypatch.setattr(oi, "CACHE", tmp_path)
    monkeypatch.setattr(oi, "load_hourly", lambda sym, refresh=True: btc)
    px = float(btc["close"].iloc[-1])
    t = oi.card("BTCUSDT", levels=[("средняя BTC шорт", px * 1.004),
                                   ("обнуление залога", px * 1.30)], price=px)
    assert "КОСНЁТСЯ" in t and "КОРИДОР 80%" in t and "сутки" in t
    assert "средняя BTC шорт" in t
    assert "обнуление залога" not in t, "дальний уровень — в фон, не в часы"
    assert "Сторону не угадывает" in t


def test_background_shows_only_far_levels(monkeypatch):
    d = oz.load_daily("BTCUSDT", refresh=False)
    monkeypatch.setattr(oz, "load_daily", lambda sym, refresh=True: d)
    px = float(d["close"].iloc[-1])
    t = oz.background("BTCUSDT", levels=[("близкий", px * 1.01),
                                         ("дальний", px * 1.25)], price=px)
    assert t.startswith("ФОН (дни)")
    assert "дальний" in t and "близкий" not in t
