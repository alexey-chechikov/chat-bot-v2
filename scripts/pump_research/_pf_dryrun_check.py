"""pump_freeze v2 — SAFE dry-run verification.

Builds the GinArea API client and does READ-ONLY calls only:
  - _build_api()      — credentials load + auth
  - api.list_bots()   — what bots exist live, and their state
  - confirms api.pause_bot / api.resume_bot are wired (does NOT call them)

No live bot is touched — pause_bot/resume_bot are NOT invoked.
"""
import os
import sys

ROOT = "/Users/alexeychechikov/code/bot7"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from services.short_bots_guard.control import _build_api  # noqa: E402

TB_ID = 4525648417  # testbed bot per managed_bots.json (may be stale)

api, err = _build_api()
if api is None:
    print(f"FAIL: _build_api -> {err}")
    sys.exit(1)
print("OK: GinArea API client built (auth + credentials loaded)")

for m in ("pause_bot", "resume_bot"):
    fn = getattr(api, m, None)
    print(f"  method {m}: {'callable -> ' + (fn.__doc__ or '').splitlines()[0] if callable(fn) else 'MISSING'}")

try:
    bots = api.list_bots()
except Exception as e:  # noqa: BLE001
    print(f"FAIL: list_bots -> {e!r}")
    sys.exit(1)

print(f"OK: list_bots -> {len(bots)} live bots")
tb_found = False
for b in bots:
    bid = getattr(b, "id", getattr(b, "bot_id", None))
    status = getattr(b, "status", getattr(b, "state", "?"))
    name = getattr(b, "name", getattr(b, "alias", getattr(b, "title", "")))
    mark = ""
    if bid is not None and int(bid) == TB_ID:
        tb_found = True
        mark = "  <-- TB testbed"
    print(f"  id={bid}  status={status}  name={name}{mark}")

print()
print(f"TB ({TB_ID}) present in live list: {tb_found}")
print("DRY-RUN OK — no pause/resume fired. Real round-trip awaits operator OK.")
