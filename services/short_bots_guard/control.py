"""Pause / Resume bot via GinArea API (set_params with p=false/true).

Использует services/ginarea_api/bots.py BotsAPI. Авторизация через
GINAREA_EMAIL / GINAREA_PASSWORD_SHA1 / GINAREA_TOTP_SECRET env vars.

Idempotent: pause_bot не делает второй PUT если бот уже paused.
audit-log: каждое действие пишется в state/short_bots_audit.jsonl.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "state" / "short_bots_audit.jsonl"


def _audit(record: dict) -> None:
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("short_bots_guard.audit_failed")


def _load_ginarea_env() -> dict:
    """Load GinArea credentials from os.environ or ginarea_tracker/.env fallback."""
    import os
    env = {}
    for k in ("GINAREA_EMAIL", "GINAREA_PASSWORD", "GINAREA_PASSWORD_SHA1", "GINAREA_TOTP_SECRET"):
        v = os.environ.get(k)
        if v:
            env[k] = v
    if all(env.get(k) for k in ("GINAREA_EMAIL", "GINAREA_TOTP_SECRET")) and \
       (env.get("GINAREA_PASSWORD") or env.get("GINAREA_PASSWORD_SHA1")):
        return env
    # Fallback: parse ginarea_tracker/.env
    tracker_env = ROOT / "ginarea_tracker" / ".env"
    if tracker_env.exists():
        try:
            for line in tracker_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in ("GINAREA_EMAIL", "GINAREA_PASSWORD",
                         "GINAREA_PASSWORD_SHA1", "GINAREA_TOTP_SECRET") and v:
                    env.setdefault(k, v)
        except OSError:
            pass
    return env


def _build_api():
    """Construct BotsAPI authenticated client. Returns (api, error)."""
    import hashlib
    import os
    try:
        from services.ginarea_api.auth import GinAreaAuth
        from services.ginarea_api.bots import BotsAPI
        from services.ginarea_api.client import GinAreaClient
    except Exception as e:
        return None, f"import_failed: {e}"

    env = _load_ginarea_env()
    email = env.get("GINAREA_EMAIL")
    totp = env.get("GINAREA_TOTP_SECRET")
    if not email or not totp:
        return None, f"missing_env: email={bool(email)}, totp={bool(totp)}"

    # Derive SHA1 from plain password if SHA1 not provided
    pwd_sha1 = env.get("GINAREA_PASSWORD_SHA1")
    if not pwd_sha1 and env.get("GINAREA_PASSWORD"):
        pwd_sha1 = hashlib.sha1(env["GINAREA_PASSWORD"].encode("utf-8")).hexdigest()
    if not pwd_sha1:
        return None, "missing_env: no GINAREA_PASSWORD or GINAREA_PASSWORD_SHA1"

    # Inject into os.environ so GinAreaAuth.from_env() picks them up
    os.environ["GINAREA_EMAIL"] = email
    os.environ["GINAREA_PASSWORD_SHA1"] = pwd_sha1
    os.environ["GINAREA_TOTP_SECRET"] = totp

    try:
        auth = GinAreaAuth.from_env()
        client = GinAreaClient(auth=auth)
        return BotsAPI(client), None
    except Exception as e:
        logger.exception("short_bots_guard.api_init_failed")
        return None, f"init_failed: {e}"


def get_bot_state(bot_id: str) -> dict:
    """Get current bot params. Returns {bot_id, p, ok, error?}."""
    api, err = _build_api()
    if api is None:
        return {"bot_id": bot_id, "ok": False, "error": err}
    try:
        params = api.get_params(int(bot_id))
        return {
            "bot_id": bot_id,
            "ok": True,
            "p": bool(params.p),
            "gs": params.gs,
            "side": int(params.side) if params.side is not None else None,
        }
    except Exception as e:
        logger.exception("short_bots_guard.get_state_failed bot=%s", bot_id)
        return {"bot_id": bot_id, "ok": False, "error": str(e)}


def is_paused(bot_id: str) -> Optional[bool]:
    """True/False/None (если API недоступен)."""
    state = get_bot_state(bot_id)
    if not state.get("ok"):
        return None
    return not state.get("p", True)  # paused == not active


# Per-bot cached state of (p, mono_ts_seconds). TTL CACHE_TTL_SEC — within that
# window, skip the GET API call when target matches cache. Reduces GinArea
# read traffic substantially: once a bot is paused (target=False, cache=False)
# next 60s of pause-proposals are noop without any API call.
_state_cache: dict[str, tuple[bool, float]] = {}
CACHE_TTL_SEC = 60.0


def _set_p(bot_id: str, target_p: bool, *, dry_run: bool = False,
            reason: str = "", trigger: str = "") -> dict:
    """Internal: set p flag. Returns audit record.
    2026-05-17: added in-memory cache to skip GET when target matches recent
    known state — reduces API spam to GinArea."""
    import time
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Cache fast-path: if we know p was target_p recently — no API call needed
    cached = _state_cache.get(bot_id)
    if cached is not None:
        cached_p, cached_ts = cached
        if (time.monotonic() - cached_ts) <= CACHE_TTL_SEC and cached_p == target_p:
            rec = {
                "ts": now, "bot_id": bot_id, "action": "noop_cached",
                "current_p": cached_p, "target_p": target_p,
                "reason": reason, "trigger": trigger,
            }
            _audit(rec)
            return rec

    api, err = _build_api()
    if api is None:
        rec = {
            "ts": now, "bot_id": bot_id, "action": "skip_api_unavailable",
            "target_p": target_p, "reason": reason, "trigger": trigger,
            "error": err,
        }
        _audit(rec)
        return rec

    try:
        current = api.get_params(int(bot_id))
    except Exception as e:
        logger.exception("short_bots_guard.read_params_failed bot=%s", bot_id)
        rec = {
            "ts": now, "bot_id": bot_id, "action": "skip_read_failed",
            "target_p": target_p, "reason": reason, "trigger": trigger,
            "error": str(e),
        }
        _audit(rec)
        return rec

    current_p = bool(current.p) if current.p is not None else True
    # Update cache from fresh read regardless of branch
    import time
    _state_cache[bot_id] = (current_p, time.monotonic())

    if current_p == target_p:
        rec = {
            "ts": now, "bot_id": bot_id, "action": "noop_already",
            "current_p": current_p, "target_p": target_p,
            "reason": reason, "trigger": trigger,
        }
        _audit(rec)
        return rec

    if dry_run:
        rec = {
            "ts": now, "bot_id": bot_id, "action": "dry_run",
            "current_p": current_p, "target_p": target_p,
            "reason": reason, "trigger": trigger,
        }
        _audit(rec)
        return rec

    # Construct new params with only p changed
    try:
        # Create a new DefaultGridParams with all fields copied + p modified
        from dataclasses import replace
        new_params = replace(current, p=target_p)
        api.set_params(int(bot_id), new_params)
        # Update cache after successful write
        _state_cache[bot_id] = (target_p, time.monotonic())
        action = "paused" if not target_p else "resumed"
        rec = {
            "ts": now, "bot_id": bot_id, "action": action,
            "current_p": current_p, "target_p": target_p,
            "reason": reason, "trigger": trigger,
        }
        _audit(rec)
        logger.info("short_bots_guard.%s bot=%s reason=%s trigger=%s",
                    action, bot_id, reason, trigger)
        return rec
    except Exception as e:
        logger.exception("short_bots_guard.set_params_failed bot=%s", bot_id)
        rec = {
            "ts": now, "bot_id": bot_id, "action": "error",
            "target_p": target_p, "reason": reason, "trigger": trigger,
            "error": str(e),
        }
        _audit(rec)
        return rec


def pause_bot(bot_id: str, *, dry_run: bool = False, reason: str = "",
              trigger: str = "") -> dict:
    """Pause bot. Idempotent. Returns audit record."""
    return _set_p(bot_id, target_p=False, dry_run=dry_run, reason=reason, trigger=trigger)


def resume_bot(bot_id: str, *, dry_run: bool = False, reason: str = "",
               trigger: str = "") -> dict:
    """Resume bot. Idempotent."""
    return _set_p(bot_id, target_p=True, dry_run=dry_run, reason=reason, trigger=trigger)
