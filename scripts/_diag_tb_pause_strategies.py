"""Diagnostic: test pause/resume strategies on TB (testbed) bot.

GOAL: find the SAFE pause/resume sequence that doesn't end in FAILED status.

Strategies tested:
  S1 — `set_params(p=false)` / `set_params(p=true)`     # what we did on T1
  S2 — pre-set `in.restart=true` then `p=false` / `p=true`
  S3 — pause normal / resume with `in.otcPassed=true` forced

Between each strategy: wait + status check. Print full state transitions.

Bot: TB testbed (id 4525648417), small deposit ~$100, low risk.

Usage:
    python scripts/_diag_tb_pause_strategies.py
    python scripts/_diag_tb_pause_strategies.py --strategy 1   # just S1
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

TB_BOT_ID = 4525648417


def _check(api, label: str) -> dict:
    """Print + return current state of TB."""
    bot = api.get_bot(TB_BOT_ID)
    params = api.get_params(TB_BOT_ID)
    in_block = params.extra_raw.get("in") or {}
    state = {
        "label": label,
        "status_code": int(bot.status),
        "status_name": bot.status.name,
        "p": params.p,
        "otc": in_block.get("otc"),
        "otcPassed": in_block.get("otcPassed"),
        "restart": in_block.get("restart"),
    }
    print(f"  [{label:18}] status={state['status_name']:10} ({state['status_code']:2})  "
          f"p={state['p']}  otc={state['otc']}  otcPassed={state['otcPassed']}  "
          f"restart={state['restart']}")
    return state


def _wait(seconds: float) -> None:
    print(f"  ⏳ waiting {seconds}s...")
    time.sleep(seconds)


def strategy_1(api, *, wait_post_pause: float = 15.0, wait_post_resume: float = 15.0) -> None:
    """S1: plain set_params(p=false) / set_params(p=true). The approach
    that put T1 in FAILED."""
    print("\n=== S1: plain p-toggle ===")
    _check(api, "BEFORE")
    print("  → set_params(p=false)")
    cur = api.get_params(TB_BOT_ID)
    api.set_params(TB_BOT_ID, replace(cur, p=False))
    _wait(wait_post_pause)
    _check(api, "AFTER_PAUSE")
    print("  → set_params(p=true)")
    cur = api.get_params(TB_BOT_ID)
    api.set_params(TB_BOT_ID, replace(cur, p=True))
    _wait(wait_post_resume)
    _check(api, "AFTER_RESUME")


def strategy_2(api, *, wait_post_pause: float = 15.0, wait_post_resume: float = 15.0) -> None:
    """S2: set in.restart=true before pause, so bot auto-recovers on resume."""
    print("\n=== S2: pause with in.restart=true pre-set ===")
    _check(api, "BEFORE")
    cur = api.get_params(TB_BOT_ID)
    in_with_restart = dict(cur.extra_raw.get("in") or {})
    in_with_restart["restart"] = True
    new_extra = {**cur.extra_raw, "in": in_with_restart}
    print("  → set_params(p=false, in.restart=True)")
    api.set_params(TB_BOT_ID, replace(cur, p=False, extra_raw=new_extra))
    _wait(wait_post_pause)
    _check(api, "AFTER_PAUSE")
    print("  → set_params(p=true)  [restart=true should auto-recover]")
    cur = api.get_params(TB_BOT_ID)
    api.set_params(TB_BOT_ID, replace(cur, p=True))
    _wait(wait_post_resume)
    _check(api, "AFTER_RESUME")
    # Restore in.restart=false to original state
    print("  → restore in.restart=False")
    cur = api.get_params(TB_BOT_ID)
    in_restored = dict(cur.extra_raw.get("in") or {})
    in_restored["restart"] = False
    api.set_params(TB_BOT_ID, replace(cur, extra_raw={**cur.extra_raw, "in": in_restored}))
    _wait(5.0)
    _check(api, "AFTER_RESTORE")


def strategy_3(api, *, wait_post_pause: float = 15.0, wait_post_resume: float = 15.0) -> None:
    """S3: pause normal; resume by forcing in.otcPassed=true."""
    print("\n=== S3: resume with in.otcPassed=true forced ===")
    _check(api, "BEFORE")
    print("  → set_params(p=false)")
    cur = api.get_params(TB_BOT_ID)
    api.set_params(TB_BOT_ID, replace(cur, p=False))
    _wait(wait_post_pause)
    _check(api, "AFTER_PAUSE")
    print("  → set_params(p=true, in.otcPassed=true)")
    cur = api.get_params(TB_BOT_ID)
    in_with_passed = dict(cur.extra_raw.get("in") or {})
    in_with_passed["otcPassed"] = True
    new_extra = {**cur.extra_raw, "in": in_with_passed}
    api.set_params(TB_BOT_ID, replace(cur, p=True, extra_raw=new_extra))
    _wait(wait_post_resume)
    _check(api, "AFTER_RESUME")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", type=int, choices=[1, 2, 3], default=None,
                    help="run only one strategy (default: all 3)")
    ap.add_argument("--wait", type=float, default=15.0,
                    help="seconds to wait between operations (default 15)")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(ROOT))
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        print(f"API init failed: {err}")
        return

    print("=" * 70)
    print("TB pause/resume strategy diagnostic")
    print(f"Bot: {TB_BOT_ID} (testbed)")
    print(f"Wait between ops: {args.wait}s")
    print("=" * 70)
    _check(api, "INITIAL")

    if args.strategy in (None, 1):
        strategy_1(api, wait_post_pause=args.wait, wait_post_resume=args.wait)
    if args.strategy in (None, 2):
        strategy_2(api, wait_post_pause=args.wait, wait_post_resume=args.wait)
    if args.strategy in (None, 3):
        strategy_3(api, wait_post_pause=args.wait, wait_post_resume=args.wait)

    print("\n" + "=" * 70)
    print("FINAL STATE:")
    _check(api, "FINAL")
    print("=" * 70)


if __name__ == "__main__":
    main()
