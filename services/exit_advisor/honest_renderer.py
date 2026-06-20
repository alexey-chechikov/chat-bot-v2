"""Honest exit advisor renderer v0.1 (2026-05-07).

Заменяет telegram_renderer.py format_advisory_alert который выдавал fake EV
(одинаковый +$2 для всех опций потому что _compute_ev_from_history читал
не-ту parquet). Полный аудит: docs/ANALYSIS/EXIT_ADVISOR_AUDIT_2026-05-07.md

Принципы:
1. Только ФАКТЫ состояния, без рекомендаций с EV.
2. HARD BAN list из MASTER §16.4 (P-5, P-8, P-10) как предупреждение.
3. Confirmed playbook actions (P-1, P-4, P-9) — без чисел EV до накопления
   реальных action-specific outcomes.
4. Что отслеживать для принятия решения — конкретные триггеры.
5. Никаких inline-кнопок [Действую] до того как log_decision callback wired.
"""
from __future__ import annotations

import json
from pathlib import Path

from .position_state import PositionStateSnapshot, ScenarioClass


_SCENARIO_ICONS = {
    ScenarioClass.MONITORING:          "📊",
    ScenarioClass.EARLY_INTERVENTION:  "⚠️",
    ScenarioClass.CYCLE_DEATH:         "🔴",
    ScenarioClass.MODERATE:            "🔴",
    ScenarioClass.SEVERE:              "🚨",
    ScenarioClass.CRITICAL:            "🚨",
    ScenarioClass.URGENT_PROTECTION:   "🆘",
}

_SCENARIO_LABELS_RU = {
    ScenarioClass.MONITORING:          "Мониторинг",
    ScenarioClass.EARLY_INTERVENTION:  "Ранняя интервенция (DD <4h)",
    ScenarioClass.CYCLE_DEATH:         "Цикл смерти (>=4h DD)",
    ScenarioClass.MODERATE:            "Умеренная просадка",
    ScenarioClass.SEVERE:              "Тяжёлая просадка",
    ScenarioClass.CRITICAL:            "Критическая просадка",
    ScenarioClass.URGENT_PROTECTION:   "СРОЧНО: риск ликвидации",
}


