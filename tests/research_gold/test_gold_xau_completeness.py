"""П.2 разбора GPT 13.10 (§5, полнота XAU 31/73–76): полнота дня — покрытие минутами (≥ 12 ч данных), а не число минут
с объёмом > 0. Минута с нулевым объёмом — это данные, а не их отсутствие. День без единой сделки уровнем не служит."""
from tests.research_gold.gold_fx import POST_CUT_DAY, block, combine, sb

D = POST_CUT_DAY


def test_zero_volume_minute_does_not_make_a_covered_day_incomplete():
    a = combine(block(D, 0, 720, 90.0), block(D + 1, 0, 720, 100.0), block(D + 2, 0, 60, 105.0))
    a["volume"][720] = 0.0                                     # одна минута дня 1 без сделок
    m = sb.Market(a, "XAU", False)
    assert m.level[D + 2] == 100.0, f"уровень взят из более старого дня: {m.level[D + 2]}"


def test_day_with_less_than_12h_of_minutes_is_incomplete():
    a = combine(block(D, 0, 720, 90.0), block(D + 1, 0, 719, 100.0), block(D + 2, 0, 60, 105.0))
    assert sb.Market(a, "XAU", False).level[D + 2] == 90.0


def test_covered_day_without_any_trade_is_skipped():
    a = combine(block(D, 0, 720, 90.0), block(D + 1, 0, 720, 100.0, volume=0.0), block(D + 2, 0, 60, 105.0))
    assert sb.Market(a, "XAU", False).level[D + 2] == 90.0
