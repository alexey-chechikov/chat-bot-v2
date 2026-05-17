"""Bot Brain — executor.

Reads latest snapshot, evaluates rules, dispatches actions per risk-tier policy:

  Production bots (5 managed, testbed=False):
    - Safe actions (pause/resume): auto-execute LIVE
    - Risky actions (resize/close_flat/fix_partial/tighten_grid):
      DRY-RUN only (journal proposal, no live API call)

  Testbed bot (tier="TB", testbed=True):
    - All actions auto-execute LIVE

Outputs:
  - state/bot_brain_proposals.jsonl — every proposal (whether executed or not)
  - state/bot_brain_actions.jsonl   — actions.dispatch audit (live + dry-run)
  - TG MARGIN_ALERT card per live action (only when status != noop/error)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = ROOT / "state" / "bot_brain_state.jsonl"
PROPOSALS_PATH = ROOT / "state" / "bot_brain_proposals.jsonl"

DEFAULT_INTERVAL_SEC = 60


def _tail_snapshot() -> Optional[dict]:
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        with SNAPSHOT_PATH.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 32 * 1024)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except (OSError, json.JSONDecodeError):
        logger.exception("bot_brain.executor.snapshot_read_failed")
        return None


def _append_proposal(proposal_dict: dict) -> None:
    try:
        PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROPOSALS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(proposal_dict, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("bot_brain.executor.append_proposal_failed")


def _decide_mode(action: str, bot_testbed: bool) -> str:
    """Risk-tier policy: which proposals run LIVE vs DRY-RUN."""
    from services.bot_brain.actions import SAFE_PRODUCTION_ACTIONS
    if bot_testbed:
        return "live"  # testbed: full auto
    if action in SAFE_PRODUCTION_ACTIONS:
        return "live"  # pause/resume on prod = LIVE
    return "dry_run"   # resize/etc on prod = dry-run only


# Per-proposal dedup: bot_id+action+rule_id within N seconds shouldn't refire
_DEDUP_WINDOW_SEC = 300
_dedup: dict[tuple, datetime] = {}


def _is_duplicate(p) -> bool:
    key = (p.bot_id, p.action, p.rule_id)
    now = datetime.now(timezone.utc)
    last = _dedup.get(key)
    if last and (now - last).total_seconds() < _DEDUP_WINDOW_SEC:
        return True
    _dedup[key] = now
    return False


def process_proposals(snapshot: dict, *, send_fn: Optional[Callable] = None) -> int:
    """Evaluate rules → dispatch + journal. Returns count of proposals processed."""
    from services.bot_brain.rules import evaluate_all
    from services.bot_brain import actions

    proposals = evaluate_all(snapshot)
    if not proposals:
        return 0

    # Map bot_id → testbed flag for quick lookup
    testbed_map = {b["bot_id"]: bool(b.get("testbed")) for b in snapshot.get("bots", [])}
    tier_map = {b["bot_id"]: b.get("tier") for b in snapshot.get("bots", [])}

    processed = 0
    for p in proposals:
        if _is_duplicate(p):
            continue
        is_testbed = testbed_map.get(p.bot_id, False)
        # testbed_only rules skip prod bots entirely
        if p.testbed_only and not is_testbed:
            _append_proposal({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "rule_id": p.rule_id, "bot_id": p.bot_id, "tier": p.tier,
                "action": p.action, "params": p.params,
                "reason": p.reason, "confidence": p.confidence,
                "mode": "skip_testbed_only_on_prod",
            })
            continue

        mode = _decide_mode(p.action, is_testbed)
        result = actions.dispatch(
            p.action, p.bot_id, params=p.params,
            mode=mode, reason=p.reason, rule_id=p.rule_id,
        )

        proposal_record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rule_id": p.rule_id, "bot_id": p.bot_id, "tier": p.tier,
            "action": p.action, "params": p.params,
            "reason": p.reason, "confidence": p.confidence,
            "mode": mode,
            "result_status": result.get("status"),
        }
        _append_proposal(proposal_record)
        processed += 1

        # TG card — only for LIVE actions (dry-run is silent in TG, journal only)
        if mode == "live" and send_fn is not None and result.get("status") == "live":
            badge = "🤖 BOT BRAIN"
            text = (
                f"{badge}  [{p.tier}] {p.action.upper()}\n"
                f"  rule: {p.rule_id}\n"
                f"  reason: {p.reason}\n"
                f"  result: {result.get('status')}"
            )
            try:
                send_fn(text)
            except Exception:
                logger.exception("bot_brain.executor.tg_send_failed")

    return processed


async def run_loop(stop_event: asyncio.Event, *, telegram_app=None,
                   interval_sec: int = DEFAULT_INTERVAL_SEC) -> None:
    """Async loop — every interval read snapshot, evaluate rules, dispatch."""
    from services.telegram.channel_router import build_send_fn
    send_fn = build_send_fn(telegram_app, "MARGIN_ALERT") if telegram_app else None
    logger.info("bot_brain.executor.start interval=%ds send_fn=%s",
                interval_sec, "wired" if send_fn else "off")

    while not stop_event.is_set():
        try:
            snap = _tail_snapshot()
            if snap is None:
                logger.warning("bot_brain.executor.no_snapshot — perception loop not ready?")
            else:
                n = process_proposals(snap, send_fn=send_fn)
                if n:
                    logger.info("bot_brain.executor.processed n=%d", n)
        except Exception:
            logger.exception("bot_brain.executor.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("bot_brain.executor.stopped")