# Per scenario_class, что говорит подтверждённый playbook (PLAYBOOK.md + MASTER §16).
# Это НЕ алгоритмические EV — это правила оператора, накопленные из реального опыта.
_SCENARIO_PLAYBOOK = {
    ScenarioClass.EARLY_INTERVENTION: {
        "context": "Один из ботов в DD недавно (<4h). Это нормально для grid в тренде — сетка работает.",
        "watch": [
            "Тренд продолжается? — смотри regime_4h в /advise",
            "OI растёт против тебя? — funding flip в /advise",
            "Расстояние до liq уменьшается быстро? — distance_to_liq в этом alert",
        ],
        "operator_options_confirmed": [
            "P-1 raise boundary (если тренд подтверждён) — расширяет диапазон работы",
            "P-4 paused (новые IN остановить) — защитное, не меняет позицию",
        ],
        "hard_ban": [
            "Force close в минус — P0 violation",
        ],
    },
    ScenarioClass.CYCLE_DEATH: {
        "context": "DD держится 4+ часов. Сетка не вытаскивает из движения.",
        "watch": [
            "Тренд ослабевает? — momentum в /advise",
            "Достижение уровня (PDH/PDL/asia high)? — session_levels в /advise",
            "Liquidation cascade? — если есть, может быть точка разворота",
        ],
        "operator_options_confirmed": [
            "P-1 raise boundary — если хочешь дать сетке дальнейший простор",
            "P-9 fix or reinforce — частичная фиксация на отскоках (не в DD!)",
            "P-12 adaptive grid tighten — больше оборотов, меньше exposure per IN",
        ],
        "hard_ban": [
            "P-5 partial unload в DD — статистика OPPORTUNITY_MAP_v2: avg -$26",
            "P-8 force close + restart — avg -$192",
            "P-10 rebalance close + reenter — avg -$46 + двойной spread",
        ],
    },
    ScenarioClass.MODERATE: {
        "context": "Заметная просадка (-3..-7%) при значительной длительности. Ситуация серьёзная.",
        "watch": [
            "Margin free уровень — сколько осталось до forced close",
            "Сравни с ранее прошедшими циклами — выходило ли из таких просадок без вмешательства?",
            "Конкурсный bonus период приближается?",
        ],
        "operator_options_confirmed": [
            "P-4 paused entries — защитное",
            "Booster bot 6399265299 — manual P-16 если impulse исчерпан у resistance",
        ],
        "hard_ban": [
            "Force close — P0 violation, исключение только при риске liq",
        ],
    },
    ScenarioClass.SEVERE: {
        "context": "Тяжёлая просадка (-7..-12%). Внимательно следить за liq distance.",
        "watch": [
            "Distance to liq < 30% — критический threshold",
            "Margin coefficient — если падает быстро, готовься к force-action",
            "Funding extreme — может быть squeeze момент",
        ],
        "operator_options_confirmed": [
            "P-4 paused — обязательно",
            "Подготовь сценарии частичного closure ЕСЛИ liq distance < 20%",
        ],
        "hard_ban": [
            "Не закрывать pre-emptively — wait for actual liq risk signal",
        ],
    },
    ScenarioClass.CRITICAL: {
        "context": "Критическая просадка (-12..-20%). Значимый убыток если закрывать.",
        "watch": [
            "Distance to liq — главная метрика сейчас",
            "Crypto market overall — каскад идёт?",
            "Подкрепление маржи возможно?",
        ],
        "operator_options_confirmed": [
            "Подкрепить margin (если возможно) — releases liq buffer",
            "P-1 raise boundary до уровня выше текущего экстремума — даёт время",
        ],
        "hard_ban": [
            "Panic close — статистика прямо отрицательная",
        ],
    },
    ScenarioClass.URGENT_PROTECTION: {
        "context": "Distance to liq < 20% — РЕАЛЬНЫЙ риск принудительного закрытия биржей.",
        "watch": [
            "Liq price vs current price — точное расстояние",
            "Скорость движения цены — если impulse, минуты до liq",
        ],
        "operator_options_confirmed": [
            "Подкрепление margin — главный приоритет (releases buffer)",
            "Частичное закрытие 25-50% — если подкрепить нельзя, чтобы спасти остальное",
            "P-1 hard boundary stop — если можно остановить новые IN мгновенно",
        ],
        "hard_ban": [
            "Полное паническое закрытие при distance > 5% — wait for actual margin call",
        ],
    },
}


def _format_state_header(state: PositionStateSnapshot) -> str:
    icon = _SCENARIO_ICONS.get(state.scenario_class, "⚠️")
    label = _SCENARIO_LABELS_RU.get(state.scenario_class, state.scenario_class.value)
    ts = state.captured_at.strftime("%H:%M UTC")

    lines = [
        f"{icon} ПОЗИЦИЯ — наблюдение | {ts}",
        f"",
        f"Сценарий: {label}",
        f"Цена BTC: ${state.current_price:,.1f}",
        f"Нереализованный итог: {state.total_unrealized_usd:+,.0f} USD",
        f"Свободная маржа: ${state.free_margin_usd:,.0f} ({state.free_margin_pct:.1f}%)",
    ]

    if state.worst_bot:
        wb = state.worst_bot
        lines.append("")
        lines.append("Худший бот:")
        lines.append(
            f"  {wb.alias} | поз. {wb.position_btc:+.3f} BTC "
            f"| P&L {wb.unrealized_usd:+.0f}$ ({wb.unrealized_pct_deposit:+.1f}%)"
        )
        if wb.duration_in_dd_h > 0:
            lines.append(f"  Время в DD: {wb.duration_in_dd_h:.1f}h")
        lines.append(f"  До ликвидации: {wb.distance_to_liq_pct:.1f}%")

    if state.short_side.bot_count > 0:
        lines.append("")
        lines.append(
            f"SHORT total: {state.short_side.bot_count} ботов "
            f"| {state.short_side.total_position_btc:+.3f} BTC (inverse, COIN-M) "
            f"| {state.short_side.total_unrealized_usd:+,.0f} USD"
        )
    if state.long_side.bot_count > 0:
        # 2026-05-07: position_btc для LONG-linear — это USD-нотом, не BTC.
        # Tracker не различает units — баг в position_state. Здесь корректно
        # подписываем как 'USD' чтобы не вводить в заблуждение.
        lines.append(
            f"LONG total: {state.long_side.bot_count} ботов "
            f"| ~${state.long_side.total_position_btc:,.0f} (linear, USDT-M) "
            f"| {state.long_side.total_unrealized_usd:+,.0f} USD"
        )

    return "\n".join(lines)


