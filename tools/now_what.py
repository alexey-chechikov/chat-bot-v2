"""Что делать прямо сейчас: уровни по каждому живому боту и действие.

Оператор 10.09: «вижу — рынок делает это, нужно сделать это». Отчёты о
прошлом ему не нужны, статистику он смотрит в GinArea. Нужны УРОВНИ, на
которых надо шевелиться, и конкретное действие.

Всё, что печатается, — измеренные величины, не мнения:
  граница набора  — якорь ± 0.75 x ATR(14д); замерено на 11 ботах,
                    6 280 бот-часов: +$14 008 из $26 048 убытка, и
                    +$7 902 вне августовской катастрофы;
  порог риска     — пороги риск-контура в ЦЕНЕ, с учётом того, что
                    сетка добирает по дороге;
  безубыток       — средняя цена позиции;
  ближний таргет  — где закроется ближайший открытый ордер.

Запуск:  .venv/bin/python tools/now_what.py
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

K_BORDER = 0.75          # доля ATR до границы набора
MED_EMPTY = 0.1          # позиция ниже этой доли медианы = набор окончен


def _atr_and_price() -> tuple[float, float]:
    days: dict[str, list] = defaultdict(list)
    with (ROOT / "market_live" / "market_1h.csv").open(encoding="utf-8") as f:
        next(f)
        for ln in f:
            p = ln.split(",")
            if len(p) > 4:
                try:
                    days[p[0][:10]].append((float(p[1]), float(p[2]),
                                            float(p[3]), float(p[4])))
                except ValueError:
                    pass
    dk = sorted(days)
    bars = {k: {"high": max(x[1] for x in days[k]),
                "low": min(x[2] for x in days[k]),
                "close": days[k][-1][3]} for k in dk}
    trs = []
    for j in range(max(1, len(dk) - 14), len(dk)):
        b, pb = bars[dk[j]], bars[dk[j - 1]]
        trs.append(max(b["high"] - b["low"], abs(b["high"] - pb["close"]),
                       abs(b["low"] - pb["close"])))
    return (st.mean(trs) if trs else 0.0), bars[dk[-1]]["close"]


def _anchor(bot_id: str) -> tuple[float | None, str]:
    """Цена, при которой начался нынешний набор позиции."""
    snap = ROOT / "ginarea_live" / "snapshots.csv"
    if not snap.exists():
        return None, ""
    with snap.open(encoding="utf-8") as f:
        i = {n: k for k, n in enumerate(f.readline().strip().split(","))}
    seq = []
    with snap.open(encoding="utf-8") as f:
        next(f)
        for ln in f:
            p = ln.rstrip("\n").split(",")
            if len(p) <= max(i.values()):
                continue
            try:
                if str(int(float(p[i["bot_id"]]))) != bot_id:
                    continue
                seq.append((p[i["ts_utc"]], abs(float(p[i["position"]])),
                            float(p[i["average_price"]] or 0)))
            except (ValueError, IndexError):
                continue
    if len(seq) < 5:
        return None, ""
    med = st.median([q for _, q, _ in seq if q] or [1e-9])
    start = None
    for k, (ts, q, avg) in enumerate(seq):
        if q < med * MED_EMPTY:
            start = k
    if start is None or start + 1 >= len(seq):
        return None, ""
    nxt = seq[start + 1]
    return (nxt[2] or None), nxt[0][:16]


def main() -> int:
    from services.order_harvester.loop import _cached_api, okx_price

    api = _cached_api()
    if api is None:
        print("GinArea недоступна")
        return 1
    try:
        cfg = json.loads((ROOT / "state" / "risk_guard_config.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    dep = float(cfg.get("deposit_usd") or 0) or 1.0
    warn = dep * float(cfg.get("warn_pct", 5)) / 100
    kill = dep * float(cfg.get("kill_pct", 10)) / 100

    atr, px_now = _atr_and_price()
    print(f"BTC ${px_now:,.0f}   ATR(14д) ${atr:,.0f} "
          f"({atr / px_now * 100:.2f}%)   депозит ${dep:,.0f}")
    print(f"порог предупреждения ${warn:,.0f}, частичного закрытия "
          f"${kill:,.0f} — ПО КАЖДОМУ боту\n")

    total_pos = total_bag = 0.0
    for b in api.list_bots():
        if int(b.status) != 2:
            continue
        s = b.stat
        pos = float(getattr(s, "position", 0) or 0)
        if not pos:
            continue
        nm = (b.name or "")[:26]
        up = nm.upper()
        inst = ("BTC-USDT-SWAP" if up.startswith("BTC") or "COIN" in up
                else "ETH-USDT-SWAP" if up.startswith("ETH")
                else "XRP-USDT-SWAP" if up.startswith("XRP") else "")
        price = okx_price(inst) if inst else 0.0
        if not price:
            continue
        avg = float(getattr(s, "averagePrice", 0) or 0)
        inverse = "USDT" not in up
        pos_usd = pos if inverse else pos * price
        bag = (pos * (price / avg - 1) if inverse
               else pos * (price - avg)) if avg else 0.0
        total_pos += abs(pos_usd)
        total_bag += bag
        long = pos_usd > 0
        p = api.get_params(b.id)
        gs = float(p.gs or 0) / 100
        tog = float(p.gap.tog or 0) / 100

        print(f"=== {nm}  ({'ЛОНГ' if long else 'ШОРТ'}) ===")
        print(f"  позиция ${pos_usd:>9,.0f}   средняя ${avg:>10,.2f}   "
              f"мешок ${bag:>8,.2f}")

        # уровни
        lvl = []
        if avg:
            lvl.append(("безубыток", avg))
            lvl.append(("ближний таргет",
                        avg * (1 + tog) if long else avg * (1 - tog)))
            lvl.append(("следующий добор",
                        avg * (1 - gs) if long else avg * (1 + gs)))
            # цена, где мешок достигнет порогов (без учёта добора)
            for lbl, lim in (("предупреждение", warn),
                             ("частичное закрытие", kill)):
                if inverse:
                    lvl.append((lbl, avg * (1 - lim / pos_usd)))
                else:
                    lvl.append((lbl, avg - lim / pos))
        anch, when = _anchor(str(b.id))
        if anch and atr:
            border = anch - K_BORDER * atr if long else anch + K_BORDER * atr
            lvl.append((f"ГРАНИЦА НАБОРА (якорь ${anch:,.0f} от {when})",
                        border))
        for lbl, v in sorted(lvl, key=lambda t: -t[1]):
            if v <= 0:
                continue
            d = (v / price - 1) * 100
            here = " <-- ЦЕНА ЗДЕСЬ" if abs(d) < 0.15 else ""
            print(f"    ${v:>10,.0f} {d:>+6.1f}%  {lbl}{here}")

        # действие
        act = "набор разрешён, ничего не делать"
        if anch and atr:
            border = anch - K_BORDER * atr if long else anch + K_BORDER * atr
            if (long and price < border) or (not long and price > border):
                act = (f"ГРАНИЦА ПРОБИТА — заморозить набор: "
                       f"maxOp = числу открытых ордеров (сейчас {p.maxOp})")
        if abs(bag) >= kill and bag < 0:
            act = "мешок за порогом частичного закрытия — риск-контур режет сам"
        elif bag < 0 and abs(bag) >= warn:
            act = "мешок за порогом предупреждения — " + act
        print(f"  ДЕЙСТВИЕ: {act}\n")

    print(f"экспозиция ${total_pos:,.0f} = {total_pos / dep:.2f} плеча   "
          f"мешок ${total_bag:,.2f} = {total_bag / dep * 100:.1f}% депозита")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
