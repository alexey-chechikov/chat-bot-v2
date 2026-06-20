"""Verify pump_freeze config after the v2 scope update — import-checks the
loop and prints the live APPLIES_TO_BOTS scope."""
import os
import sys

ROOT = "/Users/alexeychechikov/code/bot7"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from services.pump_freeze.config import APPLIES_TO_BOTS, PUMP_THRESHOLD_PCT  # noqa: E402
from services.pump_freeze import loop  # noqa: E402,F401  import check

print(f"pump_freeze.loop import: OK")
print(f"PUMP_THRESHOLD_PCT: {PUMP_THRESHOLD_PCT}")
print(f"APPLIES_TO_BOTS ({len(APPLIES_TO_BOTS)} bots):")
for bid, side in APPLIES_TO_BOTS.items():
    print(f"  {bid} -> {side}")
