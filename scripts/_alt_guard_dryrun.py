"""Один tick Alt-Guard на живых данных, без TG (send_fn=None)."""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from services.alt_guard.loop import tick

alerts = tick(send_fn=None)
print(f"\nпингов: {len(alerts)}")
for a in alerts:
    print("—", a)
