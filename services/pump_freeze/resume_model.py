"""ML resume-gate for pump_freeze — Phase 4 (PUMP_DUMP_FILTER_v2).

A trained GBM (Win's validated pipeline, OOT AUC ~0.84) scores a frozen
pump/dump event trend-vs-whipsaw. On a confident "whipsaw" verdict the loop
resumes the bot EARLY — before the reactive retrace / stall conditions fire —
because a whipsaw is exactly where the grid earns and freezing it is the
mistake the whole filter exists to avoid.

SAFETY CONTRACT — the gate is a NO-OP until the model artifact is present:

  models/pump_resume_gbm.joblib    — classifier with predict_proba;
                                     class 1 = whipsaw.
  models/pump_resume_gbm.meta.json — {"feature_order": [...],
                                      "horizon_min": 30,
                                      "whipsaw_threshold": 0.65,
                                      "trend_threshold": 0.35}

If either file is missing, joblib/sklearn is unavailable, or a feature the
model needs is absent/NaN in the live feature dict — score_event() returns
None and the caller falls back to the reactive resume logic. So this module
is safe to ship before the model lands: it simply does nothing.

Phase-4 fill-ins still owed:
  - Win: commit the .joblib + meta.json (frozen validated model).
  - Mac: complete loop.build_live_features() so it emits every feature in
    meta["feature_order"] from live data.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "models" / "pump_resume_gbm.joblib"
META_PATH = ROOT / "models" / "pump_resume_gbm.meta.json"

# Defaults — used only if meta.json omits the key.
_DEFAULT_HORIZON_MIN = 30.0
_DEFAULT_WHIPSAW_THR = 0.65
_DEFAULT_TREND_THR = 0.35

# Module-level cache: artifact loaded once. _UNSET = load not yet attempted.
_UNSET: Any = object()
_model_cache: Any = _UNSET
_meta_cache: Optional[dict] = None


def _load() -> tuple[Any, dict]:
    """Lazy-load (model, meta), cached. Returns (None, {}) when unavailable."""
    global _model_cache, _meta_cache
    if _model_cache is not _UNSET:
        return _model_cache, (_meta_cache or {})
    model = None
    meta: dict = {}
    if MODEL_PATH.exists():
        try:
            import joblib  # noqa: PLC0415  (optional dep — only needed live)
            model = joblib.load(MODEL_PATH)
        except Exception as e:  # noqa: BLE001
            logger.warning("resume_model.load_failed %s: %r", MODEL_PATH.name, e)
            model = None
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("resume_model.meta_load_failed: %r", e)
            meta = {}
    _model_cache = model
    _meta_cache = meta
    if model is not None:
        logger.info("resume_model.loaded features=%d horizon=%smin",
                    len(meta.get("feature_order", [])), meta.get("horizon_min"))
    return model, meta


def model_available() -> bool:
    """True only when a usable model artifact is loaded."""
    model, _ = _load()
    return model is not None


def horizon_min() -> float:
    """Earliest freeze-age (minutes) at which the ML-gate may resume."""
    _, meta = _load()
    return float(meta.get("horizon_min", _DEFAULT_HORIZON_MIN))


def score_event(features: dict, *, model: Any = _UNSET,
                meta: Optional[dict] = None) -> Optional[float]:
    """P(whipsaw) in [0, 1] for a frozen event, or None if unscorable.

    `model`/`meta` may be injected for testing; otherwise the cached artifact
    is used. Returns None when: no model, meta lacks feature_order, or any
    required feature is missing/NaN in `features` — caller then falls back to
    reactive resume logic.
    """
    if model is _UNSET:
        model, meta = _load()
    if meta is None:
        meta = {}
    if model is None:
        return None
    order = meta.get("feature_order")
    if not order:
        logger.warning("resume_model.no_feature_order — cannot score")
        return None
    vec: list[float] = []
    for name in order:
        v = features.get(name)
        if v is None or (isinstance(v, float) and v != v):  # missing / NaN
            logger.debug("resume_model.missing_feature %s — skip score", name)
            return None
        vec.append(float(v))
    try:
        proba = model.predict_proba([vec])[0]
        return float(proba[1])  # class 1 = whipsaw, by contract
    except Exception as e:  # noqa: BLE001
        logger.warning("resume_model.predict_failed: %r", e)
        return None


def gate_decision(score: Optional[float], *,
                  meta: Optional[dict] = None) -> str:
    """Map P(whipsaw) → 'whipsaw' | 'trend' | 'grey'.

    'grey' (and a None score) → defer to the reactive resume logic.
    """
    if score is None:
        return "grey"
    if meta is None:
        _, meta = _load()
    wt = float(meta.get("whipsaw_threshold", _DEFAULT_WHIPSAW_THR))
    tt = float(meta.get("trend_threshold", _DEFAULT_TREND_THR))
    if score >= wt:
        return "whipsaw"
    if score <= tt:
        return "trend"
    return "grey"


def _reset_cache() -> None:
    """Test helper — drop the cached artifact so the next _load() re-runs."""
    global _model_cache, _meta_cache
    _model_cache = _UNSET
    _meta_cache = None
