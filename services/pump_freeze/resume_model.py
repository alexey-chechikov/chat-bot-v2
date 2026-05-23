"""ML resume-gate for pump_freeze — Phase 4, per-symbol artifact loading.

A trained GBM (per symbol) scores a frozen pump/dump event trend-vs-whipsaw.
On a confident "whipsaw" verdict the loop resumes the bot EARLY — before
reactive retrace / stall fires — because a whipsaw is where the grid earns.

Per-symbol artifacts live in models/, one pair per symbol:
  models/{SYMBOL}_pump_resume_gbm.joblib    — classifier with predict_proba;
                                              class 1 = whipsaw.
  models/{SYMBOL}_pump_resume_gbm.meta.json — {"feature_order":[...],
                                               "horizon_min":60,
                                               "whipsaw_threshold":0.65,
                                               "trend_threshold":0.35, ...}

SAFETY CONTRACT — the gate is a NO-OP whenever the artifact for the bot's
symbol is missing, joblib/sklearn is unavailable, or any required feature is
absent/NaN in the live feature dict — score_event() returns None and the
caller falls back to reactive resume.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

# Defaults — used only if meta.json omits the key.
_DEFAULT_HORIZON_MIN = 60.0
_DEFAULT_WHIPSAW_THR = 0.65
_DEFAULT_TREND_THR = 0.35

# Per-symbol cache: symbol -> (model, meta). _UNSET = load not yet attempted.
_UNSET: Any = object()
_cache: dict = {}


def _model_path(symbol: str) -> Path:
    return ROOT / "models" / f"{symbol}_pump_resume_gbm.joblib"


def _meta_path(symbol: str) -> Path:
    return ROOT / "models" / f"{symbol}_pump_resume_gbm.meta.json"


def _load(symbol: str = "BTCUSDT") -> tuple[Any, dict]:
    """Lazy-load (model, meta) for `symbol`, cached. (None, {}) if missing."""
    if symbol in _cache:
        return _cache[symbol]
    model = None
    meta: dict = {}
    mp = _model_path(symbol)
    if mp.exists():
        try:
            import joblib  # noqa: PLC0415  (optional dep — only needed live)
            model = joblib.load(mp)
        except Exception as e:  # noqa: BLE001
            logger.warning("resume_model.load_failed %s: %r", mp.name, e)
            model = None
    mtp = _meta_path(symbol)
    if mtp.exists():
        try:
            meta = json.loads(mtp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("resume_model.meta_load_failed %s: %r", mtp.name, e)
            meta = {}
    _cache[symbol] = (model, meta)
    if model is not None:
        logger.info("resume_model.loaded symbol=%s features=%d horizon=%s",
                    symbol, len(meta.get("feature_order", [])),
                    meta.get("horizon_min"))
    return model, meta


def model_available(symbol: str = "BTCUSDT") -> bool:
    """True only when a usable model artifact for `symbol` is loaded."""
    model, _ = _load(symbol)
    return model is not None


def horizon_min(symbol: str = "BTCUSDT") -> float:
    """Earliest freeze-age (minutes) at which the ML-gate may resume for `symbol`."""
    _, meta = _load(symbol)
    return float(meta.get("horizon_min", _DEFAULT_HORIZON_MIN))


def score_event(features: dict, symbol: str = "BTCUSDT", *,
                model: Any = _UNSET,
                meta: Optional[dict] = None) -> Optional[float]:
    """P(whipsaw) in [0, 1] for a frozen event of `symbol`, or None if unscorable.

    `model`/`meta` may be injected for testing; otherwise the cached per-symbol
    artifact is used. Returns None when: no model, meta lacks feature_order,
    or any required feature is missing/NaN in `features` — caller then falls
    back to reactive resume logic.
    """
    if model is _UNSET:
        model, meta = _load(symbol)
    if meta is None:
        meta = {}
    if model is None:
        return None
    order = meta.get("feature_order")
    if not order:
        logger.warning("resume_model.no_feature_order symbol=%s — cannot score", symbol)
        return None
    vec: list[float] = []
    for name in order:
        v = features.get(name)
        if v is None or (isinstance(v, float) and v != v):  # missing / NaN
            logger.debug("resume_model.missing_feature %s for %s — skip score",
                         name, symbol)
            return None
        vec.append(float(v))
    try:
        proba = model.predict_proba([vec])[0]
        return float(proba[1])  # class 1 = whipsaw, by contract
    except Exception as e:  # noqa: BLE001
        logger.warning("resume_model.predict_failed symbol=%s: %r", symbol, e)
        return None


def gate_decision(score: Optional[float], symbol: str = "BTCUSDT", *,
                  meta: Optional[dict] = None) -> str:
    """Map P(whipsaw) -> 'whipsaw' | 'trend' | 'grey'.

    'grey' (and a None score) -> defer to reactive resume logic.
    """
    if score is None:
        return "grey"
    if meta is None:
        _, meta = _load(symbol)
    wt = float(meta.get("whipsaw_threshold", _DEFAULT_WHIPSAW_THR))
    tt = float(meta.get("trend_threshold", _DEFAULT_TREND_THR))
    if score >= wt:
        return "whipsaw"
    if score <= tt:
        return "trend"
    return "grey"


def _reset_cache(symbol: Optional[str] = None) -> None:
    """Test helper — drop cached artifact(s). None = drop all symbols."""
    if symbol is None:
        _cache.clear()
    else:
        _cache.pop(symbol, None)
