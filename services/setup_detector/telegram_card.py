from __future__ import annotations

from .models import Setup, SetupType, setup_side

_LONG_ICON = "🟢"
_SHORT_ICON = "🔴"
_GRID_ICON = "⚙️"
_DEF_ICON = "⚠️"


def format_telegram_card(setup: Setup) -> str:
    side = setup_side(setup)
    if side in ("p15_long", "p15_short"):
        return _format_p15_card(setup, direction=side.split("_")[1].upper())
    if side == "long":
        return _format_trade_card(setup, direction="LONG", icon=_LONG_ICON)
    if side == "short":
        return _format_trade_card(setup, direction="SHORT", icon=_SHORT_ICON)
    if side == "grid":
        return _format_grid_card(setup)
    return _format_defensive_card(setup)


# ── P-15 stage cards (TZ: P-15 production wire 2026-05-09) ───────────────────

_P15_STAGE_ICON = {
    "OPEN":    "🎯",
    "HARVEST": "💰",
    "REENTRY": "🔄",
    "CLOSE":   "🚫",
}


def _basis_get(setup: Setup, label: str, default=None):
    for b in setup.basis:
        if b.label == label:
            return b.value
    return default


def _format_p15_card(setup: Setup, *, direction: str) -> str:
    """Renders the lifecycle card for a P-15 leg event.

    Stages: OPEN (entry trigger), HARVEST (close 50%), REENTRY (open new
    layer at K% offset), CLOSE (gate flip / dd_cap exit).
    """
    ts = setup.detected_at.strftime("%H:%M UTC")
    stage = str(_basis_get(setup, "stage", "?"))
    icon = _P15_STAGE_ICON.get(stage, "🔔")

    avg = float(_basis_get(setup, "avg_entry", 0) or 0)
    extreme = float(_basis_get(setup, "extreme", 0) or 0)
    layers = int(_basis_get(setup, "layers", 0) or 0)
    total_size = float(_basis_get(setup, "total_size_usd", 0) or 0)
    dd_pct = float(_basis_get(setup, "dd_pct", 0) or 0)
    unrealized = float(_basis_get(setup, "unrealized_usd", 0) or 0)
    R_pct = float(_basis_get(setup, "R_pct", 0.3) or 0.3)
    K_pct = float(_basis_get(setup, "K_pct", 1.0) or 1.0)

    lines = [
        f"{icon} P-15 {direction} {stage} — {setup.pair} | {ts}",
        "",
        f"💲 Текущая цена: ${setup.current_price:,.1f}",
    ]

    if stage == "OPEN":
        trigger = _basis_get(setup, "trigger", "")
        size_usd = _basis_get(setup, "size_usd", 0)
        lines += [
            f"📌 Триггер: {trigger}",
            "",
            f"🎬 ОТКРЫТЬ {direction} ${size_usd:,.0f}",
            f"   Entry:    ${setup.current_price:,.1f}",
            f"   Размер:   ${size_usd:,.0f}",
            f"   Слой #:   1",
            "",
            f"⚙️ ПАРАМЕТРЫ ЦИКЛА:",
            f"   R = {R_pct}%   (откат для harvest)",
            f"   K = {K_pct}%   (отступ переоткрытия)",
            f"   dd_cap = 3.0% (аварийный стоп)",
            "",
            f"🎯 ЧТО ЖДЁМ:",
            f"   - Цена обновляет {'high' if direction == 'LONG' else 'low'} (extreme tracking)",
            f"   - На откате R% от extreme → HARVEST 50% позиции",
            f"   - Затем REENTRY на K% {'выше' if direction == 'LONG' else 'ниже'} exit",
            "",
            f"⛔ ОТМЕНА:",
        ] + [f"   - {c}" for c in setup.cancel_conditions[:3]]

    elif stage == "HARVEST":
        exit_price = float(_basis_get(setup, "exit_price", 0) or 0)
        harvest_size = float(_basis_get(setup, "harvest_size_usd", 0) or 0)
        harvest_pnl = float(_basis_get(setup, "harvest_pnl_usd", 0) or 0)
        next_reentry = float(_basis_get(setup, "next_reentry_price", 0) or 0)
        lines += [
            f"📍 Avg entry: ${avg:,.1f}",
            f"📍 Extreme:   ${extreme:,.1f} (running {'high' if direction == 'LONG' else 'low'})",
            f"📍 Слой #:    {layers}",
            "",
            f"💰 ЗАКРЫТЬ 50% ПОЗИЦИИ",
            f"   Exit price:   ${exit_price:,.1f}",
            f"   Размер:       ${harvest_size:,.0f}",
            f"   PnL партии:   ${harvest_pnl:+,.2f}",
            "",
            f"🔄 СЛЕДУЮЩИЙ ШАГ — REENTRY:",
            f"   Откроется по: ${next_reentry:,.1f}",
            f"   (отступ K={K_pct}% от exit)",
            "",
            f"📊 Состояние позиции:",
            f"   Total size:   ${total_size:,.0f}",
            f"   Unrealized:   ${unrealized:+,.2f}",
            f"   Cum DD:       {dd_pct:.2f}%",
        ]

    elif stage == "REENTRY":
        reentry_price = float(_basis_get(setup, "reentry_price", 0) or 0)
        new_avg = float(_basis_get(setup, "new_avg_entry", 0) or 0)
        new_layer_size = float(_basis_get(setup, "new_layer_size_usd", 0) or 0)
        lines += [
            f"📍 Слой #:    {layers}  (после harvest)",
            "",
            f"🔄 ОТКРЫТЬ НОВЫЙ СЛОЙ",
            f"   Entry:        ${reentry_price:,.1f}",
            f"   Размер:       ${new_layer_size:,.0f}",
            f"   Новый avg:    ${new_avg:,.1f}",
            "",
            f"📊 Состояние позиции:",
            f"   Total size:   ${total_size:,.0f}",
            f"   Unrealized:   ${unrealized:+,.2f}",
            "",
            f"🎯 ЧТО ЖДЁМ ДАЛЬШЕ:",
            f"   - Цена обновляет {'high' if direction == 'LONG' else 'low'}",
            f"   - На откате R={R_pct}% → следующий HARVEST",
        ]

    elif stage == "CLOSE":
        reason = _basis_get(setup, "reason", "")
        close_price = float(_basis_get(setup, "close_price", 0) or 0)
        realized_pnl = float(_basis_get(setup, "realized_pnl_usd", 0) or 0)
        pnl_emoji = "✅" if realized_pnl > 0 else "❌"
        lines += [
            f"📍 Avg entry: ${avg:,.1f}",
            f"📍 Слоёв накоплено: {layers}",
            f"📍 Total size: ${total_size:,.0f}",
            "",
            f"🚫 ЗАКРЫТЬ ВСЮ ПОЗИЦИЮ",
            f"   Причина:      {reason}",
            f"   Close price:  ${close_price:,.1f}",
            f"   {pnl_emoji} Realized PnL: ${realized_pnl:+,.2f}",
            f"   Cum DD за цикл: {dd_pct:.2f}%",
            "",
            f"♻️ Цикл завершён. Бот вернётся в IDLE.",
            f"   Следующий OPEN — когда тренд-гейт снова сработает.",
        ]

    return "\n".join(lines)


