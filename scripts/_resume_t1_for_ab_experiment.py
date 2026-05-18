"""One-shot: manually resume T1 + clear T1 from auto_pause.json.

Reason: A/B experiment 2026-05-18 — T1 runs without cascade auto-pause,
TB with auto-pause, same other settings. Compare effectiveness.

After this script:
  - GinArea T1 (bot_id 4729923198) should transition PAUSED → ACTIVE
  - state/short_bots_auto_pause.json should not have T1 in 'paused' dict
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.short_bots_guard.control import _build_api

T1_ID = 4729923198
AUTO_PAUSE_PATH = Path("state/short_bots_auto_pause.json")


def main():
    api, err = _build_api()
    if api is None:
        print(f"FAILED to build API: {err}")
        return
    print(f"Resuming T1 (id={T1_ID}) via PUT /bots/{T1_ID}/start...")
    try:
        result = api.resume_bot(T1_ID)
        print(f"  API response: {result}")
    except Exception as e:
        print(f"  API call failed: {e}")
        return

    if AUTO_PAUSE_PATH.exists():
        data = json.loads(AUTO_PAUSE_PATH.read_text(encoding="utf-8"))
        paused = data.get("paused", {})
        removed = paused.pop(str(T1_ID), None)
        if removed:
            print(f"  Removed T1 from auto_pause.paused: {removed}")
            data["paused"] = paused
            AUTO_PAUSE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
        else:
            print(f"  T1 was not in auto_pause.paused (already clean)")

    print("Done.")


if __name__ == "__main__":
    main()
