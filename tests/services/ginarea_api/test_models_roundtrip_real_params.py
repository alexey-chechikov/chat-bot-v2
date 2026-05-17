"""Roundtrip tests for DefaultGridParams with REAL production-shape params.

Regression guard for 2026-05-17 API-spam incident: the existing test fixture
`sample_default_grid_params` was a subset of GinArea API response (missing
`in.start.cnds` block among others). DefaultGridParams.from_dict silently
dropped any field not in its explicit list, to_dict never emitted them, so
set_params calls sent bodies missing required `in.start.cnds[]` → API
rejected ALL writes with errorCode:-1 "conditions array is empty in start block".

These tests use a REAL T1-shape params capture from ginarea_live/params.csv
and assert that:
  1. Every key in the input survives the full from_dict → to_dict roundtrip
  2. Modifying `p` via dataclasses.replace preserves all other fields
  3. extra_raw bucket holds the non-explicit fields verbatim
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from services.ginarea_api.models import DefaultGridParams


REAL_T1_PARAMS = {
    "border": {"bottom": 75000, "top": 85000},
    "cf": 0.00035,
    "dsblin": False,
    "dsblinbap": False,
    "dsblinbtr": False,
    "gap": {"isg": 0.018, "maxS": 0.035, "minS": 0.012, "tog": 0.21},
    "gs": 0.02,
    "gsr": None,
    "hedge": False,
    # ─── This is the field that was being dropped ────────────────────────────
    "in": {
        "otc": True,
        "otcPassed": False,
        "restart": False,
        "start": {
            "cnds": [{
                "items": [{"op": ">", "p": 0.7, "v": "ind"}],
                "params": {"d": 30, "tf": "1m"},
                "type": "PRICE%",
            }],
            "logic": None,
        },
        "stop": None,
    },
    "leverage": 0,
    "lsl": None,
    "maxOp": 220,
    "obap": False,
    "p": True,
    "q": {"maxQ": 0.002, "minQ": 0.001, "qr": 1.02},
    "side": 2,
    "slp": {"m": 0, "pp": 50, "tp": 10},
    "slt": False,
    "tr": {"mdTr": 0, "minToTr": 0, "tr": 0},
    "tsl": None,
    "ttp": 12,
    "ttpinc": 12,
    "ul": None,
}


def test_roundtrip_preserves_in_block():
    """Critical regression test — `in.start.cnds` MUST survive from_dict → to_dict.
    Previously: dropped silently, GinArea rejected with errorCode:-1."""
    parsed = DefaultGridParams.from_dict(REAL_T1_PARAMS)
    emitted = parsed.to_dict()
    assert "in" in emitted, "in block dropped on to_dict — would cause errorCode:-1"
    assert "start" in emitted["in"]
    assert "cnds" in emitted["in"]["start"]
    assert len(emitted["in"]["start"]["cnds"]) == 1
    cnd = emitted["in"]["start"]["cnds"][0]
    assert cnd["type"] == "PRICE%"
    assert cnd["items"][0]["op"] == ">"
    assert cnd["items"][0]["p"] == 0.7


def test_roundtrip_preserves_all_input_keys():
    """Every top-level key in input MUST appear in output (no silent drops)."""
    parsed = DefaultGridParams.from_dict(REAL_T1_PARAMS)
    emitted = parsed.to_dict()
    missing = set(REAL_T1_PARAMS.keys()) - set(emitted.keys())
    assert not missing, f"keys silently dropped on roundtrip: {missing}"


def test_pause_replace_only_flips_p():
    """Simulate pause_bot path: replace(p=False), serialize, diff vs original.
    Only `p` should differ — all other fields including `in` preserved verbatim."""
    parsed = DefaultGridParams.from_dict(REAL_T1_PARAMS)
    modified = replace(parsed, p=False)
    emitted = modified.to_dict()
    # p flipped
    assert emitted["p"] is False
    # Every other top-level field unchanged
    for k, v in REAL_T1_PARAMS.items():
        if k == "p":
            continue
        assert emitted[k] == v, f"field {k} mutated unexpectedly: {REAL_T1_PARAMS[k]} → {emitted[k]}"


def test_resume_replace_only_flips_p():
    """Same for resume direction."""
    paused = {**REAL_T1_PARAMS, "p": False}
    parsed = DefaultGridParams.from_dict(paused)
    modified = replace(parsed, p=True)
    emitted = modified.to_dict()
    assert emitted["p"] is True
    for k, v in paused.items():
        if k == "p":
            continue
        assert emitted[k] == v, f"field {k} mutated on resume: {paused[k]} → {emitted[k]}"


def test_extra_raw_captures_in_block():
    """extra_raw bucket should contain all fields NOT in _EXPLICIT_KEYS — in particular `in`."""
    parsed = DefaultGridParams.from_dict(REAL_T1_PARAMS)
    assert "in" in parsed.extra_raw
    assert parsed.extra_raw["in"] == REAL_T1_PARAMS["in"]


def test_explicit_field_wins_over_extra_raw():
    """If extra_raw contains a key that's also in _EXPLICIT_KEYS, to_dict must
    emit the explicit field value (so replace(p=False) overrides any stale
    extra_raw value)."""
    parsed = DefaultGridParams.from_dict(REAL_T1_PARAMS)
    # Manually inject a stale `p` into extra_raw (shouldn't happen normally,
    # but defends against malformed input)
    parsed_with_stale = replace(parsed, p=False, extra_raw={**parsed.extra_raw, "p": True})
    emitted = parsed_with_stale.to_dict()
    assert emitted["p"] is False, "explicit p must override stale extra_raw['p']"


def test_unknown_future_field_passthrough():
    """If GinArea adds a new field tomorrow, passthrough must preserve it
    without code changes."""
    future_params = {**REAL_T1_PARAMS, "newFutureField": {"a": 1, "b": [2, 3]}}
    parsed = DefaultGridParams.from_dict(future_params)
    emitted = parsed.to_dict()
    assert emitted["newFutureField"] == {"a": 1, "b": [2, 3]}
