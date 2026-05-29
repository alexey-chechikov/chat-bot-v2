"""Live cascade alert loop. См. package __init__ для контекста."""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
LIQ_CSV = ROOT / "market_live" / "liquidations.csv"
DEDUP_PATH = ROOT / "state" / "cascade_alert_dedup.json"

POLL_INTERVAL_SEC = 60
WINDOW_MINUTES = 5
THRESHOLD_BTC = 5.0  # main threshold (high-confidence edge)
THRESHOLD_BTC_MEDIUM = 2.0  # medium threshold (separate alert with weaker edge)
THRESHOLD_BTC_MEGA = 10.0   # mega-spike: 10+ BTC in 1 min — rare reversal indicator
MEGA_WINDOW_MINUTES = 1    # tight window for mega tier
DEDUP_COOLDOWN_SEC = 1800  # 30 min between alerts per side
MEGA_DEDUP_COOLDOWN_SEC = 3600  # 1h cooldown for rare mega events

# 2026-05-29 regime gate (docs/STRATEGIES/CASCADE_REGIME_AUDIT.md +
# CASCADE_SHORT_OPTIMIZE.md): liquidation-cascade follows DIE in strong trends.
# ADX>=25 cascades = −$61 / PF 0.78 (n=38); ADX<25 = +$157 / PF 1.7. Suppress
# emission when the 1h ADX says we are in a strong trend.
ADX_TREND_CAP = 25.0
_adx_cache: dict = {"ts": 0.0, "val": 0.0}
_ADX_CACHE_TTL = 300.0


def _current_adx_1h() -> float:
    """Cached Wilder ADX on BTC 1h. Returns 0.0 (fail-open) on any error."""
    now_s = time.time()
    if now_s - _adx_cache["ts"] < _ADX_CACHE_TTL:
        return _adx_cache["val"]
    val = 0.0
    try:
        from core.data_loader import load_klines
        from core.orchestrator.regime_classifier import calc_adx
        df = load_klines(symbol="BTCUSDT", timeframe="1h", limit=60)
        candles = [{"high": float(h), "low": float(l), "close": float(c)}
                   for h, l, c in zip(df["high"], df["low"], df["close"])]
        val, _ = calc_adx(candles)
    except Exception:
        logger.exception("cascade_alert.adx_compute_failed")
        val = 0.0
    _adx_cache.update(ts=now_s, val=float(val))
    return float(val)

# Predicted +12h % move (from EDGE_TEXT stats). Used by accuracy_tracker.
PREDICTED_PCT_12H = {
    ("long", 5.0): 1.14,
    ("long", 2.0): 0.68,
    ("long", 10.0): 2.0,   # rough estimate for mega
    ("short", 5.0): 0.29,
    ("short", 2.0): 1.06,
    ("short", 10.0): -2.0,  # mega short = expected drop
}

