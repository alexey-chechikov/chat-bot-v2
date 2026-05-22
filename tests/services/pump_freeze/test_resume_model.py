"""Tests for the pump_freeze ML resume-gate (Phase 4 skeleton).

Covers the safety contract: no model -> None; injected stub model -> score;
missing/NaN feature -> None; no feature_order -> None; threshold mapping.
No model artifact on disk in the test env, so the on-disk path is exercised
via _reset_cache() + the absence of models/pump_resume_gbm.joblib.
"""
from services.pump_freeze import resume_model


class _StubModel:
    """Minimal predict_proba stub — class-1 (whipsaw) probability = p."""

    def __init__(self, p: float) -> None:
        self.p = p

    def predict_proba(self, X):
        return [[1.0 - self.p, self.p] for _ in X]


META = {
    "feature_order": ["a", "b"],
    "horizon_min": 30,
    "whipsaw_threshold": 0.65,
    "trend_threshold": 0.35,
}


def test_score_none_without_model():
    """No artifact on disk → unscorable → None (reactive fallback)."""
    resume_model._reset_cache()
    assert resume_model.score_event({"a": 1.0, "b": 2.0}) is None
    assert resume_model.model_available() is False


def test_score_with_injected_model():
    s = resume_model.score_event({"a": 1.0, "b": 2.0},
                                 model=_StubModel(0.8), meta=META)
    assert s is not None and abs(s - 0.8) < 1e-9


def test_score_none_on_missing_feature():
    # 'b' absent → cannot build the vector → None
    s = resume_model.score_event({"a": 1.0},
                                 model=_StubModel(0.8), meta=META)
    assert s is None


def test_score_none_on_nan_feature():
    s = resume_model.score_event({"a": float("nan"), "b": 2.0},
                                 model=_StubModel(0.8), meta=META)
    assert s is None


def test_score_none_without_feature_order():
    s = resume_model.score_event({"a": 1.0}, model=_StubModel(0.8), meta={})
    assert s is None


def test_gate_decision_thresholds():
    assert resume_model.gate_decision(0.80, meta=META) == "whipsaw"
    assert resume_model.gate_decision(0.20, meta=META) == "trend"
    assert resume_model.gate_decision(0.50, meta=META) == "grey"
    assert resume_model.gate_decision(None, meta=META) == "grey"


def test_gate_decision_boundary_inclusive():
    # exactly on the thresholds — whipsaw_threshold/trend_threshold inclusive
    assert resume_model.gate_decision(0.65, meta=META) == "whipsaw"
    assert resume_model.gate_decision(0.35, meta=META) == "trend"
