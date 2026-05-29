"""TV webhook signal dispatcher.

Routes incoming signals by `signal_type`, applies per-type cooldowns,
formats TG messages, stores to state/tv_typed_signals.jsonl, and
optionally notifies operator immediately via Telegram.

Thread-safe: called from ThreadingHTTPServer handler threads.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .signal_types import (
    COOLDOWN_SEC, DEFAULT_COOLDOWN_SEC, NOTIFY_IMMEDIATELY,
    SIGNAL_EMOJI, SIGNAL_LABEL,
    EXHAUSTION_TOP, EXHAUSTION_BOTTOM,
    SQUEEZE_UP, SQUEEZE_DOWN,
    SPX_DROP, SPX_PUMP,
    BOS_BULLISH, BOS_BEARISH,
    LIQ_CASCADE, VOL_REJECTION, RANGE_BOUNDARY,
    CVD_DIVERGENCE,
)
from .tg_notify import send_tv_signal

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_TYPED_SIGNALS_PATH = _ROOT / "state" / "tv_typed_signals.jsonl"

_lock = threading.Lock()
_last_fired: dict[str, float] = {}   # signal_type → last fire unix ts


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_exhaustion(sig_type: str, p: dict) -> str:
    emoji = SIGNAL_EMOJI.get(sig_type, "❗")
    label = SIGNAL_LABEL.get(sig_type, sig_type)
    price = p.get("price", "?")
    tf = p.get("timeframe", "?")
    ticker = p.get("ticker", "BTCUSDT")
    strength = int(p.get("strength", 0))
    details = str(p.get("details", "")).replace(",", " · ")
    bar = "█" * strength + "░" * (3 - min(strength, 3))

    lines = [
        f"{emoji} {label}",
        f"{ticker}  ${price}  [{tf}m]",
        f"Сила: {bar} {strength}/3",
    ]
    if details:
        lines.append(f"▸ {details}")
    if sig_type == EXHAUSTION_TOP:
        lines.append("→ Вероятен разворот ВНИЗ")
    else:
        lines.append("→ Вероятен разворот ВВЕРХ")
    return "\n".join(lines)


def _fmt_squeeze(sig_type: str, p: dict) -> str:
    emoji = SIGNAL_EMOJI.get(sig_type, "⚡")
    label = SIGNAL_LABEL.get(sig_type, sig_type)
    price = p.get("price", "?")
    tf = p.get("timeframe", "?")
    ticker = p.get("ticker", "BTCUSDT")
    bars = p.get("squeeze_bars", "?")
    lines = [
        f"{emoji} {label}",
        f"{ticker}  ${price}  [{tf}m]",
        f"Сжатие {bars} баров → ПРОБОЙ",
    ]
    if sig_type == SQUEEZE_UP:
        lines.append("→ Зарождение лонг-движения")
    else:
        lines.append("→ Зарождение шорт-движения")
    return "\n".join(lines)


def _fmt_spx(sig_type: str, p: dict) -> str:
    emoji = SIGNAL_EMOJI.get(sig_type, "🌐")
    spx_price = p.get("spx_price", "?")
    chg = p.get("change_pct", "?")
    tf = p.get("timeframe", "15")
    corr = p.get("btc_corr", None)
    sign = "+" if str(chg).startswith("-") is False else ""
    lines = [
        f"{emoji} SPX {sign}{chg}% за {tf}m",
        f"ES=F  {spx_price}",
    ]
    if corr:
        lines.append(f"BTC корреляция: {corr}")
    if sig_type == SPX_DROP:
        lines.append("→ Давление на крипту · short-боты в зоне")
    else:
        lines.append("→ Риск-аппетит растёт · BTC может пойти вверх")
    return "\n".join(lines)


def _fmt_bos(sig_type: str, p: dict) -> str:
    emoji = SIGNAL_EMOJI.get(sig_type, "📈")
    label = SIGNAL_LABEL.get(sig_type, sig_type)
    price = p.get("price", "?")
    broken_level = p.get("broken_level", "?")
    ticker = p.get("ticker", "BTCUSDT")
    tf = p.get("timeframe", "60")
    lines = [
        f"{emoji} {label}",
        f"{ticker}  ${price}  [{tf}m]",
        f"Пробит уровень: ${broken_level}",
    ]
    if sig_type == BOS_BULLISH:
        lines.append("→ Структура меняется вверх · short-боты под риском")
    else:
        lines.append("→ Структура меняется вниз · short-боты в комфорте")
    return "\n".join(lines)


def _fmt_liq_cascade(p: dict) -> str:
    price = p.get("price", "?")
    side = p.get("liq_side", p.get("direction", "?"))
    volume_m = p.get("liq_volume_m", None)
    tf = p.get("timeframe", "1")
    lines = [
        f"💥 КАСКАД ЛИКВИДАЦИЙ [{tf}m]",
        f"BTCUSDT  ${price}",
        f"Ликвидирована сторона: {str(side).upper()}",
    ]
    if volume_m:
        lines.append(f"Объём: ${volume_m}M")
    lines.append("→ Дополнительный импульс в направлении каскада вероятен")
    return "\n".join(lines)


def _fmt_vol_rejection(p: dict) -> str:
    price = p.get("price", "?")
    level = p.get("level_type", "key level")
    vol_ratio = p.get("vol_ratio", None)
    tf = p.get("timeframe", "15")
    lines = [
        f"📊 ОБЪЁМНОЕ ОТБИТИЕ [{tf}m]",
        f"BTCUSDT  ${price}  на {level}",
    ]
    if vol_ratio:
        lines.append(f"Volume ×{vol_ratio} от нормы")
    lines.append("→ Уровень держится")
    return "\n".join(lines)


def _fmt_range_boundary(p: dict) -> str:
    price = p.get("price", "?")
    side = p.get("boundary_side", "?")
    pct_from_edge = p.get("pct_from_edge", None)
    lines = [
        f"📐 ГРАНИЦА ДИАПАЗОНА",
        f"BTCUSDT  ${price}  · {side} граница недели",
    ]
    if pct_from_edge:
        lines.append(f"Отступ от края: {pct_from_edge}%")
    lines.append("→ Потенциальная точка входа Range Hunter")
    return "\n".join(lines)


def _fmt_generic(sig_type: str, p: dict) -> str:
    emoji = SIGNAL_EMOJI.get(sig_type, "❗")
    label = SIGNAL_LABEL.get(sig_type, sig_type)
    price = p.get("price", "?")
    ticker = p.get("ticker", "BTCUSDT")
    tf = p.get("timeframe", "?")
    return f"{emoji} {label}\n{ticker}  ${price}  [{tf}m]"


def _format_message(sig_type: str, payload: dict) -> str:
    try:
        if sig_type in (EXHAUSTION_TOP, EXHAUSTION_BOTTOM):
            return _fmt_exhaustion(sig_type, payload)
        if sig_type in (SQUEEZE_UP, SQUEEZE_DOWN):
            return _fmt_squeeze(sig_type, payload)
        if sig_type in (SPX_DROP, SPX_PUMP):
            return _fmt_spx(sig_type, payload)
        if sig_type in (BOS_BULLISH, BOS_BEARISH):
            return _fmt_bos(sig_type, payload)
        if sig_type == LIQ_CASCADE:
            return _fmt_liq_cascade(payload)
        if sig_type == VOL_REJECTION:
            return _fmt_vol_rejection(payload)
        if sig_type == RANGE_BOUNDARY:
            return _fmt_range_boundary(payload)
        return _fmt_generic(sig_type, payload)
    except Exception:
        logger.exception("tv_dispatcher.format_failed sig_type=%s", sig_type)
        return f"TV signal: {sig_type}"


# ── Storage ───────────────────────────────────────────────────────────────────

def _store(record: dict) -> None:
    try:
        _TYPED_SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _TYPED_SIGNALS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        logger.exception("tv_dispatcher.store_failed")


# ── Main entry point ──────────────────────────────────────────────────────────

# 2026-05-29: paper-track EVERY typed TV signal so each type's edge is measured
# (source=tv_<type>, resolved per-symbol). Notify is then gated by the PnL-aware
# paper_wr_gate, so a TV type that proves to lose stops spamming the operator.
_TV_INHERENT_SIDE: dict[str, str] = {
    EXHAUSTION_TOP: "SHORT", EXHAUSTION_BOTTOM: "LONG",
    SQUEEZE_UP: "LONG", SQUEEZE_DOWN: "SHORT",
    BOS_BULLISH: "LONG", BOS_BEARISH: "SHORT",
    SPX_DROP: "SHORT", SPX_PUMP: "LONG",
}
# Uniform paper params so we measure the SIGNAL's edge, not param tuning.
_TV_STOP_PCT, _TV_TP_PCT, _TV_HOLD_H = -0.75, 1.5, 8


def _tv_side(sig_type: str, payload: dict) -> str | None:
    """Resolve LONG/SHORT for a TV signal. Prefer explicit direction, else
    the type's inherent bias, else liquidation/boundary side."""
    d = str(payload.get("direction") or "").lower()
    if d in ("bullish", "long", "up"):
        return "LONG"
    if d in ("bearish", "short", "down"):
        return "SHORT"
    if sig_type in _TV_INHERENT_SIDE:
        return _TV_INHERENT_SIDE[sig_type]
    liq = str(payload.get("liq_side") or "").upper()
    if liq == "SHORTS":   # shorts liquidated → squeeze up
        return "LONG"
    if liq == "LONGS":
        return "SHORT"
    b = str(payload.get("boundary_side") or "").lower()
    if b in ("upper", "top"):
        return "SHORT"
    if b in ("lower", "bottom"):
        return "LONG"
    return None


