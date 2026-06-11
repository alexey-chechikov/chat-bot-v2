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

BAND = 0.3  # price-gate %, валидировано Win grid-$


def _ema(xs: list[float], n: int) -> list[float]:
    a = 2.0 / (n + 1)
    e = xs[0]
    out = [e]
    for x in xs[1:]:
        e = x * a + e * (1 - a)
        out.append(e)
    return out


def regime() -> dict:
    from market_collector.ohlcv import _fetch_klines
    raw = _fetch_klines("240", 250)  # 4h, descending [ts,o,h,l,c,v,...]
    c = [float(x[4]) for x in raw][::-1]
    h = [float(x[2]) for x in raw][::-1]
    lo = [float(x[3]) for x in raw][::-1]
    e1 = _ema(c, 200); e2 = _ema(e1, 200); e3 = _ema(e2, 200)
    t200 = 3 * e1[-1] - 3 * e2[-1] + e3[-1]
    px = c[-1]
    above = (px - t200) / t200 * 100.0
    zone = "LONG-зона" if above > BAND else "SHORT-зона" if above < -BAND else "FLAT (у красной)"
    tr = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) / c[i] * 100.0
          for i in range(1, len(c))]
    atr = [tr[0]]
    for x in tr[1:]:
        atr.append((atr[-1] * 13 + x) / 14)
    win = atr[-100:]
    mean = sum(win) / len(win)
    sd = (sum((x - mean) ** 2 for x in win) / len(win)) ** 0.5
    z = (atr[-1] - mean) / sd if sd else 0.0
    return dict(px=px, t200=t200, above=above, zone=zone, atr=atr[-1], z=z, voloff=z >= 2.5)


def verdict(side: str, zone: str, voloff: bool) -> str:
    if voloff:
        return "⚫ VOL-OFF спайк — оцени: краш? фикс профит / хедж"
    if "FLAT" in zone:
        return "🟡 FLAT — обе ноги доят чоп, держать"
    fav = (side == "short" and "SHORT" in zone) or (side == "long" and "LONG" in zone)
    return "🟢 в зоне — держать/доить" if fav else "🔴 ПРОТИВ режима — присмотреть / брать профит (будет бажить)"


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
    bot, top = border
    if not bot or not top:
        return ""
    pos = (px - bot) / (top - bot)  # 0=у дна, 1=у верха
    if side == "short" and pos > 0.8:
        return " ⚠️у TOP (мешок к максимуму)"
    if side == "long" and pos < 0.2:
        return " ⚠️у BOTTOM (мешок к максимуму)"
    return f" (в border {pos*100:.0f}%)"


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
