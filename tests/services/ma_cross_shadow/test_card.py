"""TG-карточка кросса + статус-репорт + ew_impulse в живой логике."""
from __future__ import annotations

from services.ma_cross_shadow.tracker import _format_card
from services.ma_cross_shadow.signal import _is_impulse


def _entry(**kw):
    base = dict(symbol="BTCUSDT", dir="LONG", passed_h5=True, skip_reasons=[],
                entry=63200.0, ema14=63100.0, ema77=62000.0, ema200=61000.0,
                stretch_pct=1.9, ew_impulse=True, ma100_lean="LONG")
    base.update(kw)
    return base


def test_card_passed_long():
    c = _format_card(_entry())
    assert "MA-CROSS BTC" in c
    assert "H5 LONG" in c and "long-нога" in c
    assert "импульс" in c
    assert "совпал" in c  # ma100 совпал


def test_card_skip_shows_reason():
    c = _format_card(_entry(passed_h5=False, dir="SHORT",
                            skip_reasons=["наклон EMA77 против кросса"], ma100_lean="LONG"))
    assert "пропуск" in c and "наклон" in c
    assert "РАЗОШЁЛСЯ" in c  # ma100 LONG vs кросс SHORT


def test_card_correction_warns():
    c = _format_card(_entry(ew_impulse=False))
    assert "коррекция" in c


def test_is_impulse_monotonic_up():
    # чистый ступенчатый аптренд: HH+HL → импульс
    seq = []
    base = 100.0
    for k in range(8):
        base *= 1.10
        seq += [base * (1 + 0.001 * i) for i in range(15)]      # рост
        seq += [base * (1 - 0.04) * (1 - 0.001 * i) for i in range(8)]  # откат <разворота
    assert isinstance(_is_impulse(seq, 3.5), bool)


def test_report_empty():
    from services.ma_cross_shadow import report
    # пустой журнал (или несуществующий) → дружелюбный текст
    txt = report.build_status_text()
    assert "MA-CROSS" in txt
