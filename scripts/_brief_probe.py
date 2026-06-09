"""Диагностика: что tracker_reader отдаёт ассемблеру (активные/прочие/пыль)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.morning_brief import tracker_reader as tr
from services.morning_brief.card import _bag, _day_delta, _load_managed, DUST_USD

snap = tr.read_snapshots()
managed_ids = {m["bot_id"] for m in _load_managed()}
print(f"stale_min={snap['stale_min']:.1f}  ботов в хвосте: {len(snap['bots'])}")
for bid, slot in snap["bots"].items():
    latest = slot["latest"]
    if latest["status"] != tr.STATUS_ACTIVE or bid in managed_ids:
        continue
    bag = _bag(latest)
    realized, net = _day_delta(slot)
    dust = (not latest.get("position")
            and abs(latest.get("profit") or 0) < DUST_USD
            and abs(bag or 0) < DUST_USD
            and abs(net or 0) < DUST_USD)
    print(f"{bid} {latest['bot_name']!r:34} pos={latest['position']!r} "
          f"profit={latest['profit']!r} cur={latest['current_profit']!r} "
          f"bag={bag!r} net={net!r} day0={'есть' if slot['day0'] else 'НЕТ'} dust={dust}")
