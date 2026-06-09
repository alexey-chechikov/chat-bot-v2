#!/usr/bin/env python3
"""Утренний брифинг грид-портфеля: BTC 4h режим + боты + вердикт держать/закрыть/открыть.

РЕЖИМ: live Bybit 4h klines (public, без кредов) → price vs TEMA200 (price-gate) + vol-z.
БОТЫ: managed-список + регим-выравнивание. С `--live` дотягивает профит/мешок/border через
GinArea API (профит, position=мешок, border, ликвидация).

⚠️ GinArea = ОДНА машина одновременно. `--live` запускай ТОЛЬКО если на этой машине НЕ крутится
ginarea_tracker (иначе собьёшь продовую сессию). Без флага — безопасно (только публичные свечи).

Запуск: /Users/alexeychechikov/code/bot7/.venv/bin/python3 scripts/morning_briefing.py [--live]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))

# Источник истины режима/вердиктов — services/morning_brief/regime.py
# (общий с утренней TG-карточкой scripts/morning_card.py).
from services.morning_brief.regime import regime, verdict, border_flag as _border_flag  # noqa: E402


def collect_bots(live: bool) -> list[dict]:
    managed = json.loads((ROOT / "state" / "short_bots_managed.json").read_text(encoding="utf-8"))["managed_bots"]
    api = None
    if live:
        try:
            from services.ginarea_api.auth import GinAreaAuth
            from services.ginarea_api.client import GinAreaClient
            from services.ginarea_api.bots import BotsAPI
            api = BotsAPI(GinAreaClient(auth=GinAreaAuth.from_env()))
        except Exception as e:
            print(f"  ⚠️ live API недоступна: {e}\n")
    rows = []
    for m in managed:
        if m.get("testbed"):
            continue
        row = dict(alias=m["alias"], side=m["side"], bot_id=m["bot_id"])
        if api:
            try:
                st = api.get_stat(int(m["bot_id"]))
                pr = api.get_params(int(m["bot_id"]))
                row.update(profit=st.profit, position=st.position, avg=st.averagePrice,
                           liq=st.liquidationPrice,
                           border=(pr.border.bottom, pr.border.top))
            except Exception as e:
                row["err"] = str(e)[:70]
        rows.append(row)
    return rows


def border_flag(side: str, px: float, border: tuple) -> str:
    return _border_flag(side, px, border)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="дотянуть профит/мешок/border через GinArea API")
    args = ap.parse_args()

    r = regime()
    print("☀️  УТРЕННИЙ БРИФИНГ — BTC грид-портфель\n")
    print(f"BTC 4h: {r['px']:,.0f}  ·  {r['above']:+.2f}% от красной  ·  {r['zone']}"
          f"  ·  vol-z {r['z']:.1f}{'  ⚠️VOL-OFF' if r['voloff'] else ''}")
    print(f"красная (TEMA200 4h): {r['t200']:,.0f}  ·  ATR {r['atr']:.2f}%\n")

    print("Боты:")
    for b in collect_bots(args.live):
        v = verdict(b["side"], r["zone"], r["voloff"])
        print(f"  {b['alias']:20s} [{b['side']:5s}] {v}")
        if "profit" in b:
            bf = border_flag(b["side"], r["px"], b.get("border", (None, None)))
            print(f"      профит ${b['profit']:,.0f}  ·  поз {b['position']:+.4f} BTC{bf}")
        elif "err" in b:
            print(f"      (live err: {b['err']})")

    print("\nЛогика открыть/закрыть:")
    print("  ШОРТ доит в SHORT-зоне (под красной) / бажит над красной. ЛОНГ — наоборот.")
    print("  Против режима + близко к TOP border → брать профит ДО упора (не ждать макс-мешка).")
    print("  Мешок снят + ты в плюсе → можно закрыть, переставить border за ценой.")
    print("  VOL-OFF спайк → оцени краш руками (авто-рез обе = net−, не делаем).")


if __name__ == "__main__":
    main()
