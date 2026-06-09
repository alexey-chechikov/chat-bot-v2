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

DUST_USD = 1.0            # «прочие активные»: пыль (|профит|,|мешок|,|день| < $1, поз 0) не показываем
PREV_STATE = ROOT / "state" / "brief_card_state.json"
PREV_MAX_AGE_H = 8.0      # Δ-блок только если прошлая карточка свежее 8ч


def _load_prev() -> dict | None:
    try:
        d = json.loads(PREV_STATE.read_text(encoding="utf-8"))
        d["ts"] = datetime.fromisoformat(d["ts"])
        return d
    except Exception:
        return None


def _save_prev(now: datetime, px: float | None, total_current: float) -> None:
    PREV_STATE.write_text(json.dumps(
        {"ts": now.isoformat(timespec="seconds"), "px": px, "total_current": total_current},
        ensure_ascii=False), encoding="utf-8")


def _usd(v: float | None) -> str:
    if v is None:
        return "?"
    if abs(v) < 0.5:
        v = 0.0  # не показывать «-0$» на пыли
    return f"{v:+,.0f}$".replace(",", " ")


def _bag(row: dict) -> float | None:
    """Нереализованный мешок = currentProfit − profit (GinArea: currentProfit
    включает реализованный профит; при позиции 0 поля равны → мешок 0)."""
    cur, prof = row.get("current_profit"), row.get("profit")
    if cur is None or prof is None:
        return None
    return cur - prof


