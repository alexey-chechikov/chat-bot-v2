"""Отдельный разбор BTC SHORT 5189290547 — динамика, настройки, рынок, вердикт.

Оператор 2026-08-19: «хочу отдельно анализировать шорт-бота — смотреть
динамику, настройки, изменение рынка, рекомендации».

Почему ему нужен свой инструмент, а не строка в grid_health:
  * он один инверсный (монетная маржа): позиция в долларовых контрактах,
    мешок и профит в BTC — общие формулы к нему неприменимы;
  * он один направленный (side=2 SHORT), поэтому рост BTC для него не
    «просто рынок», а прямое давление на позицию;
  * он один с in-условием и разовой проверкой;
  * у него самая большая занятая ёмкость и единственный трёхзначный мешок.

ТОЛЬКО КОМАНДНАЯ СТРОКА. Оператор 2026-08-19: «в телеграм мне такой
монитор не нужен». В TG его не заводить — ни регулярной карточкой, ни по
событию. Здесь намеренно нет ни send_fn, ни импортов телеграма.

Запуск:
    .venv/bin/python tools/short_watch.py
    .venv/bin/python tools/short_watch.py --days 14
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT = "5189290547"
SNAP = ROOT / "ginarea_live" / "snapshots.csv"
AUTOTUNE = ROOT / "state" / "grid_autotune_journal.jsonl"
HARVEST = ROOT / "state" / "order_harvester_journal.jsonl"
BTC_1M = ROOT / "market_live" / "market_1m.csv"

ROUND_TRIP_FEE_PCT = 0.070      # замер по 846 ордерам
SMA_DAYS = 20
TREND_DAYS = 5                  # порог затяжного движения


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def read_history(days: int) -> list[dict]:
    """Снимки бота за N суток. Колонки берём по ИМЕНАМ, не по позиции."""
    if not SNAP.exists():
        return []
    with SNAP.open(encoding="utf-8") as f:
        hdr = f.readline().strip().split(",")
    idx = {n: k for k, n in enumerate(hdr)}
    need = ("ts_utc", "bot_id", "status", "position", "profit",
            "current_profit", "average_price", "trade_volume",
            "in_filled_count", "out_filled_count")
    if any(n not in idx for n in need):
        return []
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    with SNAP.open(encoding="utf-8") as f:
        next(f)
        for ln in f:
            p = ln.rstrip("\n").split(",")
            if len(p) <= max(idx[n] for n in need):
                continue
            try:
                if str(int(_f(p[idx["bot_id"]]))) != BOT:
                    continue
            except ValueError:
                continue
            ts = p[idx["ts_utc"]]
            if ts < cut:
                continue
            out.append({
                "ts": ts, "day": ts[:10],
                "status": int(_f(p[idx["status"]])),
                "position": _f(p[idx["position"]]),
                "profit": _f(p[idx["profit"]]),
                "current_profit": _f(p[idx["current_profit"]]),
                "avg": _f(p[idx["average_price"]]),
                "volume": _f(p[idx["trade_volume"]]),
                "in_n": _f(p[idx["in_filled_count"]]),
                "out_n": _f(p[idx["out_filled_count"]]),
            })
    out.sort(key=lambda r: r["ts"])
    return out


def btc_context() -> dict:
    """Цена, SMA20д и сколько суток подряд цена держится выше/ниже."""
    if not BTC_1M.exists():
        return {}
    closes: list[tuple[str, float]] = []
    with BTC_1M.open(encoding="utf-8") as f:
        next(f)
        for ln in f:
            p = ln.split(",")
            if len(p) < 5:
                continue
            try:
                closes.append((p[0], float(p[4])))
            except ValueError:
                continue
    if len(closes) < SMA_DAYS * 1440:
        return {}
    # почасовые точки
    hourly: list[float] = []
    seen = set()
    for ts, c in closes:
        k = ts[:13]
        if k not in seen:
            seen.add(k)
            hourly.append(c)
    win = SMA_DAYS * 24
    if len(hourly) < win + TREND_DAYS * 24:
        return {}
    sma = sum(hourly[-win:]) / win
    px = hourly[-1]
    up = dn = 0
    for i in range(len(hourly) - 1, win, -1):
        s = sum(hourly[i - win:i]) / win
        if hourly[i] > s:
            if dn:
                break
            up += 1
        else:
            if up:
                break
            dn += 1
    return {"px": px, "sma": sma, "dev_pct": (px - sma) / sma * 100,
            "up_h": up, "dn_h": dn}


def setting_changes(days: int) -> list[dict]:
    out = []
    if not AUTOTUNE.exists():
        return out
    cut = datetime.now(timezone.utc) - timedelta(days=days)
    for ln in AUTOTUNE.read_text(encoding="utf-8",
                                 errors="replace").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if str(r.get("bot_id")) != BOT:
            continue
        try:
            t = datetime.fromisoformat(str(r.get("ts")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if t >= cut:
            out.append({**r, "_t": t})
    return out


def harvests(days: int) -> tuple[int, float]:
    if not HARVEST.exists():
        return 0, 0.0
    cut = datetime.now(timezone.utc) - timedelta(days=days)
    n, usd = 0, 0.0
    for ln in HARVEST.read_text(encoding="utf-8",
                                errors="replace").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("event") != "ORDER_CLOSED" or str(r.get("bot_id")) != BOT:
            continue
        try:
            t = datetime.fromisoformat(str(r.get("ts")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if t >= cut:
            n += 1
            usd += _f(r.get("profit_usd"))
    return n, usd


def report(days: int = 7) -> None:
    hist = read_history(days)
    if not hist:
        print("нет снимков по боту — проверь ginarea_live/snapshots.csv")
        return
    now = hist[-1]
    mkt = btc_context()

    # ── сейчас ────────────────────────────────────────────────────────
    px = mkt.get("px") or 0.0
    pos_usd = abs(now["position"])          # инверс: позиция уже в долларах
    bag_btc = now["current_profit"] - now["profit"]
    bag_usd = bag_btc * px
    avg = now["avg"]
    print("═" * 66)
    print("BTC SHORT 5189290547 — инверсный, монетная маржа (BTC-USD-SWAP)")
    print("═" * 66)
    print(f"позиция          ${pos_usd:>12,.0f}   (контрактов {pos_usd:,.0f})")
    print(f"средний вход      {avg:>12,.1f}")
    if px:
        print(f"цена BTC          {px:>12,.1f}")
    if avg and px:
        # шорт: в плюсе, пока цена НИЖЕ средней
        room = (avg - px) / px * 100
        word = "в плюсе" if room > 0 else "под водой"
        print(f"до безубытка      {room:>11.2f}%   ({word})")
    print(f"мешок            ${bag_usd:>12,.2f}   ({bag_btc:+.6f} BTC)")
    print(f"реализовано      {now['profit']:>13.6f} BTC "
          f"= ${now['profit'] * px:,.2f}" if px else "")

    # ── динамика по дням ──────────────────────────────────────────────
    byday: dict[str, list[dict]] = defaultdict(list)
    for r in hist:
        byday[r["day"]].append(r)
    print(f"\nДИНАМИКА ПО ДНЯМ (последние {days})")
    print(f"{'день':11s} {'поза$':>9s} {'мешок$':>9s} {'оборот$':>9s} "
          f"{'заработок$':>11s} {'IN':>5s} {'OUT':>5s}")
    prev_prof = prev_vol = None
    for day in sorted(byday):
        rows = byday[day]
        a, b = rows[0], rows[-1]
        vol_d = b["volume"] - a["volume"]
        prof_d = (b["profit"] - a["profit"]) * px
        bag_d = (b["current_profit"] - b["profit"]) * px
        in_d = b["in_n"] - a["in_n"]
        out_d = b["out_n"] - a["out_n"]
        print(f"{day:11s} {abs(b['position']):9,.0f} {bag_d:9,.2f} "
              f"{vol_d:9,.0f} {prof_d:11,.2f} {in_d:5.0f} {out_d:5.0f}")
        prev_prof, prev_vol = b["profit"], b["volume"]

    # ── рынок ─────────────────────────────────────────────────────────
    if mkt:
        print(f"\nРЫНОК: BTC {mkt['px']:,.0f}, SMA20д {mkt['sma']:,.0f}, "
              f"отклонение {mkt['dev_pct']:+.2f}%")
        if mkt["up_h"]:
            print(f"  выше SMA20д {mkt['up_h']/24:.1f} суток подряд "
                  f"(порог затяжного движения {TREND_DAYS})")
        else:
            print(f"  ниже SMA20д {mkt['dn_h']/24:.1f} суток подряд")

    # ── настройки ─────────────────────────────────────────────────────
    ch = setting_changes(days)
    print(f"\nИЗМЕНЕНИЯ НАСТРОЕК за {days} дн: "
          f"{len(ch) if ch else 'не было'}")
    for c in ch:
        if c.get("event") == "APPLIED":
            print(f"  {c['_t']:%d.%m %H:%M} расширение: "
                  f"шаг {c.get('orig', {}).get('gs')} → {c.get('gs')}, "
                  f"таргет {c.get('orig', {}).get('tog')} → {c.get('tog')} "
                  f"[{c.get('trigger')}]")
        elif c.get("event") == "RESTORED":
            print(f"  {c['_t']:%d.%m %H:%M} откат: "
                  f"шаг → {c.get('to', {}).get('gs')}")

    hn, husd = harvests(days)
    print(f"ХАРВЕСТЕР за {days} дн: {hn} ордеров на ${husd:,.2f}")

    # ── вердикт ───────────────────────────────────────────────────────
    print("\nВЕРДИКТ")
    flags = []
    if avg and px and px > avg:
        flags.append(f"позиция под водой на {(px-avg)/px*100:.2f}%")
    if mkt and mkt.get("up_h", 0) >= TREND_DAYS * 24:
        flags.append(f"BTC выше SMA20д {mkt['up_h']/24:.1f} суток — "
                     "затяжной рост против шорта")
    elif mkt and mkt.get("up_h", 0) >= 24:
        flags.append(f"BTC выше SMA20д {mkt['up_h']/24:.1f} суток")
    days_span = max(len(byday), 1)
    vol_total = hist[-1]["volume"] - hist[0]["volume"]
    prof_total = (hist[-1]["profit"] - hist[0]["profit"]) * px
    if vol_total > 0:
        marg = prof_total / vol_total * 100
        print(f"  оборот за период ${vol_total:,.0f}, "
              f"заработок ${prof_total:,.2f}, маржа {marg:.4f}%")
    for f in flags:
        print(f"  ⚠ {f}")
    if not flags:
        print("  тревог нет")


if __name__ == "__main__":
    d = 7
    if "--days" in sys.argv:
        try:
            d = int(sys.argv[sys.argv.index("--days") + 1])
        except (IndexError, ValueError):
            pass
    report(d)
