"""Живой проход: фетч 600 баров, детект, дозаполнение — без ошибок?"""
import sys
from pathlib import Path
sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.ma_cross_shadow.tracker import _fetch_4h, detect, fill_outcomes, BARS

for sym in ("BTCUSDT", "SOLUSDT", "XRPUSDT"):
    rows = _fetch_4h(sym)
    print(f"{sym}: запрошено {BARS}, получено {len(rows) if rows else 0} баров")

fired = detect()
print(f"\nновых сигналов: {len(fired)}")
for f in fired:
    print(" ", f["symbol"], f["dir"], "H5✅" if f["passed_h5"] else f"skip {f['skip_reasons']}")
print("outcomes filled:", fill_outcomes())
