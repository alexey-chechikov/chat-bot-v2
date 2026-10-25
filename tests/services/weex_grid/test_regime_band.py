"""25.10 (оператор: «делай всё»): полоса режима SMA (гистерезис) — research/weex/regime_buffer.py, 2% прошла заранее
записанную проверку на минутках 2017–2024. Из ЛОНГА выход, только если закрытие < SMA·(1−b); в ЛОНГ — только если
> SMA·(1+b); b=0 — правило как было. Порог сегодняшнего закрытия — одна формула для движка и всех показов."""
from __future__ import annotations

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop

DAY = 86_400_000
TODAY = 20_000
NOW = TODAY * 86400 + 300                                  # 00:05 UTC


def rows(closes):
    n = len(closes)
    return [[(TODAY - n + i) * DAY, 0, 0, 0, str(c), 0, (TODAY - n + i) * DAY + DAY - 1] for i, c in enumerate(closes)]


def series(tail):
    """500 закрытых дней: долгий рост (режим ЛОНГ), затем хвост tail — относительно последней SMA100 фона."""
    base = [100.0 + i * 0.01 for i in range(500 - len(tail))]
    return base + tail


def up(closes, band):
    eg._REGIME_CACHE.clear()
    return eg.regime_up("X", 100, now=NOW, fetch=lambda s, n: rows(closes), band_pct=band)


def test_band_zero_is_old_rule():
    c = series([])
    eg._REGIME_CACHE.clear()
    old = eg.regime_up("X", 100, now=NOW, fetch=lambda s, n: rows(c[-105:]))
    assert up(c, 0) is old is True


def test_dip_inside_band_keeps_long_and_deep_dip_exits():
    c = series([])
    sma = sum(c[-100:]) / 100
    shallow = c[:-1] + [sma * 0.99]                         # закрытие на 1% ниже SMA — внутри полосы 2%
    assert up(shallow, 0) is False                          # старое правило вышло бы
    assert up(shallow, 2) is True                           # полоса держит лонг
    deep = c[:-1] + [sma * 0.97]
    assert up(deep, 2) is False


def test_reentry_needs_close_above_upper_band():
    c = series([])
    sma = sum(c[-100:]) / 100
    out = c[:-2] + [sma * 0.95]                             # вышли из лонга
    s2 = sum((out + [0])[-101:-1]) / 100
    back_in_band = out + [s2 * 1.01]                        # вернулись выше SMA, но внутри полосы
    assert up(back_in_band, 0) is True
    assert up(back_in_band, 2) is False                     # полоса: ещё вне рынка
    above = out + [s2 * 1.05]
    assert up(above, 2) is True


def test_band_needs_full_history_and_validates():
    c = series([])
    assert up(c[-105:], 2) is None                          # для гистерезиса мало истории — режим неизвестен
    with pytest.raises(eg.ConfigError):
        up(c, 50)                                           # полоса вне 0…10 — битый конфиг, не «как-нибудь»


@pytest.mark.parametrize("b", [0.0, 2.0])
@pytest.mark.parametrize("is_up", [True, False])
def test_threshold_formula_flips_exactly(b, is_up):
    prev = [100.0 + i * 0.3 for i in range(99)]
    thr = eg.regime_threshold(prev, 100, is_up, b)
    sma = (sum(prev) + thr) / 100                           # SMA100 включает сегодняшнее закрытие
    assert thr == pytest.approx(sma * ((1 - b / 100) if is_up else (1 + b / 100)), rel=1e-12)
    if b == 0:
        assert thr == pytest.approx(sum(prev) / 99)         # прежний порог карточки/account_now


def test_grid_passes_band_only_when_set(tmp_path):
    seen = []

    def regime_fn(sym, n, **kw):
        seen.append(kw)
        return True
    for band, want in ((0, {}), (2.0, {"band_pct": 2.0})):
        conf = {**eg.DEFAULT, "enabled": True, "dry_run": True, "sides": ["LONG"], "regime_sma": 100,
                "regime_band_pct": band}
        g = eg.Grid(eg.DryExchange(lambda: (99999.95, 100000.05)), conf, state_path=tmp_path / f"s{band}.json",
                    journal_path=tmp_path / f"j{band}.jsonl", regime_fn=regime_fn)
        g.tick()
        assert seen[-1] == want                             # без полосы — прежний вызов (sym, n)


def test_set_command_band(monkeypatch):
    cfg = {**eg.DEFAULT, "symbol": "BTCUSDT", "regime_sma": 100}
    saved = {}
    monkeypatch.setattr(loop, "grid_config", lambda name: dict(cfg))
    monkeypatch.setattr(loop, "save_grid_config", lambda c, name: saved.update(c))
    out = loop.set_params("полоса 2", lambda: 100000.0, "B34")
    assert saved["regime_band_pct"] == 2.0 and "полоса режима 2%" in out
    assert "вне допустимого" in loop.set_params("полоса 15", lambda: 100000.0, "B34")


def test_symbol_band_mixed_is_unknown(monkeypatch):
    cfgs = {"BTC": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, "regime_sma": 100, "sides": ["LONG"],
                    "regime_band_pct": 2},
            "B34": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, "regime_sma": 100, "sides": ["LONG"],
                    "regime_band_pct": 2},
            "ETH": {"symbol": "ETHUSDT", "enabled": True, "dry_run": False, "regime_sma": 100, "sides": ["LONG"]}}
    monkeypatch.setattr(eg, "peek_config", cfgs.get)
    assert eg.symbol_band("BTCUSDT") == 2.0 and eg.symbol_band("ETHUSDT") == 0.0
    cfgs["B34"]["regime_band_pct"] = 1
    assert eg.symbol_band("BTCUSDT") is None