def _format_trade_card(setup: Setup, *, direction: str, icon: str) -> str:
    from services.common.humanize import humanize_setup_type, fmt_price_compact
    ts = setup.detected_at.strftime("%H:%M UTC")
    basis_lines = "\n".join(f"• {b.label}" for b in setup.basis[:5])
    cancel_lines = "\n".join(f"• {c}" for c in setup.cancel_conditions[:3])

    entry_str = f"${fmt_price_compact(setup.entry_price)}" if setup.entry_price else "—"
    stop_str = f"${fmt_price_compact(setup.stop_price)}" if setup.stop_price else "—"
    tp1_str = f"${fmt_price_compact(setup.tp1_price)}" if setup.tp1_price else "—"
    tp2_str = f"${fmt_price_compact(setup.tp2_price)}" if setup.tp2_price else "—"
    rr_str = f"1:{setup.risk_reward:.1f}" if setup.risk_reward else "—"
    setup_ru = humanize_setup_type(setup.setup_type.value)

    return (
        f"{icon} {direction} — {setup_ru}\n"
        f"{setup.pair} | {ts}\n"
        f"\n"
        f"Цена ${fmt_price_compact(setup.current_price)}\n"
        f"Сила: {setup.strength}/10 | Уверенность: {setup.confidence_pct:.0f}%\n"
        f"\n"
        f"ВХОД: {entry_str} (limit)\n"
        f"СТОП: {stop_str}\n"
        f"ЦЕЛИ: TP1 {tp1_str} | TP2 {tp2_str}\n"
        f"RR: {rr_str}\n"
        f"\n"
        f"ОСНОВАНИЕ:\n{basis_lines}\n"
        f"\n"
        f"ОТМЕНА:\n{cancel_lines}\n"
        f"\n"
        f"Портфель: {setup.portfolio_impact_note}\n"
        f"Размер: {setup.recommended_size_btc:.2f} BTC | Окно: {setup.window_minutes} мин"
    )