def _normalize_units(bots: dict, px: float | None) -> None:
    """Inverse-боты (XBTUSD) считают PnL в XBT, не в $: у них balance — XBT-кошелёк
    (< 5), у linear/USDT — сотни-тысячи. Конвертируем profit/currentProfit в $ по px,
    чтобы мешок −0.25 XBT не выглядел как «0$» (реально ≈ −$15k)."""
    if not px:
        return
    for slot in bots.values():
        for key in ("latest", "day0"):
            row = slot.get(key)
            if not row or row.get("_usd_normalized"):
                continue
            b = row.get("balance")
            if b is not None and 0 < b < 5:
                for f in ("profit", "current_profit"):
                    if row.get(f) is not None:
                        row[f] = row[f] * px
                row["_unit_xbt"] = True
            row["_usd_normalized"] = True


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
    """(реализованный Δ за сутки мск = Δprofit, net за сутки = ΔcurrentProfit)."""
    latest, day0 = slot.get("latest"), slot.get("day0")
    if not latest or not day0:
        return None, None
    if latest.get("profit") is None or day0.get("profit") is None:
        return None, None
    realized = latest["profit"] - day0["profit"]
    if latest.get("current_profit") is None or day0.get("current_profit") is None:
        return realized, None
    return realized, latest["current_profit"] - day0["current_profit"]


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
    out["prev"] = _load_prev()

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
    _normalize_units(bots, (r or {}).get("px"))
    alerts: list[str] = list(data["errors"])
    emoji = "☀️" if 7 <= now.hour < 12 else ("🌙" if now.hour >= 23 or now.hour < 7 else "🕐")
    L: list[str] = [f"{emoji} БРИФИНГ {now:%d.%m} · {now:%H:%M} мск"]

    prev = data.get("prev")
    age_lbl = ""
    if prev and prev.get("ts"):
        prev_age_h = (now - prev["ts"].astimezone(MSK)).total_seconds() / 3600.0
        if 0 < prev_age_h <= PREV_MAX_AGE_H:
            age_lbl = f"{prev_age_h:.0f}ч" if prev_age_h >= 0.95 else f"{prev_age_h * 60:.0f}м"
        else:
            prev = None

    # ── час для запуска альтов
    scan = data.get("scan")
    if scan:
        L.append(f"⏰ {scan['tilt']} · окно для новых альтов: 16–20 мск")

    # ── рынок
    if r:
        vol = f"vol-z {r['z']:.1f}" + (" ⚠️VOL-OFF" if r["voloff"] else "")
        dpx = ""
        if prev and prev.get("px"):
            dpx = f" (Δ{age_lbl} {(r['px'] / prev['px'] - 1) * 100:+.1f}%)"
        L.append("━ РЫНОК")
        L.append(f"BTC {r['px']:,.0f}{dpx} · красная {r['t200']:,.0f} ({r['above']:+.2f}%) · {r['zone']} · {vol}")
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
        latest = slot["latest"] if slot and slot.get("fresh") else None
        if not latest:
            L.append(f"{alias}: не виден трекером")
            alerts.append(f"{alias} ({bid}) не виден трекером — удалён из GinArea? "
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
        bag = _bag(latest)
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
        if not latest or not slot.get("fresh") or bid in managed_ids \
                or latest["status"] != tr.STATUS_ACTIVE:
            continue
        bag = _bag(latest)
        _realized, net = _day_delta(slot)
        dust = (not latest.get("position")
                and abs(latest.get("profit") or 0) < DUST_USD
                and abs(bag or 0) < DUST_USD
                and abs(net or 0) < DUST_USD)
        if dust:
            continue  # свежесозданные/пустые боты — шум
        others.append((bid, slot, latest))
    others.sort(key=lambda x: -abs(_bag(x[2]) or 0))
    if others:
        L.append("━ ПРОЧИЕ АКТИВНЫЕ")
        for bid, slot, latest in others[:MAX_OTHERS]:
            name = (latest.get("bot_name") or bid).strip()[:24].strip()
            bag = _bag(latest)
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
        if not latest or not slot.get("fresh") or latest["status"] == tr.STATUS_ACTIVE:
            continue
        if latest.get("position"):
            stopped_bags.append(latest)
    stopped_bags.sort(key=lambda x: -abs(_bag(x) or 0))
    if stopped_bags:
        L.append("━ МЕШКИ НА СТОПЕ (бот выключен, позиция висит)")
        for latest in stopped_bags[:4]:
            name = (latest.get("bot_name") or latest["bot_id"]).strip()[:24].strip()
            bits = [f"поз {latest['position']:+g}", f"мешок {_usd(_bag(latest))}"]
            if latest.get("average_price"):
                bits.append(f"avg {latest['average_price']:,.0f}")
            L.append(f"{name}: " + " · ".join(bits))

    # ── портфель
    act = [x[2] for x in others] + [bots[b]["latest"] for b in managed_ids
                                    if bots.get(b) and bots[b]["latest"]
                                    and bots[b]["latest"]["status"] == tr.STATUS_ACTIVE]
    bag_sum = sum(_bag(x) or 0 for x in act)
    stopped_bag_sum = sum(_bag(x) or 0 for x in stopped_bags)
    total_current = sum(x.get("current_profit") or 0 for x in act)
    data["_total_current"] = total_current  # для Δ следующей карточки (build_morning_card)
    day_net = 0.0
    have_day = False
    for bid, slot in bots.items():
        latest = slot.get("latest")
        if not latest or not slot.get("fresh") or latest["status"] != tr.STATUS_ACTIVE:
            continue
        _re, net = _day_delta(slot)
        if net is not None:
            day_net += net
            have_day = True
    L.append("━ ПОРТФЕЛЬ")
    pbits = [f"активных {len(act)}", f"∑мешок {_usd(bag_sum)}"]
    if stopped_bags:
        pbits.append(f"стоп-мешки {_usd(stopped_bag_sum)} ({len(stopped_bags)})")
    if prev and prev.get("total_current") is not None:
        pbits.append(f"Δ{age_lbl} {_usd(total_current - prev['total_current'])}")
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
    data = collect(include_scan=include_scan)
    card = build_card(data)
    try:
        _save_prev(data["now_msk"], (data.get("regime") or {}).get("px"),
                   data.get("_total_current", 0.0))
    except Exception:
        pass  # Δ-блок — best effort, карточку не валим
    return card