def _format_playbook_block(state: PositionStateSnapshot) -> str:
    pb = _SCENARIO_PLAYBOOK.get(state.scenario_class)
    if not pb:
        return ""

    lines = []
    lines.append("📋 ЧТО ГОВОРИТ ПЛЕЙБУК (MASTER §16 + PLAYBOOK)")
    lines.append("")
    lines.append(f"Контекст: {pb['context']}")
    lines.append("")

    if pb.get("watch"):
        lines.append("👀 Что отслеживать:")
        for item in pb["watch"]:
            lines.append(f"  • {item}")
        lines.append("")

    if pb.get("operator_options_confirmed"):
        lines.append("✅ Подтверждённые опции (Confirmed playbook):")
        for item in pb["operator_options_confirmed"]:
            lines.append(f"  • {item}")
        lines.append("")

    if pb.get("hard_ban"):
        lines.append("⛔ HARD BAN (MASTER §16.4):")
        for item in pb["hard_ban"]:
            lines.append(f"  • {item}")

    return "\n".join(lines)


def _read_margin_override() -> dict | None:
    """Read operator margin from state_latest.json (TZ-MARGIN-COEFFICIENT-INPUT-WIRE)."""
    try:
        import json as _json
        from pathlib import Path as _Path
        p = _Path("docs/STATE/state_latest.json")
        if not p.exists():
            return None
        data = _json.loads(p.read_text(encoding="utf-8"))
        return data.get("margin")
    except Exception:
        return None


def _format_balance_block(state: PositionStateSnapshot) -> str:
    """Two-engine portfolio balance check (MASTER §16.2).

    Operator stratery: торгуем в обе стороны (LONG-USDT + SHORT-COIN-M).
    Если переизбыток в одной стороне — рекомендуем работать с другой
    как балансировкой (P-15 idea + Q-5 в OPERATOR_QUESTIONS).
    """
    short_btc = abs(state.short_side.total_position_btc)
    long_btc = state.long_side.total_position_btc  # для linear-LONG это USD-нотом
    short_unr = state.short_side.total_unrealized_usd
    long_unr = state.long_side.total_unrealized_usd

    # Проверка переизбытка SHORT (на 50%+ больше LONG в USD-эквиваленте)
    # short_btc × current_price = USD value of SHORT exposure
    # long_btc (linear) уже в USD
    short_usd_eq = short_btc * state.current_price if state.current_price > 0 else 0
    long_usd_eq = long_btc  # linear notional = USD

    lines = ["⚖️ БАЛАНС ДВУХ ДВИЖКОВ (MASTER §16.2)"]
    lines.append("")
    if short_usd_eq > 0:
        lines.append(f"SHORT exposure: ~${short_usd_eq:,.0f} ({short_btc:.3f} BTC × ${state.current_price:,.0f}) | uPnL {short_unr:+,.0f}$")
    if long_usd_eq > 0:
        lines.append(f"LONG exposure:  ~${long_usd_eq:,.0f} | uPnL {long_unr:+,.0f}$")

    if short_usd_eq > 0 and long_usd_eq > 0:
        ratio = short_usd_eq / long_usd_eq
        net_btc = long_usd_eq / state.current_price - short_btc if state.current_price > 0 else 0
        lines.append(f"SHORT/LONG ratio: {ratio:.2f}x | Net BTC exposure: {net_btc:+.3f}")

        if ratio > 1.5:
            lines.append("")
            lines.append("⚠️ ПЕРЕИЗБЫТОК SHORT (>1.5×). Идеи балансировки:")
            lines.append("  • Усилить LONG-движок (увеличить order_size / уменьшить gs)")
            lines.append("  • LONG-grid быстрее набирает на росте → снижает net SHORT exposure")
            lines.append("  • Q-5 в OPERATOR_QUESTIONS: 'SHORT мог сократить позицию пропорционально на откате'")
            lines.append("  • P-15 (DRAFT): на retracement SHORT закрывает часть в плюс/нулём → reentry с более высоких цен")
        elif ratio < 0.7:
            lines.append("")
            lines.append("⚠️ ПЕРЕИЗБЫТОК LONG (>1.4×). Идеи балансировки:")
            lines.append("  • Усилить SHORT-движок (если bull-тренд истощился)")
            lines.append("  • SHORT-grid currency cushion при росте")

    return "\n".join(lines)


