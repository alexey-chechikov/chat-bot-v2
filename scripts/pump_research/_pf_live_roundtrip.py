"""pump_freeze v2 — LIVE pause/resume round-trip on TB testbed.

Operator-approved 2026-05-22: resume -> pause, so TB ends where it started.
Verifies the real GinArea endpoints PUT /bots/{id}/start and /stop work
end-to-end (the one thing the mocked unit tests cannot cover).

Touches ONLY TB (4525648417, testbed). No other bot.
"""
import os
import sys
import time

ROOT = "/Users/alexeychechikov/code/bot7"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from services.short_bots_guard.control import _build_api  # noqa: E402

TB_ID = 4525648417


def tb_status(api):
    b = api.get_bot(TB_ID)
    return getattr(b, "status", getattr(b, "state", None))


def poll(api, want_change_from=None, want_equal=None, label=""):
    for i in range(7):
        time.sleep(2)
        s = tb_status(api)
        print(f"   +{(i + 1) * 2}s  status={s}")
        if want_change_from is not None and s != want_change_from:
            return s
        if want_equal is not None and s == want_equal:
            return s
    return tb_status(api)


api, err = _build_api()
if api is None:
    print(f"FAIL: _build_api -> {err}")
    sys.exit(1)
print("OK: API client built")

s0 = tb_status(api)
print(f"TB status BEFORE: {s0}")

print("\n-> resume_bot(TB)  [PUT /bots/{id}/start]")
resp = api.resume_bot(TB_ID)
print(f"   response: {resp}")
s_after_resume = poll(api, want_change_from=s0)
print(f"   TB status after resume: {s_after_resume}")

print("\n-> pause_bot(TB)  [PUT /bots/{id}/stop]")
resp = api.pause_bot(TB_ID)
print(f"   response: {resp}")
s_final = poll(api, want_equal=s0)
print(f"   TB status after pause: {s_final}")

print(f"\nTB BEFORE={s0}  AFTER={s_final}")
if s_final == s0:
    print("ROUND-TRIP OK — endpoints work, TB returned to original state.")
else:
    print(f"NOTE: TB ended at {s_final}, started at {s0} — check manually.")
