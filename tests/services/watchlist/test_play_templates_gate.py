"""Гейт по размеру выборки: n<30 в ленту не идёт (2026-07-29)."""
from services.watchlist.play_templates import (
    MIN_SAMPLE_N, PLAYS, play_sample_n, play_underpowered,
)


def test_sample_n_parsed_from_edge_string():
    assert play_sample_n("funding_squeeze_long") == 10
    assert play_sample_n("cascade_short_continuation_long") == 139


def test_underpowered_plays_flagged():
    """n=10 при 70% — ДИ примерно 35-93%, монетка. Не в ленту."""
    assert play_underpowered("funding_squeeze_long") is True
    assert play_underpowered("cascade_long_reversal_short") is True   # n=20
    assert play_underpowered("cascade_short_continuation_long") is False  # n=139


def test_threshold_matches_project_standard():
    assert MIN_SAMPLE_N == 30


def test_unknown_label_is_not_flagged():
    assert play_underpowered("нет_такого") is False


def test_all_plays_have_parseable_sample_size():
    missing = [k for k in PLAYS if play_sample_n(k) is None]
    assert not missing, f"плеи без n= в edge: {missing}"