# Backtest results (POST_LIQUIDATION_CASCADE_2026-05-07.md, n=103/102)
# entry_plan: signed % offsets from last_price. None = no concrete plan (weak/asymmetric edge).
EDGE_TEXT = {
    ("long", 5.0): {
        "title": "⚡ КАСКАД LONG-ликвидаций (>=5 BTC за 5 мин)",
        "stats": "Исторически (n=103, фев-июнь 2024):\n"
                 "  +4ч: 67% случаев цена выше, средний +0.46%\n"
                 "  +12ч: 73% случаев выше, средний +1.14%\n"
                 "  +24ч: 64%, средний +1.50%",
        "play": "СЕТАП: BUY на стабилизации после каскада\n"
                "EV после комиссий: ~+0.5% за сделку",
        "entry_plan": {"dir": "LONG", "tp1_pct": +0.46, "tp2_pct": +1.14, "stop_pct": -0.50, "size_usd": 5000},
    },
    ("long", 2.0): {
        "title": "⚡ Каскад LONG-ликвидаций (>=2 BTC, среднее)",
        "stats": "Исторически (n=297):\n"
                 "  +12ч: 63% случаев выше, средний +0.68%",
        "play": "Слабее основного сетапа — рассматривай как контекст.",
        "entry_plan": {"dir": "LONG", "tp1_pct": +0.35, "tp2_pct": +0.68, "stop_pct": -0.50, "size_usd": 2500, "note": "weak edge — половинный размер"},
    },
    ("short", 5.0): {
        "title": "⚡ КАСКАД SHORT-ликвидаций (>=5 BTC за 5 мин)",
        "stats": "Исторически (n=102):\n"
                 "  +24ч: 61% случаев выше, средний +1.02%\n"
                 "  +12ч: 57%, средний +0.29% (слабее)",
        "play": "Тренд продолжается вверх обычно.\n"
                "Если есть SHORT-позиция — НЕ агрессивно докидывать.\n"
                "Sell pressure высокая, но реверс маловероятен.",
        "entry_plan": None,
    },
    ("short", 2.0): {
        "title": "⚡ Каскад SHORT-ликвидаций (>=2 BTC, среднее)",
        "stats": "Исторически (n=296):\n"
                 "  +24ч: 61% выше, средний +1.06%",
        "play": "Контекст для оценки давления на шортов.",
        "entry_plan": None,
    },
    ("long", 10.0): {
        "title": "🌋 МЕГА-СПАЙК LONG-ликвидаций (>=10 BTC за 1 мин)",
        "stats": "Очень редкое событие — обычно signal реверса вверх.\n"
                 "Таких спайков ~5-10 в год, корреляция с low в 6-12ч высокая.",
        "play": "СЕТАП: следить за стабилизацией ниже current\n"
                "Через 6-12ч обычно отскок 1.5-3%\n"
                "БУДЬ ОСТОРОЖЕН — может быть продолжение каскада",
        "entry_plan": {"dir": "LONG", "tp1_pct": +1.00, "tp2_pct": +2.50, "stop_pct": -0.80, "size_usd": 3000, "note": "после стабилизации (2-3 свечи без новых ликвидаций)"},
    },
    ("short", 10.0): {
        "title": "🌋 МЕГА-СПАЙК SHORT-ликвидаций (>=10 BTC за 1 мин)",
        "stats": "Очень редкое — local high индикатор.\n"
                 "Часто перед коррекцией 2-5%.",
        "play": "СЕТАП: SHORT с tight stop на стабилизации",
        "entry_plan": {"dir": "SHORT", "tp1_pct": -1.00, "tp2_pct": -2.00, "stop_pct": +0.80, "size_usd": 3000, "note": "после стабилизации (2-3 свечи без новых ликвидаций)"},
    },
}


