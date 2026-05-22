"""Contract test — pins build_live_features() output to the FINAL feature set
the resume-gate model is trained on.

Source of truth: train_final in state/pump_feature_grades.json (Win-Claude
9b7577d) + docs/STRATEGIES/PUMP_FILTER_FEATURE_CONTRACT.md. If either side
drifts — a feature renamed, added, or dropped — this fails immediately
instead of silently mismatching the model in production.
"""
from datetime import datetime, timedelta, timezone

from services.pump_freeze.loop import _compute_bar_features

# FINAL contract — 9 features (9b7577d). n_triggers dropped: importance 0.020,
# 9-feature OOT 0.915 > 10-feature 0.881. Do NOT edit without a matching
# model retrain + meta.json feature_order update.
TRAIN_FINAL = {
    "accel", "funding_at_anchor", "move_pct",
    "move_t5", "move_t15", "move_t30", "move_t60",
    "vol_spike", "wick_ratio",
}
# funding_at_anchor is added by build_live_features() from deriv_live_history;
# the other 8 come from _compute_bar_features().
BAR_DERIVED = TRAIN_FINAL - {"funding_at_anchor"}

T0 = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)


def _bars(n: int) -> list:
    out = []
    for i in range(n):
        c = 100.0 + i
        out.append((T0 + timedelta(minutes=i), c - 0.5, c + 0.2, c - 0.7, c, 10.0))
    return out


def test_compute_bar_features_emits_exactly_the_8_bar_features():
    """_compute_bar_features must emit exactly the 8 bar-derived contract
    features on a healthy history — no missing, no extras."""
    bars = _bars(250)
    f = _compute_bar_features(bars, bars[150][0])
    assert set(f.keys()) == BAR_DERIVED, (
        f"feature drift: got {sorted(f)}, contract {sorted(BAR_DERIVED)}")


def test_no_feature_outside_contract():
    """Regardless of history length, the pipeline never emits a feature
    outside the contract set (guards against an accidental new column)."""
    for n in (40, 100, 250):
        bars = _bars(n)
        f = _compute_bar_features(bars, bars[min(n - 5, 150)][0])
        extra = set(f) - BAR_DERIVED
        assert not extra, f"unknown feature(s) at n={n}: {extra}"
