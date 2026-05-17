"""Bot Brain — action vocabulary.

Each action has a `dispatch(proposal, mode)` callable. Modes:
  - "dry_run": journal proposal + return without touching GinArea
  - "live":    actually call GinArea API to enact change

Risk-tier policy (enforced at executor level, not here):
  - Production bots (5 managed): only safe actions in auto mode (pause/resume/recenter)
  - Testbed bot (tier="TB"): all actions allowed in auto mode

Audit: every action attempt (dry or live) appends to state/bot_brain_actions.jsonl.

Available actions:
  pause          — set p=False via GinArea set_params (existing short_bots_guard.control)
  resume         — set p=True
  resize         — change q.maxQ (and proportionally q.minQ) — TESTBED ONLY initially
  tighten_grid   — decrease gs by 30% — TESTBED ONLY
  widen_grid     — increase gs by 30% — TESTBED ONLY
  recenter       — STUB (needs careful design: kill+recreate)
  close_flat     — STUB (close position to 0)
  fix_partial    — STUB (close N% of position)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "state" / "bot_brain_actions.jsonl"


SAFE_PRODUCTION_ACTIONS = {"pause", "resume"}
TESTBED_ONLY_ACTIONS = {"resize", "tighten_grid", "widen_grid",
                         "recenter", "close_flat", "fix_partial"}
ALL_ACTIONS = SAFE_PRODUCTION_ACTIONS | TESTBED_ONLY_ACTIONS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _audit(record: dict) -> None:
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("bot_brain.actions.audit_failed")


def _api():
    """Build GinArea API client (reuses short_bots_guard.control._build_api)."""
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    return api, err


def _read_params(api, bot_id: str):
    return api.get_params(int(bot_id))


def _write_params(api, bot_id: str, new_params):
    return api.set_params(int(bot_id), new_params)


# ─── Action implementations ───────────────────────────────────────────────────

def _act_pause(bot_id: str, params: dict, mode: str, reason: str, rule_id: str) -> dict:
    """params: {} — no extras needed."""
    if mode == "dry_run":
        return {"status": "dry_run", "would_call": "control.pause_bot", "target_p": False}
    from services.short_bots_guard.control import pause_bot
    res = pause_bot(bot_id, dry_run=False, reason=reason, trigger=f"bot_brain:{rule_id}")
    return {"status": "live", "control_result": res}


def _act_resume(bot_id: str, params: dict, mode: str, reason: str, rule_id: str) -> dict:
    if mode == "dry_run":
        return {"status": "dry_run", "would_call": "control.resume_bot", "target_p": True}
    from services.short_bots_guard.control import resume_bot
    res = resume_bot(bot_id, dry_run=False, reason=reason, trigger=f"bot_brain:{rule_id}")
    return {"status": "live", "control_result": res}


def _act_resize(bot_id: str, params: dict, mode: str, reason: str, rule_id: str) -> dict:
    """params: {factor: 0.5} → multiply current q.maxQ and q.minQ by factor."""
    factor = float(params.get("factor", 0.5))
    if mode == "dry_run":
        return {"status": "dry_run", "would_change": f"q.maxQ × {factor}, q.minQ × {factor}",
                "factor": factor}
    api, err = _api()
    if api is None:
        return {"status": "error", "error": err}
    try:
        from dataclasses import replace
        current = _read_params(api, bot_id)
        new_maxQ = (current.q.maxQ or 0) * factor
        new_minQ = (current.q.minQ or 0) * factor
        new_q = replace(current.q, maxQ=new_maxQ, minQ=new_minQ)
        new_params = replace(current, q=new_q)
        _write_params(api, bot_id, new_params)
        return {"status": "live", "old_maxQ": current.q.maxQ, "new_maxQ": new_maxQ,
                "old_minQ": current.q.minQ, "new_minQ": new_minQ, "factor": factor}
    except Exception as e:
        logger.exception("bot_brain.actions.resize_failed bot=%s", bot_id)
        return {"status": "error", "error": str(e)}


def _act_tighten_grid(bot_id: str, params: dict, mode: str, reason: str, rule_id: str) -> dict:
    """params: {factor: 0.7} → multiply gs by factor (default 0.7 = 30% tighter)."""
    factor = float(params.get("factor", 0.7))
    if mode == "dry_run":
        return {"status": "dry_run", "would_change": f"gs × {factor}", "factor": factor}
    api, err = _api()
    if api is None:
        return {"status": "error", "error": err}
    try:
        from dataclasses import replace
        current = _read_params(api, bot_id)
        new_gs = (current.gs or 0) * factor
        new_params = replace(current, gs=new_gs)
        _write_params(api, bot_id, new_params)
        return {"status": "live", "old_gs": current.gs, "new_gs": new_gs, "factor": factor}
    except Exception as e:
        logger.exception("bot_brain.actions.tighten_failed bot=%s", bot_id)
        return {"status": "error", "error": str(e)}


def _act_widen_grid(bot_id: str, params: dict, mode: str, reason: str, rule_id: str) -> dict:
    """params: {factor: 1.3} → multiply gs by factor."""
    factor = float(params.get("factor", 1.3))
    return _act_tighten_grid(bot_id, {"factor": factor}, mode, reason, rule_id)


def _act_stub(action: str):
    """Stub for actions not yet implemented."""
    def _impl(bot_id, params, mode, reason, rule_id):
        msg = f"action '{action}' not yet implemented in Phase 2 (planned)"
        if mode == "dry_run":
            return {"status": "dry_run", "would_call": action, "note": msg}
        return {"status": "skip_not_implemented", "note": msg}
    return _impl


DISPATCH = {
    "pause": _act_pause,
    "resume": _act_resume,
    "resize": _act_resize,
    "tighten_grid": _act_tighten_grid,
    "widen_grid": _act_widen_grid,
    "recenter": _act_stub("recenter"),
    "close_flat": _act_stub("close_flat"),
    "fix_partial": _act_stub("fix_partial"),
}


def dispatch(action: str, bot_id: str, *, params: Optional[dict] = None,
             mode: str = "dry_run", reason: str = "", rule_id: str = "") -> dict:
    """Dispatch action by name. Returns audit record (also appended to actions.jsonl)."""
    if action not in DISPATCH:
        rec = {"ts": _now_iso(), "bot_id": bot_id, "action": action, "mode": mode,
               "status": "error", "error": f"unknown action: {action}",
               "rule_id": rule_id, "reason": reason}
        _audit(rec)
        return rec

    impl = DISPATCH[action]
    try:
        outcome = impl(bot_id, params or {}, mode, reason, rule_id)
    except Exception as e:
        logger.exception("bot_brain.dispatch_failed action=%s bot=%s", action, bot_id)
        outcome = {"status": "exception", "error": str(e)}

    rec = {"ts": _now_iso(), "bot_id": bot_id, "action": action, "mode": mode,
           "params": params or {}, "reason": reason, "rule_id": rule_id, **outcome}
    _audit(rec)
    return rec