# Inverted plays для long-cascade когда edge drift подтверждён.
# В 2024 long-cascade был bounce up edge. В 2026 инвертировался: 65% pct_down
# 4h на n=20 свежих событий (cascade_backtest_combined.json).
# Когда edge_drift_guard.is_drifted("long", thr) == True, не подавляем сигнал
# целиком — наоборот, шлём с инвертированным SHORT направлением.
INVERTED_PLAYS = {
    ("long", 5.0): {
        "title": "🔄 LONG-cascade DRIFTED → INVERTED SHORT setup (>=5 BTC за 5 мин)",
        "stats": "ИНВЕРСИЯ от 2024 bull regime (combined backtest 2024+2026):\n"
                 "  2024 (n=103): 73% pct_up 4h, +0.91% — bounce edge\n"
                 "  2026 (n=20):  35% pct_up 4h = 65% pct_DOWN, -0.17% mean\n"
                 "  12h: 25% pct_up, -0.58% mean — drift подтверждён",
        "play": "СЕТАП: SHORT на стабилизации (2026 regime continuation вниз).\n"
                "⚠️ Малая выборка (n=20) — размер половинный.",
        "entry_plan": {"dir": "SHORT", "tp1_pct": -0.40, "tp2_pct": -0.78, "stop_pct": +0.40,
                        "size_usd": 2500,
                        "note": "Half-size до n>=40. Inverted edge свежий — мониторим WR."},
    },
    # 2BTC INVERTED ("long", 2.0) REMOVED 2026-05-19 — re-sweep n=387:
    # long_2btc inverted 4h DOWN 51.2%, 24h DOWN 56.1%, mean inverted +0.091%
    # → -EV after BitMEX 0.15% taker RT (-0.06%/trade). Шум, не торгуем.
    # 2BTC alerts всё ещё могут залогироваться как drift-warning через fallback
    # path в _format_alert, но без entry_plan.
    # Mega-long INVERTED 2026-05-19: re-sweep n=68 показал 4h_up 31.8% (= 68.2%
    # DOWN-WR, mean −0.232%), 24h_up 25% (= 75% DOWN-WR, mean −0.950%). Жирнейший
    # inverted edge на mega-long-cascade — хорошо торговать SHORT с 24h hold.
    ("long", 10.0): {
        "title": "🌋🔄 МЕГА-LONG-cascade DRIFTED → INVERTED SHORT (24h hold)",
        "stats": "Re-swept 2026-05-19 (cascade_backtest_combined, n=68):\n"
                 "  4h: 32% up = 68% DOWN, mean −0.232%\n"
                 "  24h: 25% up = 75% DOWN, mean −0.950%\n"
                 "  Сильнейшая инверсия из всех cascade-вариантов.",
        "play": "СЕТАП: SHORT на стабилизации (2-3 свечи без новых ликвидаций).\n"
                "Hold 24h — там edge максимален. Можно частично закрывать на 4h.",
        "entry_plan": {"dir": "SHORT", "tp1_pct": -0.50, "tp2_pct": -1.00, "stop_pct": +0.60,
                        "size_usd": 4000,
                        "note": "Strong inverted edge n=68. 24h hold. R:R 1:1.67."},
    },
    # SHORT-side INVERTED 2026-05-19: live edge_drift_guard показал short_24h
    # accuracy 37.2% n=43 — т.е. DOWN-WR 62.8%. Old "continuation up" play
    # выдохся; вместо него — SHORT fade с 24h hold.
    ("short", 5.0): {
        "title": "🔄 SHORT-cascade DRIFTED → INVERTED SHORT fade (>=5 BTC за 5 мин)",
        "stats": "ИНВЕРСИЯ vs 2024:\n"
                 "  2024 hist: 70% pct_up 4h — continuation edge\n"
                 "  2026 live (cascade_edge_drift, n=43): 37.2% pct_up 24h = 62.8% pct_DOWN\n"
                 "  Цена SHORT-cascade'a — squeeze вверх; 24h позже чаще откат вниз.",
        "play": "СЕТАП: SHORT на стабилизации после squeeze (2-3 свечи без новых ликвидаций).\n"
                "Hold 24h. Half-size до накопления собственных fills.",
        "entry_plan": {"dir": "SHORT", "tp1_pct": -0.40, "tp2_pct": -0.80, "stop_pct": +0.45,
                        "size_usd": 2500,
                        "note": "Half-size. 24h hold (4h/12h slabej edge). Inverted edge — мониторим WR."},
    },
    # ("short", 2.0) INVERTED removed 2026-05-19 — same reason as long_2btc:
    # mid-tier edge не оправдывает fees, treat as noise.
}


# Weak-conviction noise filter (2026-05-19):
# 2BTC тир alerts суппрессируются если qty < threshold × 1.3 ИЛИ single exchange
# (один источник). Конкретный кейс который операторе показал: 2.32 BTC OKX-only =
# чистый noise, такие алерты больше не приходят.
WEAK_CONVICTION_MIN_QTY_RATIO = 1.3
WEAK_CONVICTION_EXCHANGE_MIN_QTY = 0.3
SUPPRESSED_LOG_PATH = ROOT / "state" / "cascade_alert_suppressed.jsonl"


def _is_weak_conviction(threshold: float, qty: float, by_exchange: dict) -> tuple[bool, str]:
    """Returns (suppress, reason). Only the 2BTC tier is filtered — 5BTC + mega always fire."""
    if threshold >= THRESHOLD_BTC:  # 5.0 BTC or higher — always fire
        return False, ""
    reasons: list[str] = []
    if qty < threshold * WEAK_CONVICTION_MIN_QTY_RATIO:
        reasons.append(f"qty {qty:.2f}/{threshold:.1f} below ×{WEAK_CONVICTION_MIN_QTY_RATIO}")
    contributing_exchanges = 0
    for _exch, sides in (by_exchange or {}).items():
        side_max = max(sides.get("long", 0.0), sides.get("short", 0.0))
        if side_max >= WEAK_CONVICTION_EXCHANGE_MIN_QTY:
            contributing_exchanges += 1
    if contributing_exchanges < 2:
        reasons.append(f"single_exchange ({contributing_exchanges} contributing)")
    if reasons:
        return True, "; ".join(reasons)
    return False, ""


def _log_suppressed(side: str, threshold: float, qty: float, reason: str,
                     by_exchange: dict, now: datetime) -> None:
    try:
        SUPPRESSED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": now.isoformat(timespec="seconds"),
            "side": side,
            "threshold_btc": threshold,
            "qty_btc": round(qty, 4),
            "reason": reason,
            "by_exchange": {e: round(s.get(side, 0.0), 3) for e, s in (by_exchange or {}).items()},
        }
        with SUPPRESSED_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("cascade_alert.suppressed_log_failed")


