"""Manual unfreeze of an auto_executor setup (operator request 2026-05-29).

Removes the per-setup killswitch freeze, stamps unfrozen_at (so the same losing
streak won't re-freeze it), resets consecutive-loss counter and any expired
global freeze. Run, then restart app_runner so the live loop reloads state.
"""
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.auto_executor.state import load_state, save_state  # noqa: E402

SETUP = sys.argv[1] if len(sys.argv) > 1 else "long_pdl_bounce"
now = datetime.now(timezone.utc).isoformat(timespec="seconds")

st = load_state()
k = st.kill
was_frozen = SETUP in k.setup_frozen
k.setup_frozen.pop(SETUP, None)
k.unfrozen_at[SETUP] = now
k.consecutive_losses = 0
# clear an expired/active global freeze too (operator wants it trading)
k.freeze_until = None
save_state(st)

print(f"unfroze setup={SETUP} was_frozen={was_frozen} unfrozen_at={now}")
print(f"  setup_frozen now: {dict(k.setup_frozen)}")
print(f"  consecutive_losses reset: {k.consecutive_losses}")
print(f"  global freeze_until cleared: {k.freeze_until}")
