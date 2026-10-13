"""П.1 разбора GPT 13.10 (§5, LVN 106–113): профиль LVN строится ТОЛЬКО из выбранных полных дней строго до дня сигнала —
без хвоста «до конца файла» и без пропущенных неполных дней между выбранными."""
import numpy as np

from tests.research_gold.gold_fx import POST_CUT_DAY, block, combine, sb

D = POST_CUT_DAY


def _same(z1, z2) -> bool:
    return all(np.array_equal(x, y) for x, y in zip(z1, z2))


def test_lvn_profile_does_not_see_future_when_next_calendar_day_is_absent():
    # дни 0, 1, 3, 4 (дня 2 нет); профиль дня 3 = дни 0 и 1; изменение дня 4 не должно его менять
    a = combine(block(D, 0, 15, 100), block(D + 1, 0, 15, 105), block(D + 3, 0, 15, 110), block(D + 4, 0, 15, 120))
    z1 = sb.Market(a, "PAXG", False).lvn(D + 3)
    changed = {k: v.copy() for k, v in a.items()}
    future = changed["ts"] >= (D + 4) * sb.DAY
    for k in ("open", "high", "low", "close"):
        changed[k][future] = 300.0
    z2 = sb.Market(changed, "PAXG", False).lvn(D + 3)
    assert z1 is not None and z2 is not None
    assert _same(z1, z2), f"профиль дня сигнала зависит от будущего дня: край {z1[0][-1]} → {z2[0][-1]}"
    assert z1[0][-1] < 110, "в профиль попали дни 3/4 (день сигнала и позже)"


def _xau_day(day: int) -> dict:
    """720 минут: первая половина в [1000, 1004], вторая — в [1006, 1010] → корзины 1004–1006 пустые (LVN)."""
    lo = block(day, 0, 360, 1002.0)
    lo["low"][:], lo["high"][:] = 1000.0, 1004.0
    hi = block(day, 360, 360, 1008.0)
    hi["low"][:], hi["high"][:] = 1006.0, 1010.0
    return combine(lo, hi)


def test_lvn_profile_uses_only_selected_complete_days_not_the_gap_between_them():
    # XAU: дни 0 и 2 полные (720 минут), день 1 — одна минута (неполный) с объёмом 500 ровно в «дыре» профиля
    gap_day = block(D + 1, 0, 1, 1005.0, volume=500.0)
    gap_day["low"][:], gap_day["high"][:] = 1004.2, 1005.8
    with_gap = combine(_xau_day(D), gap_day, _xau_day(D + 2), block(D + 3, 0, 60, 1005.0))
    without_gap = combine(_xau_day(D), _xau_day(D + 2), block(D + 3, 0, 60, 1005.0))
    z_with = sb.Market(with_gap, "XAU", False).lvn(D + 3)
    z_without = sb.Market(without_gap, "XAU", False).lvn(D + 3)
    assert z_without is not None and z_without[1].any(), "фикстура должна давать LVN-зону в дыре профиля"
    assert z_with is not None
    assert _same(z_with, z_without), "объём неполного промежуточного дня попал в профиль выбранных дней"