def format_honest_advisory(state: PositionStateSnapshot) -> str:
    """Verbose (full playbook + balance) — kept for /playbook on-demand command.

    Live hourly worker should call format_compact_advisory() instead — it
    dedup'ит и сокращает до 5-7 строк когда метрики не сильно меняются.
    Operator feedback 2026-05-12: full message was 30 lines × 5/night = visual spam.
    """
    if not state.has_active_position:
        return ""
    if state.scenario_class == ScenarioClass.MONITORING:
        return ""

    parts = [
        _format_state_header(state),
    ]

    # Margin override (operator-supplied) — most authoritative.
    margin = _read_margin_override()
    if margin and margin.get("coefficient") is not None:
        age_min = margin.get("data_age_minutes", 0)
        coef = margin.get("coefficient")
        avail = margin.get("available_margin_usd")
        dist = margin.get("distance_to_liquidation_pct")
        parts.append("")
        parts.append(
            f"💰 Margin (operator /margin): coef={coef:.4f} | "
            f"available ${avail:,.0f} | dist_liq {dist:.1f}%"
        )
        if age_min > 360:  # > 6h
            parts.append(f"  ⚠️ {age_min/60:.1f}h old — обнови /margin")

    parts.extend([
        "",
        _format_playbook_block(state),
        "",
        _format_balance_block(state),
    ])
    return "\n".join(parts)


# ── Compact mode (2026-05-12, operator request to reduce spam) ────────────

_PREV_SNAPSHOT_PATH = Path("state/exit_advisor_prev_snapshot.json")