def format_actionable_card(setup: Setup, edge: dict, *, countertrend: bool = False) -> str:
    """«ОТКРОЙ СЕЙЧАС» — императивная карточка валид-эджа со статистикой inline.

    2026-06-21: оператор хотел видеть проактивные входы «вот сейчас можно
    открыть такую сделку» с понятными RR/PF, а не только жди/закрывай.
    edge = выхлоп edge_stats.edge_for() (pf/wr/rr/exp/n + regime_pf)."""
    from services.common.humanize import humanize_setup_type, fmt_price_compact
    direction = "SHORT" if setup.setup_type.value.startswith("short_") else "LONG"
    ts = setup.detected_at.strftime("%H:%M UTC")
    setup_ru = humanize_setup_type(setup.setup_type.value)

    entry = f"${fmt_price_compact(setup.entry_price)}" if setup.entry_price else f"${fmt_price_compact(setup.current_price)}"
    stop = f"${fmt_price_compact(setup.stop_price)}" if setup.stop_price else "—"
    tp1 = f"${fmt_price_compact(setup.tp1_price)}" if setup.tp1_price else "—"
    tp2 = f"${fmt_price_compact(setup.tp2_price)}" if setup.tp2_price else "—"
    rr = f"1:{setup.risk_reward:.1f}" if setup.risk_reward else f"1:{edge.get('rr', 0):.1f}"

    icon = "🟢" if direction == "LONG" else "🔴"
    reg = edge.get("regime") or "?"
    if edge.get("regime_known"):
        edge_line = (f"📊 PF(режим {reg}) {edge['regime_pf']:.1f} · WR {edge.get('regime_wr', edge['wr'])}%"
                     f" · всего PF {edge['pf']:.2f}/RR {edge['rr']:.1f}/ожид +{edge['exp']:.2f}% (n={edge['n']})")
    else:
        edge_line = (f"📊 PF {edge['pf']:.2f} · WR {edge['wr']}% · RR {edge['rr']:.1f}"
                     f" · ожид +{edge['exp']:.2f}%/сделку (n={edge['n']})")

    cancel = "; ".join(setup.cancel_conditions[:2]) if setup.cancel_conditions else "стоп"
    lines = [
        f"🎯 ОТКРОЙ {icon} {direction} · {setup_ru} · {setup.pair}  {ts}",
        f"ВХОД {entry} (limit) · СТОП {stop} · TP1 {tp1} / TP2 {tp2} · RR {rr}",
        edge_line,
        f"размер {setup.recommended_size_btc:.2f} BTC · окно {setup.window_minutes}мин · уверенность {setup.confidence_pct:.0f}%",
    ]
    if countertrend:
        lines.append("⚠️ КОНТРТРЕНД: против BTC 4h-структуры — половинь размер или жди подтверждения")
    lines.append(f"отмена: {cancel}")
    return "\n".join(lines)


def _format_grid_card(setup: Setup) -> str:
    ts = setup.detected_at.strftime("%H:%M UTC")
    basis_lines = "\n".join(f"• {b.label}" for b in setup.basis[:5])
    bots_str = ", ".join(setup.grid_target_bots) if setup.grid_target_bots else "—"
    action_str = setup.grid_action or "—"

    from services.common.humanize import fmt_price_compact
    return (
        f"{_GRID_ICON} GRID ACTION — {setup.pair} | {ts}\n"
        f"\n"
        f"Цена ${fmt_price_compact(setup.current_price)}\n"
        f"Сила: {setup.strength}/10 | Уверенность: {setup.confidence_pct:.0f}%\n"
        f"\n"
        f"Действие: {action_str}\n"
        f"Боты: {bots_str}\n"
        f"\n"
        f"ОСНОВАНИЕ:\n{basis_lines}\n"
        f"\n"
        f"Окно: {setup.window_minutes} мин"
    )


def _format_defensive_card(setup: Setup) -> str:
    ts = setup.detected_at.strftime("%H:%M UTC")
    basis_lines = "\n".join(f"• {b.label}" for b in setup.basis[:5])
    cancel_lines = "\n".join(f"• {c}" for c in setup.cancel_conditions[:3])

    from services.common.humanize import fmt_price_compact
    return (
        f"{_DEF_ICON} ЗАЩИТНЫЙ АЛЕРТ — {setup.pair} | {ts}\n"
        f"\n"
        f"Цена ${fmt_price_compact(setup.current_price)}\n"
        f"Сила: {setup.strength}/10\n"
        f"\n"
        f"СИГНАЛ: {setup.portfolio_impact_note}\n"
        f"\n"
        f"ОСНОВАНИЕ:\n{basis_lines}\n"
        f"\n"
        f"ОТМЕНА:\n{cancel_lines}"
    )


def format_outcome_card(
    setup: Setup,
    new_status: str,
    current_price: float,
    hypothetical_pnl_usd: float | None,
    time_to_outcome_min: int | None,
) -> str:
    side = setup_side(setup)
    if new_status in ("tp1_hit", "tp2_hit"):
        icon = "✅"
        label = "TP1 HIT" if new_status == "tp1_hit" else "TP2 HIT"
    elif new_status == "stop_hit":
        icon = "❌"
        label = "STOP HIT"
    elif new_status == "expired":
        icon = "⏱"
        label = "EXPIRED"
    else:
        icon = "ℹ️"
        label = new_status.upper().replace("_", " ")

    direction = side.upper()
    pnl_str = f"Hypothetical: {hypothetical_pnl_usd:+.0f} USD" if hypothetical_pnl_usd is not None else ""
    time_str = f"Время: {time_to_outcome_min} мин" if time_to_outcome_min is not None else ""

    entry_str = f"${setup.entry_price:,.1f}" if setup.entry_price else "—"

    lines = [
        f"{icon} {label} — {direction} SETUP {setup.pair}",
        f"Entry: {entry_str} → Текущая: ${current_price:,.1f}",
    ]
    if pnl_str:
        lines.append(pnl_str)
    if time_str:
        lines.append(time_str)
    lines.append(f"Setup ID: {setup.setup_id}")

    return "\n".join(lines)
