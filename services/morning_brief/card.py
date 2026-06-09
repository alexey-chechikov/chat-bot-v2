"""Ассемблер утренней TG-карточки: режим BTC + core-боты + прочие активные + альт-кандидаты.

Риск-гейты (handoff 2026-06-08): SL±$175/бот, дневной лимит 2×SL, isolated margin,
альты не оставлять на ночь, кросс-боты НЕ балансируют (мешки коррелируют, диверс +10%
в крахе) — защита = SL на каждом. Закрытие руками на net-0/~$70+.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.morning_brief import regime as rg
from services.morning_brief import tracker_reader as tr

ROOT = Path(__file__).resolve().parents[2]
MSK = timezone(timedelta(hours=3))

SL_USD = 175.0            # обязательный SL на бота
SL_WARN_USD = 140.0       # 80% от SL — алерт "у SL"
NET_CLOSE_USD = 70.0      # net-0/+$70 → пора закрыть руками
DAY_LIMIT_USD = 350.0     # дневной лимит убытка = 2×SL → стоп-день
LIQ_WARN_PCT = 15.0       # дистанция до ликвидации, ближе — алерт
TRACKER_STALE_MIN = 10.0
MAX_OTHERS = 6            # строк в секции "прочие активные"
MAX_CANDIDATES = 3
TG_HARD_LIMIT = 4000      # запас от лимита Telegram 4096

RISK_FOOTER = ("— риск: SL±$175/бот · isolated · альты НЕ на ночь · закрытие руками "
               "net-0/+$70 · дневной лимит −$350 (2×SL) · кросс-боты НЕ балансируют")


def _usd(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{v:+,.0f}$".replace(",", " ")


def _load_managed() -> list[dict]:
    cfg = json.loads((ROOT / "state" / "short_bots_managed.json").read_text(encoding="utf-8"))
    return [m for m in cfg["managed_bots"] if not m.get("testbed")]


def _liq_dist_pct(side: str, px: float, liq: float | None) -> float | None:
    if not liq or not px:
        return None
    if side == "short":
        return (liq - px) / px * 100.0
    return (px - liq) / px * 100.0


def _day_delta(slot: dict) -> tuple[float | None, float | None]:
    """(реализованный Δ за сутки мск, net за сутки = реализ.Δ + Δ мешка)."""
    latest, day0 = slot.get("latest"), slot.get("day0")
    if not latest or not day0:
        return None, None
    if latest.get("profit") is None or day0.get("profit") is None:
        return None, None
    realized = latest["profit"] - day0["profit"]
    bag_now = latest.get("current_profit") or 0.0
    bag_then = day0.get("current_profit") or 0.0
    return realized, realized + (bag_now - bag_then)


def collect(include_scan: bool = True) -> dict:
    """Собирает все секции; каждая защищена — карточка уходит с тем, что доступно."""
    errors: list[str] = []
    out: dict = {"errors": errors, "now_msk": datetime.now(MSK)}

    try:
        out["regime"] = rg.regime()
    except Exception as e:
        out["regime"] = None
        errors.append(f"режим BTC недоступен: {str(e)[:60]}")

    try:
        out["snap"] = tr.read_snapshots()
    except Exception as e:
        out["snap"] = {"bots": {}, "stale_min": None}
        errors.append(f"трекер-снапшоты недоступны: {str(e)[:60]}")
    try:
        out["params"] = tr.read_params()
    except Exception as e:
        out["params"] = {}
        errors.append(f"трекер-params недоступны: {str(e)[:60]}")

    out["managed"] = _load_managed()

    out["scan"] = None
    if include_scan:
        try:
            sys.path.insert(0, str(ROOT / "tools"))
            import _alt_grid_scan
            out["scan"] = _alt_grid_scan.scan()
        except Exception as e:
            errors.append(f"альт-сканер упал: {str(e)[:60]}")
        finally:
            if str(ROOT / "tools") in sys.path:
                sys.path.remove(str(ROOT / "tools"))
    return out


def build_card(data: dict) -> str:
    now = data["now_msk"]
    r = data["regime"]
    snap = data["snap"]
    params = data["params"]
    bots = snap.get("bots", {})
    alerts: list[str] = list(data["errors"])
    L: list[str] = [f"☀️ БРИФИНГ {now:%d.%m} · {now:%H:%M} мск"]

    # ── час для запуска альтов
    scan = data.get("scan")
    if scan:
        L.append(f"⏰ {scan['tilt']} · окно для новых альтов: 16–20 мск")

    # ── рынок
    if r:
        vol = f"vol-z {r['z']:.1f}" + (" ⚠️VOL-OFF" if r["voloff"] else "")
        L.append("━ РЫНОК")
        L.append(f"BTC {r['px']:,.0f} · красная {r['t200']:,.0f} ({r['above']:+.2f}%) · {r['zone']} · {vol}")
        if r["voloff"]:
            alerts.append("VOL-OFF спайк (ATR-z≥2.5) — оцени краш руками, авто-рез НЕ делаем")
    else:
        L.append("━ РЫНОК: ✖ нет данных")

    # ── core-боты
    L.append("━ CORE-БОТЫ")
    managed_ids = set()
    for m in data["managed"]:
        bid, side, alias = m["bot_id"], m["side"], m["alias"]
        managed_ids.add(bid)
        slot = bots.get(bid)
        latest = slot["latest"] if slot else None
        if not latest:
            L.append(f"{alias}: не виден трекером")
            alerts.append(f"{alias} ({bid}) не виден трекером >24ч — удалён из GinArea? "
                          "обнови state/short_bots_managed.json")
            continue
        st = latest["status"]
        if st != tr.STATUS_ACTIVE:
            label = tr.STATUS_LABEL.get(st, str(st))
            L.append(f"{alias}: {label}")
            if st == tr.STATUS_FAILED:
                alerts.append(f"{alias} в статусе FAILED — проверь GinArea")
            continue
        if r:
            v = rg.verdict(side, r["zone"], r["voloff"])
            lvl = rg.close_level(side, r["t200"])
            act = "закрой при" if side == "short" else "закрой при пробое"
            L.append(f"{alias} {v.split(' — ')[0]} · {act} {lvl:,.0f}")
        else:
            L.append(f"{alias} (режим неизвестен)")
        realized, _net = _day_delta(slot)
        day = f" ({_usd(realized)}/д)" if realized is not None else ""
        bits = [f"профит {_usd(latest['profit'])}{day}"]
        bag = latest.get("current_profit")
        if bag is not None:
            bits.append(f"мешок {_usd(bag)}")
        pos = latest.get("position")
        if pos:
            bits.append(f"поз {pos:+g}")
        liq_d = _liq_dist_pct(side, (r or {}).get("px") or 0, latest.get("liquidation_price"))
        if liq_d is not None:
            warn = " ⚠️БЛИЗКО" if liq_d < LIQ_WARN_PCT else ""
            bits.append(f"ликв {liq_d:+.0f}%{warn}")
            if liq_d < LIQ_WARN_PCT:
                alerts.append(f"{alias}: ликвидация ближе {LIQ_WARN_PCT:.0f}% — разгрузи/добавь маржи")
        p = params.get(bid)
        if p and r:
            bf = rg.border_flag(side, r["px"], (p.get("border_bottom"), p.get("border_top")))
            if bf:
                bits.append(bf.strip())
            if "у TOP" in bf or "у BOTTOM" in bf:
                alerts.append(f"{alias}: цена у адверс-border — мешок к максимуму, брать профит до упора")
        L.append("   " + " · ".join(bits))

    # ── прочие активные (вкл. альт-гриды) — правила SL/net-close
    others = []
    for bid, slot in bots.items():
        latest = slot.get("latest")
        if not latest or bid in managed_ids or latest["status"] != tr.STATUS_ACTIVE:
            continue
        others.append((bid, slot, latest))
    others.sort(key=lambda x: -abs(x[2].get("current_profit") or 0))
    if others:
        L.append("━ ПРОЧИЕ АКТИВНЫЕ")
        for bid, slot, latest in others[:MAX_OTHERS]:
            name = (latest.get("bot_name") or bid).strip()[:24].strip()
            bag = latest.get("current_profit")
            _realized, net = _day_delta(slot)
            bits = [f"профит {_usd(latest['profit'])}"]
            if bag is not None:
                bits.append(f"мешок {_usd(bag)}")
            if net is not None:
                bits.append(f"день {_usd(net)}")
            flags = ""
            if bag is not None and bag <= -SL_WARN_USD:
                flags += " ⚠️у SL"
                alerts.append(f"{name}: мешок {_usd(bag)} — у SL −$175, проверь стоп")
            if net is not None and net >= NET_CLOSE_USD:
                flags += " 💰закрой руками"
                alerts.append(f"{name}: net за день {_usd(net)} ≥ +$70 — правило: закрыть руками")
            L.append(f"{name}: " + " · ".join(bits) + flags)
        if len(others) > MAX_OTHERS:
            L.append(f"(+{len(others) - MAX_OTHERS} ещё)")

    # ── мешки на стопе: бот не активен, но позиция висит на бирже
    stopped_bags = []
    for bid, slot in bots.items():
        latest = slot.get("latest")
        if not latest or latest["status"] == tr.STATUS_ACTIVE:
            continue
        if latest.get("position"):
            stopped_bags.append(latest)
    stopped_bags.sort(key=lambda x: -abs(x.get("current_profit") or 0))
    if stopped_bags:
        L.append("━ МЕШКИ НА СТОПЕ (бот выключен, позиция висит)")
        for latest in stopped_bags[:4]:
            name = (latest.get("bot_name") or latest["bot_id"]).strip()[:24].strip()
            bits = [f"поз {latest['position']:+g}", f"мешок {_usd(latest.get('current_profit'))}"]
            if latest.get("average_price"):
                bits.append(f"avg {latest['average_price']:,.0f}")
            L.append(f"{name}: " + " · ".join(bits))

    # ── портфель
    act = [x[2] for x in others] + [bots[b]["latest"] for b in managed_ids
                                    if bots.get(b) and bots[b]["latest"]
                                    and bots[b]["latest"]["status"] == tr.STATUS_ACTIVE]
    bag_sum = sum(x.get("current_profit") or 0 for x in act)
    stopped_bag_sum = sum(x.get("current_profit") or 0 for x in stopped_bags)
    day_net = 0.0
    have_day = False
    for bid, slot in bots.items():
        latest = slot.get("latest")
        if not latest or latest["status"] != tr.STATUS_ACTIVE:
            continue
        _re, net = _day_delta(slot)
        if net is not None:
            day_net += net
            have_day = True
    L.append("━ ПОРТФЕЛЬ")
    pbits = [f"активных {len(act)}", f"∑мешок {_usd(bag_sum)}"]
    if stopped_bags:
        pbits.append(f"стоп-мешки {_usd(stopped_bag_sum)} ({len(stopped_bags)})")
    if have_day:
        lim = " 🛑 СТОП-ДЕНЬ" if day_net <= -DAY_LIMIT_USD else " (лимит −$350 ok)"
        pbits.append(f"день {_usd(day_net)}{lim}")
        if day_net <= -DAY_LIMIT_USD:
            alerts.append(f"дневной лимит пробит: {_usd(day_net)} ≤ −$350 — стоп-день, новых не открывать")
    L.append(" · ".join(pbits))
    stale = snap.get("stale_min")
    if stale is not None and stale > TRACKER_STALE_MIN:
        alerts.append(f"трекер молчит {stale:.0f} мин — данные ботов устарели")

    # ── альт-кандидаты
    if scan:
        good = [x for x in scan["rows"] if not x["danger"] and not x["thin"]][:MAX_CANDIDATES]
        L.append("━ АЛЬТ-КАНДИДАТЫ (топ ✅, MegaHard 12%)")
        if good:
            for x in good:
                m, a = x["m"], x["a"]
                L.append(f"{x['sym']}: rng24 {m['rng24']:.1f}% · ER {m['er']:.2f} · ликв {x['liqrel']:.2f}")
                L.append(f"   step {a['step']} · орд {a['ordcnt']} · охват {a['span']}% · target {a['target']}"
                         f" · mult {a['mult']} · size {a['size']:.2f}/{a['maxsz']:.2f}"
                         f" · off −{a['baseoff']} · TP/SL ±$175")
        else:
            L.append("нет чистых кандидатов (всё 🚫/⚠ — памп/тренд/тонко)")

    # ── алерты
    if alerts:
        L.append("━ ⚠️ АЛЕРТЫ")
        seen = set()
        for a in alerts:
            if a not in seen:
                L.append(f"• {a}")
                seen.add(a)
    L.append(RISK_FOOTER)

    card = "\n".join(L)
    if len(card) > TG_HARD_LIMIT:
        card = card[:TG_HARD_LIMIT - 12] + "\n…(обрезано)"
    return card


def build_morning_card(include_scan: bool = True) -> str:
    return build_card(collect(include_scan=include_scan))