def _format_entry_plan(plan: dict | None, last_price: float | None) -> list[str]:
    """Build concrete entry/SL/TP block from plan + live price. Empty list if not applicable."""
    if not plan or not last_price or last_price <= 0:
        return []
    direction = plan["dir"]
    tp1 = last_price * (1 + plan["tp1_pct"] / 100)
    tp2 = last_price * (1 + plan["tp2_pct"] / 100)
    stop = last_price * (1 + plan["stop_pct"] / 100)
    risk = abs(plan["stop_pct"])
    rr1 = abs(plan["tp1_pct"]) / risk if risk else 0
    rr2 = abs(plan["tp2_pct"]) / risk if risk else 0
    size_usd = plan.get("size_usd", 5000)
    size_btc = size_usd / last_price if last_price else 0
    out = [
        "💰 ПЛАН ВХОДА",
        f"  Направление: {direction}",
        f"  Размер:  ${size_usd:,} (≈{size_btc:.4f} BTC)",
        f"  Entry:  ~${last_price:,.0f}",
        f"  Stop:   ${stop:,.0f}   ({plan['stop_pct']:+.2f}%)",
        f"  TP1:    ${tp1:,.0f}   ({plan['tp1_pct']:+.2f}%, R:R 1:{rr1:.1f})",
        f"  TP2:    ${tp2:,.0f}   ({plan['tp2_pct']:+.2f}%, R:R 1:{rr2:.1f})",
    ]
    if plan.get("note"):
        out.append(f"  ⚠ {plan['note']}")
    return out


def _load_dedup() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        return json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_dedup(d: dict) -> None:
    DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        DEDUP_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("cascade_alert.dedup_save_failed")


def _liquidation_window_sums(now_utc: datetime, window_min: int) -> tuple[float, float, float | None]:
    """Wrapped legacy 3-tuple for backward compat. Use _liquidation_window_breakdown
    для полной информации с per-exchange разбивкой."""
    long_btc, short_btc, last_price, _ = _liquidation_window_breakdown(now_utc, window_min)
    return long_btc, short_btc, last_price


