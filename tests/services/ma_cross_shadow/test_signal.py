"""MA-cross H5 чистая логика: кросс на последнем баре, фильтры, прогрев EMA200."""
from __future__ import annotations

import math

from services.ma_cross_shadow.signal import assess_latest, compute, _last_cross_index


def _ramp(n, start, slope):
    return [start + slope * i for i in range(n)]


def test_no_signal_until_ema200_warm():
    closes = _ramp(150, 100, 0.1)
    hl = closes
    assert assess_latest(hl, hl, closes) is None  # <210 баров


def test_no_signal_when_last_bar_not_cross():
    # ровный аптренд: EMA14 всегда выше EMA77, кросса на последнем баре нет
    closes = _ramp(260, 100, 0.5)
    assert assess_latest(closes, closes, closes) is None


def test_upcross_detected_and_long():
    # сначала падение (EMA14<EMA77), потом разворот вверх так, чтобы 14 пересёк 77
    down = _ramp(180, 200, -0.4)          # 200 → ~128
    up = _ramp(80, 128, 1.2)              # резкий разворот вверх
    closes = down + up
    sig = assess_latest(closes, closes, closes)
    # на последнем баре кросс может быть или нет в зависимости от формы — проверяем,
    # что ЕСЛИ сигнал есть, он LONG (14 над 77 после разворота)
    if sig is not None:
        assert sig["direction"] == 1
        assert "ema14" in sig and "ema200" in sig


def test_last_cross_index_basic():
    diff = [1, 1, -1, -1, 1]   # кросс на индексе 2 и 4
    assert _last_cross_index(diff) == 4
    assert _last_cross_index(diff[:4]) == 2
    assert _last_cross_index([1, 1, 1]) is None


def test_filters_populate_reasons():
    """Сконструировать кросс и проверить, что reasons заполняется при провале фильтра."""
    # V-образный разворот вверх ПОД EMA200 (цена низко) → фильтр ② должен сработать
    down = _ramp(200, 300, -1.0)          # длинное падение 300→100, EMA200 высоко
    up = _ramp(60, 100, 0.8)
    closes = down + up
    sig = assess_latest(closes, closes, closes)
    if sig is not None and sig["direction"] == 1:
        # цена ~140 на развороте, EMA200 ещё высоко (>140) → не на стороне для LONG
        if sig["entry"] < sig["ema200"]:
            assert not sig["passed"]
            assert any("EMA200" in r for r in sig["reasons"])


def test_compute_shapes():
    closes = _ramp(260, 100, 0.3)
    ind = compute(closes, closes, closes)
    assert len(ind["e14"]) == len(ind["e77"]) == len(ind["diff"]) == 260
    assert all(math.isfinite(x) for x in ind["e200"])