def _tv_symbol(payload: dict) -> str:
    t = str(payload.get("ticker") or "BTCUSDT").upper()
    return t.split(".")[0].replace("PERP", "").strip() or "BTCUSDT"


def _paper_track_tv(sig_type: str, payload: dict, now_dt) -> None:
    """Record a paper trade for this TV signal (best-effort, never raises)."""
    try:
        price = payload.get("price")
        side = _tv_side(sig_type, payload)
        if price is None or side is None:
            return
        from services.paper_signal_tracker.journal import record_paper_signal
        symbol = _tv_symbol(payload)
        tf = str(payload.get("timeframe") or "")
        record_paper_signal(
            source=f"tv_{sig_type}", side=side, entry=float(price),
            stop_pct=_TV_STOP_PCT, tp_pct=_TV_TP_PCT, hold_h=_TV_HOLD_H,
            symbol=symbol, context=f"{symbol}_{tf}", now=now_dt,
        )
    except Exception:
        logger.exception("tv_dispatcher.paper_track_failed sig=%s", sig_type)


def dispatch(payload: dict, ingest_record: dict) -> None:
    """Called from webhook handler after the raw alert is stored.

    payload      — parsed JSON body from Pine script
    ingest_record — the already-stored raw record (has ingest_ts, remote_addr…)
    """
    sig_type: str = str(payload.get("signal_type") or payload.get("indicator") or "unknown")
    now = time.monotonic()

    with _lock:
        last = _last_fired.get(sig_type, 0.0)
        cooldown = COOLDOWN_SEC.get(sig_type, DEFAULT_COOLDOWN_SEC)
        if now - last < cooldown:
            elapsed = int(now - last)
            logger.info(
                "tv_dispatcher.deduped sig=%s elapsed=%ds cooldown=%ds",
                sig_type, elapsed, cooldown,
            )
            return
        _last_fired[sig_type] = now

    now_dt = datetime.now(timezone.utc)
    typed_record = {
        "ts": now_dt.isoformat(timespec="seconds"),
        "signal_type": sig_type,
        "payload": payload,
        "ingest_ts": ingest_record.get("ingest_ts", ""),
    }
    _store(typed_record)

    # Paper-track EVERY typed signal (incl. CVD & no-notify) so its edge is measured.
    _paper_track_tv(sig_type, payload, now_dt)

    if sig_type not in NOTIFY_IMMEDIATELY and sig_type != CVD_DIVERGENCE:
        logger.info("tv_dispatcher.stored_no_notify sig=%s", sig_type)
        return

    if sig_type == CVD_DIVERGENCE:
        logger.debug("tv_dispatcher.cvd_legacy_skipped")
        return

    # PnL-aware gate: suppress TG notify if this TV type's paper edge has decayed
    # (WR<40% or PF<0.9 over rolling window). Until ~20 outcomes accrue → allow.
    side = _tv_side(sig_type, payload)
    if side is not None:
        try:
            from services.common.paper_wr_gate import should_emit
            ok, why = should_emit(f"tv_{sig_type}", side)
        except Exception:
            ok, why = True, "gate_unavailable"
        if not ok:
            logger.info("tv_dispatcher.suppressed_wr_gate sig=%s %s", sig_type, why)
            return

    text = _format_message(sig_type, payload)
    logger.info("tv_dispatcher.notify sig=%s", sig_type)
    send_tv_signal(text)