def _read_prev_snapshot() -> dict:
    try:
        if _PREV_SNAPSHOT_PATH.exists():
            return json.loads(_PREV_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_prev_snapshot(data: dict) -> None:
    try:
        _PREV_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PREV_SNAPSHOT_PATH.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _is_critical(state: PositionStateSnapshot) -> bool:
    """Critical conditions force a full alert with playbook.

    Operator feedback 2026-05-19: position info itself is not actionable
    (видим на BitMEX UI). Critical = только реальные emergencies где надо
    срочно делать что-то.
      - distance_to_liq <= 10% (margin call territory)
      - free_margin_pct < 70% (tight margin reserve)
    Убрано: DD >= 8h (для grid bot в боковике это норма, не emergency).
    """
    if state.worst_bot:
        if state.worst_bot.distance_to_liq_pct <= 10.0:
            return True
    if state.free_margin_pct < 70.0:
        return True
    return False


def _significant_change(state: PositionStateSnapshot, prev: dict) -> bool:
    """Skip duplicate alerts if nothing material changed since last hour.

    Operator feedback 2026-05-19: каждые 2h приходила POS-card с DD+2h —
    DD-age растёт линейно с временем, это не "изменение позиции". Убран
    DD-age trigger. uPnL threshold поднят $50 → $200 (за час $50 это шум
    для $1k+ позиции, $200 = заметное движение).
    """
    if not prev:
        return True
    # uPnL changed > $200 (raised from $50 — было слишком чувствительно)
    cur_upnl = state.total_unrealized_usd
    prev_upnl = prev.get("upnl", 0.0)
    if abs(cur_upnl - prev_upnl) > 200.0:
        return True
    # Distance to liq dropped ≥ 1% (real risk movement)
    cur_liq = state.worst_bot.distance_to_liq_pct if state.worst_bot else 100.0
    prev_liq = prev.get("liq_dist", 100.0)
    if prev_liq - cur_liq >= 1.0:
        return True
    # DD-age trigger removed — elapsed time != significant change.
    return False


def format_compact_advisory(state: PositionStateSnapshot) -> tuple[str, bool]:
    """Return (text, is_critical). Text is empty if no material change since last
    snapshot (caller should suppress). is_critical flag tells caller to route to
    PRIMARY channel (with 🔴) vs ROUTINE channel (with ⚪).

    Format (4-7 lines):
        ⚠️ POS @ HH:MM UTC | DD=Xh | liq=Y%
        BTC $price | uPnL ±$N (Δ vs 1h)
        SHORT N bots × pos | LONG N bots × $pos
        Net exp: -X BTC (SHORT-tilt Y×)
        ⚠ flags if any
    """
    if not state.has_active_position:
        return ("", False)
    if state.scenario_class == ScenarioClass.MONITORING:
        return ("", False)

    # Kill-switch: env EXIT_ADVISOR_POS_CARD_DISABLED=1 → suppress всё,
    # даже critical. Operator всё видит на BitMEX UI; cliff_monitor шлёт
    # margin alerts отдельно. /playbook на запрос — остаётся.
    import os as _os
    if _os.environ.get("EXIT_ADVISOR_POS_CARD_DISABLED", "0") == "1":
        return ("", False)

    prev = _read_prev_snapshot()
    critical = _is_critical(state)

    if not critical and not _significant_change(state, prev):
        # Stale — caller should suppress
        return ("", False)

    ts = state.captured_at.strftime("%H:%M UTC")
    wb = state.worst_bot
    dd_h = wb.duration_in_dd_h if wb else 0.0
    liq_dist = wb.distance_to_liq_pct if wb else 100.0

    upnl = state.total_unrealized_usd
    prev_upnl = prev.get("upnl")
    upnl_delta = ""
    if prev_upnl is not None:
        delta = upnl - prev_upnl
        if abs(delta) >= 10:
            upnl_delta = f" (Δ {delta:+,.0f}$)"

    lines = []
    flag = "🔴" if critical else "⚠️"
    lines.append(f"{flag} POS @ {ts} | DD={dd_h:.0f}h | liq={liq_dist:.1f}%")
    lines.append(
        f"BTC ${state.current_price:,.0f} | uPnL {upnl:+,.0f}${upnl_delta}"
    )

    s_btc = state.short_side.total_position_btc
    l_usd = state.long_side.total_position_btc  # for LONG-linear stored as USD
    pos_line = []
    if state.short_side.bot_count > 0:
        pos_line.append(
            f"SHORT {state.short_side.bot_count}b × {s_btc:+.2f}BTC ({state.short_side.total_unrealized_usd:+.0f}$)"
        )
    if state.long_side.bot_count > 0:
        pos_line.append(
            f"LONG {state.long_side.bot_count}b × ${l_usd:,.0f} ({state.long_side.total_unrealized_usd:+.0f}$)"
        )
    if pos_line:
        lines.append(" | ".join(pos_line))

    # Net exposure
    if state.short_side.bot_count and state.long_side.bot_count:
        net_btc = s_btc + (l_usd / state.current_price if state.current_price else 0)
        sl_ratio = (
            abs(s_btc * state.current_price) / max(l_usd, 1)
            if l_usd > 0 else float("inf")
        )
        sl_str = f"{sl_ratio:.1f}×" if sl_ratio != float("inf") else "∞"
        lines.append(f"Net: {net_btc:+.2f}BTC | SHORT-tilt {sl_str}")
        if sl_ratio > 1.5:
            lines.append("⚠ SHORT-перевес — рассмотреть балансировку")

    # Margin warning if critical
    margin = _read_margin_override()
    if margin and margin.get("distance_to_liquidation_pct") is not None:
        dist = margin["distance_to_liquidation_pct"]
        if dist <= 10:
            lines.append(f"💀 dist_liq {dist:.1f}% (operator margin)")

    # Quick pointer for full playbook
    if critical:
        lines.append("📋 /playbook — полный плейбук")

    text = "\n".join(lines)

    # Save snapshot for next-hour delta
    _write_prev_snapshot({
        "upnl": upnl,
        "dd_h": dd_h,
        "liq_dist": liq_dist,
        "ts": state.captured_at.isoformat(),
    })

    return (text, critical)
