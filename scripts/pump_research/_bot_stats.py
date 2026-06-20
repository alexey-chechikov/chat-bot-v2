"""Read-only snapshot of all live GinArea bots + per-bot stats.
For the pump_freeze v2 scope decision and the new-bots performance review.
No bot is modified."""
import os
import sys

ROOT = "/Users/alexeychechikov/code/bot7"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from services.short_bots_guard.control import _build_api  # noqa: E402

api, err = _build_api()
if api is None:
    print(f"FAIL: _build_api -> {err}")
    sys.exit(1)

bots = api.list_bots()
print(f"{len(bots)} live bots\n")

for b in bots:
    bid = getattr(b, "id", getattr(b, "bot_id", None))
    name = getattr(b, "name", getattr(b, "alias", getattr(b, "title", "")))
    status = getattr(b, "status", getattr(b, "state", "?"))
    print(f"--- id={bid}  status={status}  {name}")
    # bot object fields
    bd = getattr(b, "__dict__", None)
    if bd:
        for k, v in bd.items():
            if k in ("id", "name", "status", "title", "alias"):
                continue
            print(f"      {k}: {v}")
    # stats
    try:
        st = api.get_stat(int(bid))
        sd = getattr(st, "__dict__", None)
        if sd:
            for k, v in sd.items():
                print(f"   stat.{k}: {v}")
        else:
            print(f"   stat: {st}")
    except Exception as e:  # noqa: BLE001
        print(f"   stat: ERROR {e!r}")
    print()