def _liquidation_window_breakdown(now_utc: datetime, window_min: int
                                    ) -> tuple[float, float, float | None, dict]:
    """Read last N min from liquidations.csv. Returns
    (long_btc_total, short_btc_total, last_price, by_exchange).

    by_exchange: {"bybit": {"long": float, "short": float}, "okx": {...}}.
    Cross-exchange confirmation: если cascade на >1 бирже одновременно — high conviction.
    """
    if not LIQ_CSV.exists():
        return 0.0, 0.0, None, {}
    cutoff = now_utc - timedelta(minutes=window_min)
    long_btc = 0.0
    short_btc = 0.0
    last_price = None
    by_exchange: dict[str, dict[str, float]] = {}
    try:
        with LIQ_CSV.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("ts_utc", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                try:
                    qty = float(row.get("qty") or 0)
                    price = float(row.get("price") or 0)
                except (ValueError, TypeError):
                    continue
                if qty <= 0:
                    continue
                side = (row.get("side") or "").lower()
                exch = (row.get("exchange") or "unknown").lower()
                by_exchange.setdefault(exch, {"long": 0.0, "short": 0.0})
                if side == "long":
                    long_btc += qty
                    by_exchange[exch]["long"] += qty
                elif side == "short":
                    short_btc += qty
                    by_exchange[exch]["short"] += qty
                if price > 0:
                    last_price = price
    except OSError:
        logger.exception("cascade_alert.liq_read_failed")
    return long_btc, short_btc, last_price, by_exchange


def _format_exchange_breakdown(side: str, by_exchange: dict, min_threshold: float = 0.3) -> str:
    """Build per-exchange breakdown line. Cross-exchange (>1 биржа) = confirmation."""
    contribs = []
    for exch, sides in by_exchange.items():
        v = sides.get(side, 0.0)
        if v >= min_threshold:
            contribs.append(f"{exch}={v:.2f}")
    if len(contribs) >= 2:
        return f"📡 Cross-exchange ({len(contribs)} бирж): " + ", ".join(contribs)
    elif len(contribs) == 1:
        return f"📡 Только {contribs[0]} BTC"
    return ""


def _format_alert(side: str, threshold: float, qty_btc: float, last_price: float | None,
                   by_exchange: dict | None = None) -> str:
    info = EDGE_TEXT.get((side, threshold)) or EDGE_TEXT.get((side, 5.0))
    lines: list[str] = []
    drifted = False
    try:
        from services.cascade_alert.edge_drift_guard import is_drifted
        drifted = is_drifted(side, threshold)
    except Exception:
        logger.exception("cascade_alert.drift_check_failed")

    # При drift'е long-cascade — переключаемся на inverted SHORT play.
    # 2024→2026 edge inversion: long-cascade был bounce, стал continuation вниз.
    # cascade_backtest_combined.json подтвердил инверсию (n=20 / 2026 live).
    inverted = INVERTED_PLAYS.get((side, threshold)) if drifted else None
    if inverted:
        lines.append("🔄 EDGE INVERTED — старый bounce edge мёртв, торгуем по новому 2026-режиму.")
        lines.append("")
        lines.append(inverted["title"])
        lines.append("")
        lines.append(f"Ликвидировано: {qty_btc:.2f} BTC за {WINDOW_MINUTES} мин")
        if by_exchange:
            exch_line = _format_exchange_breakdown(side, by_exchange)
            if exch_line:
                lines.append(exch_line)
        if last_price:
            lines.append(f"Цена: ~${last_price:,.0f}")
        lines.append("")
        lines.append(inverted["stats"])
        lines.append("")
        lines.append(inverted["play"])
        plan_lines = _format_entry_plan(inverted.get("entry_plan"), last_price)
        if plan_lines:
            lines.append("")
            lines.extend(plan_lines)
        return "\n".join(lines)

    # Не drifted ИЛИ drift без inverted-карты (short-side, mega) — обычный путь.
    if drifted:
        lines.append("⚠️ EDGE DRIFTED — историческая статистика ниже не подтверждается на live-данных. Не торговать как сетап.")
        lines.append("")
    lines.append(info["title"])
    lines.append("")
    lines.append(f"Ликвидировано: {qty_btc:.2f} BTC за {WINDOW_MINUTES} мин")
    if by_exchange:
        exch_line = _format_exchange_breakdown(side, by_exchange)
        if exch_line:
            lines.append(exch_line)
    if last_price:
        lines.append(f"Цена: ~${last_price:,.0f}")
    lines.append("")
    lines.append(info["stats"])
    lines.append("")
    lines.append(info["play"])
    if not drifted:
        plan_lines = _format_entry_plan(info.get("entry_plan"), last_price)
        if plan_lines:
            lines.append("")
            lines.extend(plan_lines)
    return "\n".join(lines)


EVAL_INTERVAL_SEC = 3600  # evaluate_pending запускается раз в час
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"


def _price_at(target: datetime) -> float | None:
    """Lookup close-price for target ts (±2 min). Reads market_1m.csv tail."""
    if not MARKET_1M_CSV.exists():
        return None
    target_floor = target.replace(second=0, microsecond=0)
    window = (target_floor - timedelta(minutes=2), target_floor + timedelta(minutes=2))
    best: tuple[float, float] | None = None  # (abs_dt_sec, close)
    try:
        with MARKET_1M_CSV.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = datetime.fromisoformat(row["ts_utc"])
                except (ValueError, KeyError):
                    continue
                if ts < window[0] or ts > window[1]:
                    continue
                try:
                    close = float(row["close"])
                except (ValueError, KeyError):
                    continue
                dt_sec = abs((ts - target_floor).total_seconds())
                if best is None or dt_sec < best[0]:
                    best = (dt_sec, close)
    except OSError:
        return None
    return best[1] if best else None


async def cascade_accuracy_eval_loop(stop_event: asyncio.Event,
                                     interval_sec: int = EVAL_INTERVAL_SEC,
                                     drift_send_fn=None) -> None:
    """Background tick: evaluates pending cascade prognoses every hour.
    Each 24th tick also runs edge-drift evaluation.
    """
    from services.cascade_alert.accuracy_tracker import evaluate_pending, summary
    from services.cascade_alert.edge_drift_guard import evaluate_drift
    logger.info("cascade_accuracy_eval.start interval=%ds", interval_sec)
    tick = 0
    while not stop_event.is_set():
        try:
            n = evaluate_pending(get_price_fn=_price_at)
            if n > 0:
                logger.info("cascade_accuracy_eval.filled n=%d", n)
            # Drift check raz в сутки (24 tick × 1h = 24h)
            if tick % 24 == 0:
                try:
                    statuses = evaluate_drift(summary_fn=summary, send_fn=drift_send_fn)
                    drifted = [s for s in statuses if s.drifted]
                    if drifted:
                        logger.warning("cascade_edge_drift.detected count=%d", len(drifted))
                    else:
                        logger.info("cascade_edge_drift.healthy entries=%d", len(statuses))
                except Exception:
                    logger.exception("cascade_edge_drift.eval_failed")
        except Exception:
            logger.exception("cascade_accuracy_eval.tick_failed")
        tick += 1
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("cascade_accuracy_eval.stopped")


def _record_paper_cascade(side: str, threshold: float, last_price: float | None,
                           now: datetime) -> None:
    """Записывает hypothetical paper-trade в state/paper_signals.jsonl.

    Direction map (validated в state/cascade_backtest_combined.json):
      long_liq cascade (price dropped, longs liquidated) → SHORT continuation (2026 inversion)
      short_liq cascade (price rose, shorts liquidated)  → LONG fade (still works)

    Через 7-14 дней weekly aggregator покажет real-world win rate.
    """
    if last_price is None or last_price <= 0:
        return
    try:
        from services.paper_signal_tracker.journal import record_paper_signal
        trade_side = "SHORT" if side == "long" else "LONG"
        record_paper_signal(
            source="cascade_alert",
            side=trade_side,
            entry=float(last_price),
            stop_pct=-0.5, tp_pct=0.75, hold_h=4,
            context=f"{side}_liq_{threshold:.1f}btc",
            now=now,
        )
    except Exception:
        logger.exception("cascade_alert.paper_signal_failed")


def _record_cascade_prognosis(side: str, threshold: float, qty_btc: float,
                              last_price: float | None, now: datetime) -> None:
    """Best-effort journal write for accuracy tracker. Never raises."""
    if last_price is None or last_price <= 0:
        return
    try:
        from services.cascade_alert.accuracy_tracker import CascadePrognosis, record_prognosis
        predicted = PREDICTED_PCT_12H.get((side, threshold), 0.0)
        record_prognosis(CascadePrognosis(
            ts=now.isoformat(timespec="seconds"),
            direction=side,
            threshold_btc=float(threshold),
            spot_price=float(last_price),
            qty_btc=float(qty_btc),
            predicted_pct_12h=float(predicted),
        ))
    except Exception:
        logger.exception("cascade_alert.record_prognosis_failed")


async def cascade_alert_loop(stop_event: asyncio.Event, *, send_fn=None, interval_sec: int = POLL_INTERVAL_SEC) -> None:
    """Async loop. Каждые 60 сек проверяет cascade в last 5min window.

    send_fn: callable(text) — будет вызвана с alert текстом если каскад обнаружен.
    """
    if send_fn is None:
        logger.warning("cascade_alert.no_send_fn — alerts будут только в логе")

    logger.info("cascade_alert.start interval=%ds threshold_high=%.1fBTC threshold_medium=%.1fBTC window=%dmin",
                interval_sec, THRESHOLD_BTC, THRESHOLD_BTC_MEDIUM, WINDOW_MINUTES)

    while not stop_event.is_set():
        try:
            now = datetime.now(timezone.utc)
            long_btc, short_btc, last_price, by_exchange = _liquidation_window_breakdown(now, WINDOW_MINUTES)
            # Mega tier: tighter window for rare 10+ BTC bursts
            mega_long, mega_short, _ = _liquidation_window_sums(now, MEGA_WINDOW_MINUTES)
            dedup = _load_dedup()
            # Cross-tier dedup: if MEGA fires for a side this tick, we
            # silence the regular 5BTC/2BTC card for the same side. Operator
            # complaint 2026-05-25: same liq-event was sending MEGA + 5BTC
            # cards within the same minute, two different "plans".
            mega_fired_sides: set[str] = set()

            # MEGA tier (10+ BTC in 1 min) — fired first, highest priority
            for side, mega_qty in (("long", mega_long), ("short", mega_short)):
                if mega_qty < THRESHOLD_BTC_MEGA:
                    continue
                key = f"{side}_{THRESHOLD_BTC_MEGA}_mega"
                last_sent_str = dedup.get(key)
                if last_sent_str:
                    try:
                        last_sent = datetime.fromisoformat(last_sent_str.replace("Z", "+00:00"))
                        if (now - last_sent).total_seconds() < MEGA_DEDUP_COOLDOWN_SEC:
                            continue
                    except ValueError:
                        pass
                text = _format_alert(side, THRESHOLD_BTC_MEGA, mega_qty, last_price, by_exchange=by_exchange)
                logger.info("cascade_alert.MEGA side=%s qty=%.2f", side, mega_qty)
                # edge_drift_guard 2026-05-25 (v2): suppress ALL drifted
                # variants, INCLUDING those with an INVERTED_PLAYS entry.
                # Rationale (operator/teammate complaint, day 3): the n=20-43
                # inverted backtest is too thin to push as a trade plan; when
                # original edge is drifted, the safest action is silence — not
                # a "here's an inverted setup, trade this instead" card. We
                # keep INVERTED_PLAYS metadata for future re-validation but
                # do not emit them as live signals.
                try:
                    from services.cascade_alert.edge_drift_guard import is_drifted
                    _drifted = is_drifted(side, THRESHOLD_BTC_MEGA)
                except Exception:
                    _drifted = False
                if _drifted:
                    logger.info("cascade_alert.MEGA.suppressed_drift side=%s qty=%.2f",
                                side, mega_qty)
                    dedup[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    continue
                # Universal paper-WR gate (2026-05-23): trade-side = fade of
                # liq side. Block emission if recent paper WR for that trade
                # direction has decayed below the policy threshold — preventive
                # backstop independent of edge_drift_guard's accuracy metric.
                _trade_side = "SHORT" if side == "long" else "LONG"
                try:
                    from services.common.paper_wr_gate import should_emit
                    _ok, _why = should_emit("cascade_alert", _trade_side)
                except Exception:
                    _ok, _why = True, "wr_gate_unavailable"
                if not _ok:
                    logger.info("cascade_alert.MEGA.suppressed_wr_gate "
                                "side=%s trade=%s %s", side, _trade_side, _why)
                    dedup[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    continue
                # 2026-05-29 regime gate: skip cascade follows in strong trend.
                _adx = _current_adx_1h()
                if _adx >= ADX_TREND_CAP:
                    logger.info("cascade_alert.MEGA.suppressed_adx_trend "
                                "side=%s qty=%.2f adx=%.1f", side, mega_qty, _adx)
                    dedup[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    continue
                # Cross-service dedup: skip if cascade_followup already fired
                # for this side within last 10 min (operator-confusion guard).
                try:
                    from services.cascade_alert.cross_service_dedup import (
                        recently_emitted, mark_emitted,
                    )
                    blocked, who = recently_emitted(side, now)
                except Exception:
                    blocked, who = False, ""
                if blocked:
                    logger.info("cascade_alert.MEGA.suppressed_cross_service "
                                "side=%s by=%s", side, who)
                    dedup[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    continue
                if send_fn is not None:
                    try:
                        send_fn(text)
                    except Exception:
                        logger.exception("cascade_alert.mega_send_failed")
                try:
                    mark_emitted("cascade_alert_mega", side, now)
                except Exception:
                    pass
                _record_cascade_prognosis(side, THRESHOLD_BTC_MEGA, mega_qty, last_price, now)
                _record_paper_cascade(side, THRESHOLD_BTC_MEGA, last_price, now)
                dedup[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                mega_fired_sides.add(side)

            for side, qty in (("long", long_btc), ("short", short_btc)):
                # Cross-tier dedup: skip regular 5BTC/2BTC if MEGA already
                # fired this tick for the same side.
                if side in mega_fired_sides:
                    logger.info("cascade_alert.suppressed_by_mega side=%s qty=%.2f",
                                side, qty)
                    continue
                # Определяем threshold (high имеет приоритет)
                if qty >= THRESHOLD_BTC:
                    threshold = THRESHOLD_BTC
                elif qty >= THRESHOLD_BTC_MEDIUM:
                    threshold = THRESHOLD_BTC_MEDIUM
                else:
                    continue

                key = f"{side}_{threshold}"
                last_sent_str = dedup.get(key)
                if last_sent_str:
                    try:
                        last_sent = datetime.fromisoformat(last_sent_str.replace("Z", "+00:00"))
                        if (now - last_sent).total_seconds() < DEDUP_COOLDOWN_SEC:
                            continue
                    except ValueError:
                        pass

                # Weak-conviction filter for 2BTC tier: single-exchange + qty
                # barely above threshold = noise. Operator complained about
                # repeated marginal alerts (e.g. 2.32 BTC OKX-only 2026-05-19).
                suppress, suppress_reason = _is_weak_conviction(threshold, qty, by_exchange)
                if suppress:
                    _log_suppressed(side, threshold, qty, suppress_reason, by_exchange, now)
                    logger.info("cascade_alert.suppressed side=%s threshold=%.1f qty=%.2f reason=%s",
                                side, threshold, qty, suppress_reason)
                    dedup[key] = now.isoformat(timespec="seconds")
                    continue

                # Триггер alert
                text = _format_alert(side, threshold, qty, last_price, by_exchange=by_exchange)
                logger.info("cascade_alert.triggered side=%s threshold=%.1f qty=%.2f", side, threshold, qty)
                # edge_drift_guard 2026-05-25 (v2): suppress ALL drifted,
                # including those that would have been shown as INVERTED.
                # See MEGA branch above for rationale.
                try:
                    from services.cascade_alert.edge_drift_guard import is_drifted
                    _drifted = is_drifted(side, threshold)
                except Exception:
                    _drifted = False
                if _drifted:
                    logger.info("cascade_alert.suppressed_drift "
                                "side=%s threshold=%.1f qty=%.2f", side, threshold, qty)
                    dedup[key] = now.isoformat(timespec="seconds")
                    continue
                # paper-WR gate (preventive — see MEGA branch above).
                _trade_side = "SHORT" if side == "long" else "LONG"
                try:
                    from services.common.paper_wr_gate import should_emit
                    _ok, _why = should_emit("cascade_alert", _trade_side)
                except Exception:
                    _ok, _why = True, "wr_gate_unavailable"
                if not _ok:
                    logger.info("cascade_alert.suppressed_wr_gate "
                                "side=%s trade=%s threshold=%.1f %s",
                                side, _trade_side, threshold, _why)
                    dedup[key] = now.isoformat(timespec="seconds")
                    continue
                # 2026-05-29 regime gate: skip cascade follows in strong trend.
                _adx = _current_adx_1h()
                if _adx >= ADX_TREND_CAP:
                    logger.info("cascade_alert.suppressed_adx_trend "
                                "side=%s threshold=%.1f adx=%.1f", side, threshold, _adx)
                    dedup[key] = now.isoformat(timespec="seconds")
                    continue
                # Cross-service dedup
                try:
                    from services.cascade_alert.cross_service_dedup import (
                        recently_emitted, mark_emitted,
                    )
                    blocked, who = recently_emitted(side, now)
                except Exception:
                    blocked, who = False, ""
                if blocked:
                    logger.info("cascade_alert.suppressed_cross_service "
                                "side=%s threshold=%.1f by=%s", side, threshold, who)
                    dedup[key] = now.isoformat(timespec="seconds")
                    continue
                if send_fn is not None:
                    try:
                        send_fn(text)
                    except Exception:
                        logger.exception("cascade_alert.send_failed")
                try:
                    mark_emitted("cascade_alert", side, now)
                except Exception:
                    pass
                _record_cascade_prognosis(side, threshold, qty, last_price, now)
                _record_paper_cascade(side, threshold, last_price, now)

                # Auto paper trade (B2): originally opened a virtual position
                # on every cascade. Disabled 2026-05-08 — live data showed
                # 0W/3L (-90 USD) over 5 days, contradicting the n=103 backtest
                # (73% pct_up). Likely cause: paper trade fires 5+ minutes
                # after the cascade peak, by which time the bounce has already
                # started or finished. Re-enable via env CASCADE_AUTO_OPEN=1
                # once thresholds are re-tuned (e.g. higher BTC qty bar).
                import os as _os
                if _os.environ.get("CASCADE_AUTO_OPEN", "0") == "1":
                    try:
                        from services.paper_trader.cascade_trade import open_cascade_trade
                        trade = open_cascade_trade(side, threshold, qty, last_price or 0)
                        if trade and send_fn:
                            send_fn(
                                f"📋 Paper trade открыт автоматически\n"
                                f"trade_id: {trade['trade_id']}\n"
                                f"{trade['side'].upper()} @ ${trade['entry']:,.0f} | TP ${trade['tp1']:,.0f} | SL ${trade['sl']:,.0f}"
                            )
                    except Exception:
                        logger.exception("cascade_alert.paper_trade_failed")

                dedup[key] = now.isoformat(timespec="seconds")
                _save_dedup(dedup)
        except Exception:
            logger.exception("cascade_alert.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass

    logger.info("cascade_alert.stopped")
