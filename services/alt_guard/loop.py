"""Alt-Guard: сторож живых альт-гридов (Dynamic-Auto, side=3, не managed).

Пинги (риск-рамка handoff 2026-06-08 + правила оператора):
1. net дня ≥ +$70  → «закрой руками» (правило net-0/+$70, кулдаун 4ч/бот)
2. мешок ≤ −0.8×SL (SL из tsl, дефолт $175) → «подходит к SL» (4ч/бот)
3. бот был активен → перестал (статус ≠ 2) → «остановился (SL/стоп?)» (1 раз)
4. XRP памп-guard: funding ≤ FUNDING_PUMP_THRESH ИЛИ mark +3%/час →
   «подтяни short-ногу» (4ч). Research: XRP funding = единственный предиктор
   kill-хвоста (AUC 0.695, ~2x lift, направленный вверх); точный порог у Win —
   пока консервативный −0.03%/8ч + прайс-триггер, который от калибровки не зависит.
5. каскад BTC ≥5 (cascade_alert_dedup свежий) → «альты коррелируют» (2ч)
6. 23:00 мск → вечерний чек «альты на ночь не оставляем» (1 раз/сутки)

Источники только с диска: ginarea_live/*.csv (НЕ GinArea API — сессию держит
трекер), state/deriv_live.json, state/deriv_live_history.jsonl,
state/cascade_alert_dedup.json. Состояние: state/alt_guard_state.json.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "state" / "alt_guard_state.json"
DERIV_PATH = ROOT / "state" / "deriv_live.json"
DERIV_HIST_PATH = ROOT / "state" / "deriv_live_history.jsonl"
CASCADE_DEDUP_PATH = ROOT / "state" / "cascade_alert_dedup.json"
REGIME_V2_PATH = ROOT / "state" / "regime_v2_state.json"  # BTCUSDT.4h.state_3state

MSK = timezone(timedelta(hours=3))

NET_CLOSE_USD = 70.0          # net-0/+$70 → закрыть руками
SL_DEFAULT_USD = 175.0
# 2026-06-11 SOL-урок: Dynamic-Auto при закрытии цикла уходит в статус 13 на
# ~1 мин (поза 0) и возвращается в 2 — это НЕ остановка. Пинг «остановился»
# только после N минут подряд не-активности + пинг «возобновился» после него.
STOP_CONFIRM_MIN = 3.0
SL_WARN_FRAC = 0.8            # 80% от SL → предупреждение
# 2026-06-10 WLD-урок: симметричный грид в MARKDOWN набивает ЛОНГ-мешок до SL
# (WLD: +71 профит short-ногой → реверс в лонг → мешок −181 → tsl). Ранний пинг,
# когда нога ПРОТИВ режима BTC 4h и мешок ≥ 40% SL — решать на −$70, не на −$143.
REGIME_LEG_FRAC = 0.4
FUNDING_PUMP_THRESH = -0.0003  # −0.03%/8ч; уточнить порог из research у Win
PUMP_MOVE_1H_PCT = 3.0        # XRP +3%/час → памп уже идёт
CASCADE_FRESH_MIN = 5.0

COOLDOWN_H = {"net": 4.0, "slwarn": 4.0, "xrp_pump": 4.0, "cascade": 2.0,
              "regime_leg": 4.0, "drift1": 2.0, "drift2": 2.0, "drift3": 0.5,
              "idio": 2.0, "exitfast": 2.0}
DRIFT_SERIES_HOURS = 4.0      # глубина ряда для drift-монитора Win
BAG_JOURNAL = ROOT / "state" / "alt_guard_bag_journal.jsonl"  # worst-bag/день — калибровка порогов (Win Q3)
# Задача 2 Вина [просадка]: ПРЕДОХРАНИТЕЛЬ СЕРИИ. 2 типизированных STOP-EVENT в окне
# → ПАУЗА на новые альты до RESTART-условия (режим успокоился). Не пере-вооружаться
# во враждебный режим. RESTART = BTC 4h вернулся в RANGE (regime_v2) — прокси «успокоения».
STOP_SERIES_N = 2             # стопов подряд для срабатывания
STOP_SERIES_WINDOW_H = 24.0   # в каком окне считать «подряд»
STOP_LABELS = {12: "выключен", 16: "стоп TP/SL", 10: "FAILED"}
# DECORR (Win ретро 11-12.06, биржевые 1m): «упал на 3% сильнее BTC за 30 мин» =
# маркер дрейфера ЗА ЧАСЫ до bag-Stage3 (WLD: 11:16 vs 16:14), 0 ложняков SOL/XRP.
# Комплемент: декорр ловит идиосинкразию, bag-монитор — коррелированный дрейф. n=1!
BTC_1M_CSV = ROOT / "market_live" / "market_1m.csv"
# Портфельный гейт дня (Win): асимметрия +25/−99 → нужен winrate>80%. Если ∑net
# альтов за день ≤ порога — стоп на НОВЫЕ альт-боты до завтра (пинг раз в день).
ALT_DAY_GATE_USD = -90.0
EVENING_HOUR_MSK = 23
POLL_INTERVAL_SEC = 60


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except OSError:
        logger.exception("alt_guard.state_save_failed")


def _parse_ts(s) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _cooldown_ok(state: dict, key: str, now: datetime, hours: float) -> bool:
    last = (state.get("pings") or {}).get(key)
    if not last:
        return True
    try:
        return (now - datetime.fromisoformat(last)).total_seconds() >= hours * 3600
    except ValueError:
        return True


def _mark(state: dict, key: str, now: datetime) -> None:
    state.setdefault("pings", {})[key] = now.isoformat(timespec="seconds")


def _alt_bots(snap: dict, params: dict, managed_ids: set[str]) -> list[tuple[str, dict, dict]]:
    """[(bot_id, slot, params_row)] — fresh Dynamic-Auto (side=3) не из managed."""
    out = []
    for bid, slot in snap.get("bots", {}).items():
        latest = slot.get("latest")
        if not latest or not slot.get("fresh") or bid in managed_ids:
            continue
        p = params.get(bid)
        if not p or str(p.get("side")).strip() != "3":
            continue
        out.append((bid, slot, p))
    return out


def _sl_usd(p: dict) -> float:
    try:
        raw = json.loads(p.get("raw_params_json") or "{}")
        tsl = raw.get("tsl")
        if tsl:
            return abs(float(tsl))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return SL_DEFAULT_USD


def _xrp_px_1h_ago(now: datetime, path: Path = DERIV_HIST_PATH,
                   tail_bytes: int = 400_000) -> float | None:
    """mark_price XRPUSDT ~час назад из хвоста deriv-истории (снапшоты ~5 мин)."""
    if not path.exists():
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    target = now - timedelta(hours=1)
    best_px, best_gap = None, None
    for line in lines:
        try:
            d = json.loads(line)
            ts = datetime.fromisoformat(d["last_updated"])
            px = (d.get("XRPUSDT") or {}).get("mark_price")
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            continue
        if px is None:
            continue
        gap = abs((ts - target).total_seconds())
        if best_gap is None or gap < best_gap:
            best_gap, best_px = gap, float(px)
    if best_gap is not None and best_gap <= 1800:  # снапшот в ±30 мин от цели
        return best_px
    return None


def evaluate(*, snap: dict, params: dict, managed_ids: set[str], deriv: dict,
             xrp_px_1h_ago: float | None, cascade_dedup: dict,
             state: dict, now: datetime,
             regime_3state: str | None = None,
             drift: dict[str, tuple] | None = None,
             idio: dict[str, float] | None = None,
             exitfast: dict[str, tuple] | None = None) -> tuple[list[str], dict]:
    """Чистая логика: → (список пингов, обновлённый state). Никакого IO."""
    from services.morning_brief import tracker_reader as tr_mod
    from services.morning_brief.card import _bag, _day_delta

    alerts: list[str] = []
    alts = _alt_bots(snap, params, managed_ids)
    prev_active = dict(state.get("prev_active") or {})
    new_active: dict[str, bool] = {}
    inactive = dict(state.get("inactive") or {})  # {bid: {"since": iso, "pinged": bool}}

    for bid, slot, p in alts:
        latest = slot["latest"]
        name = (latest.get("bot_name") or bid).strip()[:16].strip()
        active = latest["status"] == 2
        new_active[bid] = active
        bag = _bag(latest) or 0.0
        _realized, net = _day_delta(slot)

        if not active:
            # дебаунс: рестарт цикла (статус 13, ~1 мин) — не остановка
            if prev_active.get(bid) or bid in inactive:
                rec = inactive.get(bid) or {"since": now.isoformat(timespec="seconds"),
                                            "pinged": False}
                try:
                    since = datetime.fromisoformat(rec["since"])
                except ValueError:
                    since = now
                if (not rec["pinged"]
                        and (now - since).total_seconds() >= STOP_CONFIRM_MIN * 60):
                    st = latest["status"]
                    label = tr_mod.STATUS_LABEL.get(st, f"статус {st}")
                    # типизированный STOP-EVENT (задача 2.1 Вина): тип/причина/цена/pnl
                    etype = "STOP-TPSL" if st == 16 else ("STOP-FAIL" if st == 10 else "STOP-OFF")
                    alerts.append(f"🛑 ALT-GUARD {name}: [{etype}] бот остановился — {label} · "
                                  f"профит {latest.get('profit'):+,.0f}$ · мешок {bag:+,.0f}$")
                    rec["pinged"] = True
                    # регистрируем стоп для предохранителя серии (только убыточные/TP-SL)
                    if st in (16, 10) or (latest.get("profit") or 0) < 0:
                        # reason: был ли бот стойким дрифтером перед стопом (Win f337990)
                        last_drift = (state.get("drift_last") or {}).get(bid, {})
                        reason = ("persistent_drift" if int(last_drift.get("stage", 0)) >= 3
                                  else "sl_or_off")
                        state.setdefault("stop_events", []).append(
                            {"ts": now.isoformat(timespec="seconds"), "bot": name,
                             "type": etype, "profit": latest.get("profit"), "reason": reason})
                inactive[bid] = rec
            continue
        # снова активен: если успели пингануть остановку — закрываем историю
        rec = inactive.pop(bid, None)
        rwp = state.setdefault("resumed_with_pos", {})
        if rec is not None:
            # бот был выключен → снова активен. Если поза висит под водой = РЕЗЬЮМ-с-позой
            # (опасно: догон сетки в движении). Помечаем на окно для EXIT-FAST-детектора.
            if latest.get("position") and bag < 0:
                rwp[bid] = now.isoformat(timespec="seconds")
            if rec.get("pinged"):
                alerts.append(f"▶️ ALT-GUARD {name}: бот СНОВА АКТИВЕН · "
                              f"профит {latest.get('profit'):+,.0f}$ · мешок {bag:+,.0f}$")
        # чистим протухший resume-флаг (>30 мин)
        rts = _parse_ts(rwp.get(bid))
        if rts and (now - rts).total_seconds() > 1800:
            rwp.pop(bid, None)

        if net is not None and net >= NET_CLOSE_USD and _cooldown_ok(state, f"{bid}:net", now, COOLDOWN_H["net"]):
            alerts.append(f"💰 ALT-GUARD {name}: net дня {net:+,.0f}$ ≥ +$70 — "
                          f"правило: закрыть руками (мешок {bag:+,.0f}$)")
            _mark(state, f"{bid}:net", now)

        sl = _sl_usd(p)
        if bag <= -SL_WARN_FRAC * sl and _cooldown_ok(state, f"{bid}:slwarn", now, COOLDOWN_H["slwarn"]):
            alerts.append(f"⚠️ ALT-GUARD {name}: мешок {bag:+,.0f}$ — {abs(bag)/sl*100:.0f}% "
                          f"от SL −${sl:.0f}. Решай: дождаться SL / закрыть раньше")
            _mark(state, f"{bid}:slwarn", now)

        # drift-лестница Win (tools/_grid_drift_monitor.py, валидирована на 10.06):
        # пингуем ПЕРЕХОДЫ вверх; Stage 3 повторяется каждые 30 мин, пока держится.
        if drift and bid in drift:
            stage, action, mx = drift[bid]
            # StageAlerter-дедуп (Win f337990): эмитим ТОЛЬКО на смену стадии вверх;
            # Stage-3 напоминаем раз в час; спад ≥2→0 = «дрифт снят». Состояние per bot
            # в persist-стейте (процесс рестартится). Убивает спам Stage-2 (было 6× за 14ч).
            dl = state.setdefault("drift_last", {})
            rec = dl.get(bid)
            prev_stage = int(rec["stage"]) if rec else 0
            emit = False
            if rec is None:
                emit = stage >= 1
            elif stage > prev_stage:
                emit = True
            elif stage >= 3:
                last_emit = _parse_ts((rec or {}).get("emit_ts"))
                emit = bool(last_emit and (now - last_emit).total_seconds() >= 3600)
            if emit:
                icons = {1: "🟡", 2: "🟠", 3: "🔴"}
                alerts.append(
                    f"{icons[stage]} DRIFT Stage {stage} {name}: {action}\n"
                    f"   мешок {mx['bag']:+,.0f}$ ({mx['bag_pct']:.0%} SL) · "
                    f"поза-pin {mx['pos_pin']:.2f} · total {mx['total']:+,.0f}$"
                    f" · пригвождён<0 {mx.get('pinned_neg_min', 0):.0f}м"
                    + ("\n   step/target ×2 меняются на живом боте БЕЗ рестарта "
                       "(доказано 10.06)" if stage == 2 else "")
                    + ("\n   Stage 3 = закрыть СЕЙЧАС, не ждать −175 на дне "
                       "(дискриминатор: знак total + длительность, не глубина мешка)" if stage == 3 else ""))
                dl[bid] = {"stage": stage, "emit_ts": now.isoformat(timespec="seconds")}
            elif stage != prev_stage:
                # стадия сменилась, но не эмитим (спад) — обновляем без emit_ts-сброса
                dl[bid] = {"stage": stage, "emit_ts": (rec or {}).get("emit_ts", now.isoformat(timespec="seconds"))}
                if prev_stage >= 2 and stage == 0:
                    alerts.append(f"▶️ DRIFT снят {name}: вернулся в healthy "
                                  f"(мешок {mx['bag']:+,.0f}$, total {mx['total']:+,.0f}$)")
            # worst-bag журнал (калибровка порогов, Win Q3)
            wb = state.setdefault("worst_bag", {})
            rec = wb.get(bid) or {"date": "", "worst_pct": 0.0}
            today = now.astimezone(MSK).date().isoformat()
            if rec.get("date") != today:
                if rec.get("date"):
                    state.setdefault("_bag_flush", []).append(
                        {"date": rec["date"], "bot_id": bid, "name": name,
                         "worst_bag_pct": rec["worst_pct"]})
                rec = {"date": today, "worst_pct": 0.0}
            rec["worst_pct"] = max(rec["worst_pct"], round(float(mx.get("bag_pct") or 0), 3))
            wb[bid] = rec

        # DECORR-пинг (Win, ретро: за часы до bag-Stage3): альт уехал от BTC ≥3%/30мин
        if idio and bid in idio and _cooldown_ok(state, f"{bid}:idio", now, COOLDOWN_H["idio"]):
            ex = idio[bid]
            if abs(ex) >= 3.0:
                leg = "ЛОНГ-нога" if ex < 0 else "ШОРТ-нога"
                arrow = "вниз" if ex < 0 else "вверх"
                alerts.append(f"🟠 DECORR {name}: ушёл {arrow} на {abs(ex):.1f}% сильнее BTC "
                              f"за 30 мин — маркер дрейфера (ретро WLD: сигнал за 5ч до стопа). "
                              f"Под ударом {leg} · мешок {bag:+,.0f}$. Подтяни SL / готовь закрытие")
                _mark(state, f"{bid}:idio", now)

        # EXIT-FAST против стороны позы (Win SOL-резьюм-урок): подтверждённый взрывной
        # ход (Donchian+ATR+объём, 0 ложных в ренже) ПРОТИВ висящей позы = kill-switch.
        # Поза шорт (<0) + пробой ВВЕРХ, или лонг (>0) + пробой ВНИЗ.
        pos_ef = latest.get("position") or 0
        if (exitfast and bid in exitfast and pos_ef and bag < 0
                and _cooldown_ok(state, f"{bid}:exitfast", now, COOLDOWN_H["exitfast"])):
            fired, ef_dir = exitfast[bid]
            against = (pos_ef < 0 and ef_dir > 0) or (pos_ef > 0 and ef_dir < 0)
            if fired and against:
                # резьюм-вариант: бот недавно был выключен с висящей позой
                just_resumed = bool((state.get("resumed_with_pos") or {}).get(bid))
                arrow = "ВВЕРХ" if ef_dir > 0 else "ВНИЗ"
                leg = "ШОРТ" if pos_ef < 0 else "ЛОНГ"
                if just_resumed:
                    alerts.append(
                        f"🚨 EXIT-FAST {name}: взрывной ход {arrow} ПРОТИВ {leg}-позы на РЕЗЬЮМЕ "
                        f"(мешок {bag:+,.0f}$). Урок SOL −350: резюм догоняет сетку в движении. "
                        f"ЗАКРОЙ позу (фикс ~безубыток) + открой НОВЫЙ бот, НЕ резюмируй.")
                else:
                    alerts.append(
                        f"🚨 EXIT-FAST {name}: подтверждённый взрывной ход {arrow} ПРОТИВ {leg}-ноги "
                        f"(мешок {bag:+,.0f}$, Donchian+ATR+объём, 0 ложных в ренже). "
                        f"Kill-switch: закрой ногу СЕЙЧАС, не жди −175 на дне.")
                _mark(state, f"{bid}:exitfast", now)

        # нога против режима BTC (WLD-урок 2026-06-10): ранний пинг на 40% SL
        pos = latest.get("position") or 0
        against = ((regime_3state == "MARKDOWN" and pos > 0)
                   or (regime_3state == "MARKUP" and pos < 0))
        if (against and bag <= -REGIME_LEG_FRAC * sl
                and _cooldown_ok(state, f"{bid}:regime_leg", now, COOLDOWN_H["regime_leg"])):
            leg = "ЛОНГ" if pos > 0 else "ШОРТ"
            alerts.append(f"🔻 ALT-GUARD {name}: {leg}-нога ПРОТИВ режима BTC "
                          f"({regime_3state}) · мешок {bag:+,.0f}$ ({abs(bag)/sl*100:.0f}% SL). "
                          f"WLD-урок: в тренде нога доберёт до SL — рассмотри закрытие "
                          f"ноги/бота сейчас")
            _mark(state, f"{bid}:regime_leg", now)

    # XRP памп-guard — только если XRP-грид жив
    xrp_alive = any((s["latest"].get("bot_name") or "").strip().upper().startswith("XRP")
                    and s["latest"]["status"] == 2 for _, s, _p in alts)
    if xrp_alive:
        x = deriv.get("XRPUSDT") or {}
        fund = x.get("funding_rate_8h")
        mark = x.get("mark_price")
        move_1h = None
        if mark and xrp_px_1h_ago:
            move_1h = (float(mark) / xrp_px_1h_ago - 1) * 100.0
        trig = []
        if fund is not None and fund <= FUNDING_PUMP_THRESH:
            trig.append(f"funding {fund*100:+.3f}%/8ч ≤ {FUNDING_PUMP_THRESH*100:+.2f}%")
        if move_1h is not None and move_1h >= PUMP_MOVE_1H_PCT:
            trig.append(f"цена {move_1h:+.1f}%/час")
        if trig and _cooldown_ok(state, "xrp_pump", now, COOLDOWN_H["xrp_pump"]):
            alerts.append("⚡ ALT-GUARD XRP памп-риск: " + " · ".join(trig) +
                          " — short-нога XRP-грида под ударом (research: пампы = kill-хвост). "
                          "Подтяни SL / закрой short-ногу руками")
            _mark(state, "xrp_pump", now)

    # каскад BTC → альты коррелируют
    if alts and _cooldown_ok(state, "cascade", now, COOLDOWN_H["cascade"]):
        for ctype, ts_iso in (cascade_dedup or {}).items():
            try:
                ts = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if 0 <= (now - ts).total_seconds() <= CASCADE_FRESH_MIN * 60:
                n = sum(1 for _b, s, _p in alts if s["latest"]["status"] == 2)
                alerts.append(f"🌊 ALT-GUARD: каскад BTC ({ctype}) — мешки альтов "
                              f"КОРРЕЛИРУЮТ (диверс +10% в крахе). Глянь все {n} грида")
                _mark(state, "cascade", now)
                break

    # портфельный гейт дня (Win): ∑net альтов ≤ −$90 → новые альты сегодня не открывать
    now_msk0 = now.astimezone(MSK)
    if alts and state.get("day_gate_date") != now_msk0.date().isoformat():
        nets = []
        for _bid, s, _p in alts:
            _r, n = _day_delta(s)
            if n is not None:
                nets.append(n)
        if nets and sum(nets) <= ALT_DAY_GATE_USD:
            alerts.append(f"⛔ ALT-GUARD портфельный гейт: ∑net альтов за день "
                          f"{sum(nets):+,.0f}$ ≤ {ALT_DAY_GATE_USD:+,.0f}$ — НОВЫЕ альт-боты "
                          f"сегодня не открывать (асимметрия +25/−99: один дрейфер "
                          f"съедает трёх рейнджеров)")
            state["day_gate_date"] = now_msk0.date().isoformat()

    # вечерний чек 23:00 мск
    now_msk = now.astimezone(MSK)
    if (now_msk.hour == EVENING_HOUR_MSK
            and state.get("evening_date") != now_msk.date().isoformat()):
        live = [(bid, s) for bid, s, _p in alts if s["latest"]["status"] == 2]
        if live:
            rows = []
            for bid, s in live:
                latest = s["latest"]
                nm = (latest.get("bot_name") or bid).strip()[:12].strip()
                _r, net = _day_delta(s)
                rows.append(f"{nm} net {net:+,.0f}$ мешок {(_bag(latest) or 0):+,.0f}$"
                            if net is not None else f"{nm} мешок {(_bag(latest) or 0):+,.0f}$")
            alerts.append("🌙 ALT-GUARD 23:00 мск — альты НЕ оставляем на ночь "
                          "(тренд ночью = слив):\n" + "\n".join(f"  • {r}" for r in rows) +
                          "\nЗакрываешь / оставляешь осознанно?")
        state["evening_date"] = now_msk.date().isoformat()

    # ── ПРЕДОХРАНИТЕЛЬ СЕРИИ (задача 2 Вина): 2 стопа в окне → ПАУЗА до RESTART
    events = state.get("stop_events", [])
    cutoff = now - timedelta(hours=STOP_SERIES_WINDOW_H)
    events = [e for e in events if _parse_ts(e.get("ts")) and _parse_ts(e["ts"]) >= cutoff]
    state["stop_events"] = events
    paused = bool(state.get("series_pause"))
    if not paused and len(events) >= STOP_SERIES_N:
        names = ", ".join(f"{e['bot']}({e['type']})" for e in events[-STOP_SERIES_N:])
        alerts.append(f"⏸️ ALT-GUARD ПРЕДОХРАНИТЕЛЬ: {len(events)} стопа в {STOP_SERIES_WINDOW_H:.0f}ч "
                      f"({names}) — ПАУЗА на новые альты. Не пере-вооружаться во враждебный режим; "
                      f"жди RESTART (BTC 4h вернётся в RANGE). Текущие боты под обычным присмотром.")
        state["series_pause"] = True
        paused = True
    if paused and regime_3state == "RANGE":
        alerts.append("▶️ ALT-GUARD: режим успокоился (BTC 4h RANGE) — пауза предохранителя СНЯТА, "
                      "новые альты снова можно (по сканеру + час).")
        state["series_pause"] = False
        state["stop_events"] = []

    state["prev_active"] = new_active
    state["inactive"] = inactive
    return alerts, state


def _assess_drift(snap: dict, params: dict, managed_ids: set[str],
                  now: datetime) -> dict[str, tuple]:
    """Drift-монитор Win по живым альт-ботам: {bot_id: (stage, action, метрики)}."""
    import sys as _sys
    from services.morning_brief import tracker_reader as tr
    tools_dir = str(ROOT / "tools")
    if tools_dir not in _sys.path:
        _sys.path.insert(0, tools_dir)
    try:
        import _grid_drift_monitor as gdm
        import pandas as pd
    except Exception:
        logger.exception("alt_guard.drift_import_failed")
        return {}
    alt_ids = {bid for bid, slot, _p in _alt_bots(snap, params, managed_ids)
               if slot["latest"]["status"] == 2}
    if not alt_ids:
        return {}
    series = tr.read_series(alt_ids, hours=DRIFT_SERIES_HOURS, now=now)
    out: dict[str, tuple] = {}
    for bid, rows in series.items():
        if len(rows) < 3:
            continue
        try:
            df = pd.DataFrame(rows)
            tsl = -_sl_usd(params.get(bid) or {})
            out[bid] = gdm.assess(df, tsl=tsl)
        except Exception:
            logger.exception("alt_guard.drift_assess_failed bot=%s", bid)
    return out


def _bot_symbol(name: str) -> str | None:
    """Имя бота → BitMEX-символ: 'SOL' → SOLUSDT. Кастомные имена — пропуск."""
    tok = "".join(ch for ch in (name or "").split()[0] if ch.isalpha()).upper() if name else ""
    return f"{tok}USDT" if 2 <= len(tok) <= 6 else None


def _assess_exitfast(snap: dict, params: dict, managed_ids: set[str]) -> dict[str, tuple]:
    """EXIT-FAST по активным альт-ботам с позой: {bot_id: (fired, direction)}.
    1ч-свечи Bybit (нужен объём). Считаем только где есть висящая поза + мешок<0."""
    import json as _json
    import urllib.request
    from services.alt_guard.exit_fast import exit_fast
    out: dict[str, tuple] = {}
    for bid, slot, _p in _alt_bots(snap, params, managed_ids):
        latest = slot["latest"]
        if latest["status"] != 2 or not latest.get("position"):
            continue
        bag = (latest.get("current_profit") or 0) - (latest.get("profit") or 0)
        if bag >= 0:
            continue
        sym = _bot_symbol(latest.get("bot_name") or "")
        if not sym:
            continue
        try:
            url = (f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}"
                   "&interval=60&limit=40")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            lst = _json.load(urllib.request.urlopen(req, timeout=12)).get("result", {}).get("list", [])
            kl = sorted(lst, key=lambda x: int(x[0]))
            highs = [float(x[2]) for x in kl]; lows = [float(x[3]) for x in kl]
            closes = [float(x[4]) for x in kl]; vols = [float(x[5]) for x in kl]
            out[bid] = exit_fast(highs, lows, closes, vols)
        except Exception:
            logger.exception("alt_guard.exitfast_failed sym=%s", sym)
    return out


def _btc_1m_series(count: int = 45):
    """BTC 1m closes из локального коллектора (pd.Series c DatetimeIndex)."""
    import pandas as pd
    if not BTC_1M_CSV.exists():
        return None
    size = BTC_1M_CSV.stat().st_size
    with BTC_1M_CSV.open("rb") as fh:
        if size > 12_000:
            fh.seek(size - 12_000)
            fh.readline()
        lines = fh.read().decode("utf-8", errors="replace").splitlines()
    ts, px = [], []
    for line in lines:
        parts = line.split(",")
        if len(parts) < 5 or not parts[0].startswith("20"):
            continue
        try:
            ts.append(pd.Timestamp(parts[0]))
            px.append(float(parts[4]))
        except (ValueError, TypeError):
            continue
    if len(px) < 35:
        return None
    return pd.Series(px[-count:], index=pd.DatetimeIndex(ts[-count:]))


def _alt_1m_series(sym: str, count: int = 45):
    """Альт 1m closes с BitMEX (public, лёгкий запрос)."""
    import json as _json
    import urllib.request
    import pandas as pd
    url = ("https://www.bitmex.com/api/v1/trade/bucketed?binSize=1m&partial=false"
           f"&symbol={sym}&count={count}&reverse=true")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    rows = _json.load(urllib.request.urlopen(req, timeout=15))[::-1]
    ts = [pd.Timestamp(r["timestamp"]) for r in rows]
    px = [float(r["close"]) for r in rows]
    if len(px) < 35:
        return None
    return pd.Series(px, index=pd.DatetimeIndex(ts))


def _assess_idio(snap: dict, params: dict, managed_ids: set[str]) -> dict[str, float]:
    """DECORR: excess-ход альта vs BTC за 30 мин, % — {bot_id: excess_now}."""
    import sys as _sys
    tools_dir = str(ROOT / "tools")
    if tools_dir not in _sys.path:
        _sys.path.insert(0, tools_dir)
    try:
        import _grid_drift_monitor as gdm
    except Exception:
        logger.exception("alt_guard.idio_import_failed")
        return {}
    btc = _btc_1m_series()
    if btc is None:
        return {}
    out: dict[str, float] = {}
    for bid, slot, _p in _alt_bots(snap, params, managed_ids):
        latest = slot["latest"]
        if latest["status"] != 2:
            continue
        sym = _bot_symbol(latest.get("bot_name") or "")
        if not sym:
            continue
        try:
            alt = _alt_1m_series(sym)
            if alt is None:
                continue
            ex = gdm.idio_excess(alt, btc)
            ex = ex.dropna()
            if len(ex):
                out[bid] = round(float(ex.iloc[-1]), 2)
        except Exception:
            logger.exception("alt_guard.idio_failed sym=%s", sym)
    return out


def tick(send_fn, now: datetime | None = None) -> list[str]:
    """Один проход: чтение с диска → evaluate → отправка. Возвращает пинги."""
    from services.morning_brief import tracker_reader as tr
    from services.morning_brief.card import _load_managed

    now = now or datetime.now(timezone.utc)
    snap = tr.read_snapshots(now=now)
    params = tr.read_params()
    managed_ids = {m["bot_id"] for m in _load_managed()}
    state = _read_json(STATE_PATH, {})
    regime_3state = None
    try:
        regime_3state = (_read_json(REGIME_V2_PATH, {})
                         .get("BTCUSDT", {}).get("4h", {}).get("state_3state"))
    except AttributeError:
        pass
    alerts, state = evaluate(
        snap=snap, params=params, managed_ids=managed_ids,
        deriv=_read_json(DERIV_PATH, {}),
        xrp_px_1h_ago=_xrp_px_1h_ago(now),
        cascade_dedup=_read_json(CASCADE_DEDUP_PATH, {}),
        state=state, now=now, regime_3state=regime_3state,
        drift=_assess_drift(snap, params, managed_ids, now),
        idio=_assess_idio(snap, params, managed_ids),
        exitfast=_assess_exitfast(snap, params, managed_ids),
    )
    # worst-bag журнал (калибровка порогов drift-лестницы, Win Q3)
    for rec in state.pop("_bag_flush", []):
        try:
            with BAG_JOURNAL.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("alt_guard.bag_journal_failed")
    for text in alerts:
        logger.warning("alt_guard.ping %s", text.splitlines()[0][:120])
        if send_fn is not None:
            try:
                send_fn(text)
            except Exception:
                logger.exception("alt_guard.send_failed")
    _save_state(state)
    return alerts


async def alt_guard_loop(stop_event, *, send_fn=None,
                         interval_sec: int = POLL_INTERVAL_SEC) -> None:
    import asyncio
    if send_fn is None:
        logger.warning("alt_guard.no_send_fn — пинги только в лог")
    logger.info("alt_guard.start interval=%ds net>=+%.0f sl_warn=%.0f%% "
                "xrp_fund<=%.4f pump_1h>=%.1f%%", interval_sec, NET_CLOSE_USD,
                SL_WARN_FRAC * 100, FUNDING_PUMP_THRESH, PUMP_MOVE_1H_PCT)
    while not stop_event.is_set():
        try:
            tick(send_fn)
        except Exception:
            logger.exception("alt_guard.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("alt_guard.stopped")
