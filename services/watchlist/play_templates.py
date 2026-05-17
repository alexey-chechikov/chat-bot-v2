"""Named "play" templates that enrich watchlist alerts with concrete entry plans.

When a Rule.label matches a key here, watchlist_loop appends a "ПЛАН ВХОДА" section
with absolute entry/stop/TP levels computed from current market price.

Refactor 2026-05-17:
  - Cross-asset clarity: signal_symbol (что триггерило rule) и trade_symbol
    (на чём торгуем) разделены. По умолчанию оба BTCUSDT, явный override для
    cross-asset rules (например xrp00003: signal=XRP, trade=BTC).
  - Edge-over-baseline: рядом с conditional WR показывается unconditional
    baseline за тот же study period — оператор видит реальный edge в п.п.
  - VPVR-context: при наличии manual_levels.json показываем dist до VAL/VAH и
    предупреждаем если entry/TP упираются в volume support/resistance.
  - Setup verdict: GO / CAUTION / SKIP по 3 проверкам (R:R, edge vs baseline,
    market state alignment).
  - Scale-out: scale_out_pct позволяет частично фиксировать на TP1 и двигать
    стоп в безубыток — спасает плохой TP1 R:R 0.5 у taker_imbalance_short.

Thresholds based on combined 2024+2026 backtest (scripts/cascade_backtest_combined.py)
and funding-edge study (2 years of 8h BTCUSDT funding vs forward 4h/24h price moves).
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"
MANUAL_LEVELS_PATH = ROOT / "state" / "manual_levels.json"
BOT_BRAIN_STATE_PATH = ROOT / "state" / "bot_brain_state.jsonl"
DERIV_PATH = ROOT / "state" / "deriv_live.json"

# Map trade_symbol → storage_symbol используемый в manual_levels.json
LEVELS_STORAGE_MAP = {
    "BTCUSDT": "BTCUSD",
    "ETHUSDT": "ETHUSDT",
    "XRPUSDT": "XRPUSDT",
}


def _last_btc_price() -> Optional[float]:
    """Read last close from market_live/market_1m.csv. Used for BTC entry."""
    if not MARKET_1M_CSV.exists():
        return None
    last_close: Optional[float] = None
    try:
        with MARKET_1M_CSV.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    last_close = float(row["close"])
                except (ValueError, KeyError):
                    continue
    except OSError:
        logger.exception("play_templates.market_read_failed")
    return last_close


def _last_price_for(symbol: str) -> Optional[float]:
    """Last live mark_price per symbol. BTCUSDT — from 1m CSV (most accurate),
    others — from deriv_live.json snapshot."""
    if symbol.upper() == "BTCUSDT":
        return _last_btc_price()
    try:
        if DERIV_PATH.exists():
            d = json.loads(DERIV_PATH.read_text(encoding="utf-8"))
            return float(d.get(symbol.upper(), {}).get("mark_price") or 0) or None
    except (OSError, ValueError, json.JSONDecodeError):
        logger.exception("play_templates.deriv_read_failed symbol=%s", symbol)
    return None


def _load_levels(trade_symbol: str) -> Optional[dict]:
    """Read manual_levels.json entry for trade_symbol."""
    try:
        if not MANUAL_LEVELS_PATH.exists():
            return None
        levels = json.loads(MANUAL_LEVELS_PATH.read_text(encoding="utf-8"))
        storage = LEVELS_STORAGE_MAP.get(trade_symbol.upper(), trade_symbol.upper())
        return levels.get(storage)
    except (OSError, json.JSONDecodeError):
        return None


def _read_brain_state_latest() -> Optional[dict]:
    """Tail bot_brain_state.jsonl for latest snapshot. None if file missing."""
    if not BOT_BRAIN_STATE_PATH.exists():
        return None
    try:
        with BOT_BRAIN_STATE_PATH.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 16 * 1024)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except (OSError, json.JSONDecodeError):
        return None


def _breakeven_wr(rr: float) -> float:
    """Breakeven WR for given reward:risk ratio. R:R 1.0 → 50%, R:R 0.5 → 66.7%."""
    if rr <= 0:
        return 1.0
    return 1.0 / (1.0 + rr)


def _vpvr_context(entry: float, direction: str, stop: float, tp1: float, tp2: float,
                  levels: dict) -> list[str]:
    """Return lines describing VPVR alignment of the setup. levels has val/vah/poc."""
    out = []
    val = levels.get("val")
    vah = levels.get("vah")
    poc = levels.get("poc")
    if not (val and vah):
        return out

    def _pct(a, b):
        return (a - b) / b * 100.0 if b else 0.0

    if direction == "SHORT":
        # SHORT: entry near VAL ⇒ caveat (selling into support)
        if val and abs(_pct(entry, val)) < 0.30:
            out.append(f"  ⚠ entry близко к VAL ${val:,.0f} (support) — SHORT в зону объёма")
        if val and tp2 < val:
            out.append(f"  ⚠ TP2 ниже VAL ${val:,.0f} — нужно сломать volume support")
        if poc and abs(_pct(entry, poc)) < 0.15:
            out.append(f"  ⚠ entry у POC ${poc:,.0f} — высокая ликвидность, реверс возможен")
    else:  # LONG
        if vah and abs(_pct(entry, vah)) < 0.30:
            out.append(f"  ⚠ entry близко к VAH ${vah:,.0f} (resistance) — LONG в зону объёма")
        if vah and tp2 > vah:
            out.append(f"  ⚠ TP2 выше VAH ${vah:,.0f} — нужно сломать volume resistance")
    return out


def _verdict(play: dict, rr_primary: float, ctx_warnings: int,
             edge_pp: Optional[float], regime_match: Optional[bool]) -> str:
    """GO / CAUTION / SKIP based on R:R, edge over baseline, market context.

    Verdict strictness rules:
      - HARD-SKIP: edge_pp < 0 → rule performs WORSE than random baseline →
        trading it has negative expected value, no half-size salvages this.
      - HARD-SKIP: regime_match=False AND edge_pp < 5 — going against regime
        with marginal edge = burn.
      - Otherwise: flag-count logic (0 flags = GO, 1 = CAUTION, 2+ = SKIP).
    """
    # Hard-skip: anti-edge (worse than random)
    if edge_pp is not None and edge_pp < 0:
        return (f"🔴 SKIP — anti-edge ({edge_pp:+.1f} п.п. vs baseline). "
                f"Rule fires когда rate ХУЖЕ случайного. -EV at any size.")

    flags: list[str] = []
    if rr_primary < 1.0:
        flags.append("RR")
    if edge_pp is not None and edge_pp < 3.0:
        flags.append("edge")
    if ctx_warnings >= 2:
        flags.append("vpvr")
    if regime_match is False:
        flags.append("regime")

    # Hard-skip: regime conflict + marginal edge
    if regime_match is False and (edge_pp is None or edge_pp < 5):
        return f"🔴 SKIP (regime conflict + edge {edge_pp:+.1f} п.п.) — wait"

    if not flags:
        return "🟢 GO — R:R, edge over baseline, context all align"
    if len(flags) == 1:
        return f"🟡 CAUTION (issue: {flags[0]}) — half size, tight stop discipline"
    return f"🔴 SKIP (issues: {', '.join(flags)}) — wait for cleaner setup"


PLAYS: dict[str, dict] = {
    "funding_squeeze_long": {
        "title": "📈 FUNDING SQUEEZE → LONG",
        "edge": "n=10 (за 2 года) при funding < -0.010%/8h\n"
                "  +4ч: 70% pct_up, mean +0.68%\n"
                "  +24ч: 70% pct_up, mean +0.60%",
        "signal_symbol": "BTCUSDT",
        "trade_symbol": "BTCUSDT",
        "dir": "LONG",
        "tp1_pct": +0.46,
        "tp2_pct": +0.68,
        "stop_pct": -0.40,
        "exit_after_h": 4,
        "baseline_4h_up_pct": 50.0,  # unconditional baseline (approx)
        "edge_wr_pct": 70.0,
        "scale_out_pct": None,
        "note": "Редкий сетап (~5 раз/год). Размер обычный.",
    },
    "cascade_short_continuation_long": {
        "title": "📈 SHORT-каскад → LONG (продолжение тренда вверх)",
        "edge": "n=139 (2024+2026 combined, обновлено): 70% pct_up 4h, mean +0.41%\n"
                "  Сетап работал стабильно в обоих периодах.",
        "signal_symbol": "BTCUSDT",
        "trade_symbol": "BTCUSDT",
        "dir": "LONG",
        "tp1_pct": +0.41,
        "tp2_pct": +0.74,
        "stop_pct": -0.40,
        "exit_after_h": 4,
        "baseline_4h_up_pct": 50.0,
        "edge_wr_pct": 70.0,
        "scale_out_pct": None,
        "note": None,
    },
    "cascade_long_reversal_short": {
        "title": "📉 LONG-каскад → SHORT (новый сетап для 2026 режима)",
        "edge": "n=20 (2026): 65% pct_down 4h, mean -0.17%, 12h -0.58%\n"
                "  ⚠ ИНВЕРСИЯ от 2024 (там был bounce). Малая выборка.",
        "signal_symbol": "BTCUSDT",
        "trade_symbol": "BTCUSDT",
        "dir": "SHORT",
        "tp1_pct": -0.40,
        "tp2_pct": -0.78,
        "stop_pct": +0.40,
        "exit_after_h": 4,
        "baseline_4h_up_pct": 50.0,
        "edge_wr_pct": 65.0,
        "scale_out_pct": None,
        "note": "Свежий edge на 2026 регим. Половинный размер до n>=40.",
    },
    "taker_imbalance_long": {
        "title": "📈 BTC LONG (XRP taker imbalance signal)",
        "edge": "n=109 (23 дня апр-май 2026): XRP heavy_buy quintile (>58%)\n"
                "  +4ч: 68% BTC pct_up, mean +0.27%\n"
                "  +24ч: 70% BTC pct_up, mean +0.63%\n"
                "  ⚠ Cross-asset: XRP taker → BTC trade.\n"
                "  ⚠ Выборка короткая (23 дня), нужна валидация ≥3 мес.",
        "signal_symbol": "XRPUSDT",
        "trade_symbol": "BTCUSDT",
        "dir": "LONG",
        "tp1_pct": +0.27,
        "tp2_pct": +0.63,
        "stop_pct": -0.40,
        "exit_after_h": 4,
        "baseline_4h_up_pct": 50.0,
        "edge_wr_pct": 68.0,
        "scale_out_pct": 0.30,  # 30% out at TP1, move stop to BE, 70% rides
        "note": "TP1 R:R 0.68 — scale-out 30% и BE-stop вместо чистого TP-take.",
    },
    "taker_imbalance_short": {
        "title": "📉 BTC SHORT (taker imbalance signal) [MAKER-ONLY]",
        # Edge text is overridden per-signal-symbol below. Default = XRP (cross-asset).
        "edge": "n=171 path-aware (XRP cross-asset): TP2 hit 26% / SL hit 25%\n"
                "  mean PnL scale-out: +0.027%/trade\n"
                "  Net as maker: +0.047%/trade (XBTUSD inverse rebate −0.02% RT)\n"
                "  Net as taker: -0.073% — НЕ БРАТЬ market.",
        "signal_symbol": "XRPUSDT",  # default if rule_symbol not passed
        "trade_symbol": "BTCUSDT",
        "dir": "SHORT",
        "tp1_pct": -0.15,
        "tp2_pct": -0.40,
        "stop_pct": +0.30,
        "exit_after_h": 4,
        "baseline_4h_up_pct": 50.0,
        "edge_wr_pct": 44.0,
        "scale_out_pct": 0.30,
        "maker_only": True,
        "cancel_after_min": 5,
        # Per-signal-symbol path-aware stats (2026-05-17 backtest 10 дней live)
        # Overrides edge/edge_wr_pct/edge_text when rule fires from that symbol.
        "per_signal_stats": {
            "BTCUSDT": {
                "edge_text": "n=165 path-aware (BTC own taker < 42):\n"
                             "  TP2 hit 24% / SL hit 30%, mean PnL scale-out +0.001%/trade (FLAT)\n"
                             "  Net as maker: +0.021%/trade  /  taker: −0.099%\n"
                             "  ⚠ BTC own taker signal слабый, edge на грани шума.",
                "edge_wr_pct": 44.8,
            },
            "ETHUSDT": {
                "edge_text": "n=168 path-aware (ETH cross-asset → BTC):\n"
                             "  TP2 hit 26% / SL hit 26%, mean PnL scale-out +0.020%/trade\n"
                             "  Net as maker: +0.040%/trade  /  taker: −0.080%",
                "edge_wr_pct": 46.4,
            },
            "XRPUSDT": {
                "edge_text": "n=171 path-aware (XRP cross-asset → BTC):\n"
                             "  TP2 hit 26% / SL hit 25%, mean PnL scale-out +0.027%/trade\n"
                             "  Net as maker: +0.047%/trade  /  taker: −0.073%",
                "edge_wr_pct": 43.9,
            },
        },
        "note": "MAKER-ONLY: post-only sell-limit @ entry. Если не fill за 5мин — skip. Иначе −EV.",
    },
    "topshort_divergence_long": {
        "title": "📈 BTC LONG 24h (top-traders shorting vs retail longing, contrarian)",
        "edge": "n=55 (top 10% top-bearish divergence, апр-май 2026):\n"
                "  +24ч: 71% pct_up, mean +0.87%\n"
                "  Парадокс: когда top-traders шортят, рынок идёт ВВЕРХ.\n"
                "  Top-trader индикатор — контрарианский, не follow-the-money.\n"
                "  ⚠ Выборка короткая, валидация ≥3 мес",
        "signal_symbol": "BTCUSDT",
        "trade_symbol": "BTCUSDT",
        "dir": "LONG",
        "tp1_pct": +0.40,
        "tp2_pct": +0.87,
        "stop_pct": -0.50,
        "exit_after_h": 24,
        "baseline_4h_up_pct": 50.0,
        "edge_wr_pct": 71.0,
        "scale_out_pct": None,
        "note": "Triggered when (top_trader_long_pct - global_long_pct) < -5pp.",
    },
}


def format_play(label: str, current_value: float, *,
                rule_symbol: Optional[str] = None) -> Optional[str]:
    """Return enriched alert lines for known play label, or None.

    `rule_symbol`: actual symbol of the rule that fired (BTCUSDT/ETHUSDT/XRPUSDT).
    Overrides play['signal_symbol'] — since a single label may be triggered by
    multiple symbol-rules (same threshold on each symbol's taker_buy), the
    template needs to know which symbol's data actually fired."""
    play = PLAYS.get(label)
    if not play:
        return None

    trade_symbol = play.get("trade_symbol", "BTCUSDT")
    # Real signal symbol = rule that fired; fallback to template default
    signal_symbol = rule_symbol or play.get("signal_symbol", trade_symbol)
    price = _last_price_for(trade_symbol)
    if not price or price <= 0:
        return None

    # Per-signal-symbol overrides (different paths may have different edge stats)
    per_signal = (play.get("per_signal_stats") or {}).get(signal_symbol, {})
    edge_text = per_signal.get("edge_text", play.get("edge"))
    edge_wr_pct = per_signal.get("edge_wr_pct", play.get("edge_wr_pct") or 0)

    tp1 = price * (1 + play["tp1_pct"] / 100)
    tp2 = price * (1 + play["tp2_pct"] / 100)
    stop = price * (1 + play["stop_pct"] / 100)
    risk = abs(play["stop_pct"])
    rr1 = abs(play["tp1_pct"]) / risk if risk else 0
    rr2 = abs(play["tp2_pct"]) / risk if risk else 0
    be_wr_tp1 = _breakeven_wr(rr1) * 100
    be_wr_tp2 = _breakeven_wr(rr2) * 100
    edge_pp = edge_wr_pct - (play.get("baseline_4h_up_pct") or 0)
    if play["dir"] == "SHORT":
        # SHORT edge uses pct_down — same math but baseline_up flips
        edge_pp = edge_wr_pct - (100 - (play.get("baseline_4h_up_pct") or 50))

    exit_at = datetime.now(timezone.utc) + timedelta(hours=play["exit_after_h"])

    levels = _load_levels(trade_symbol) or {}
    vpvr_lines = _vpvr_context(price, play["dir"], stop, tp1, tp2, levels) if levels else []

    # Regime context — read latest bot_brain snapshot
    brain = _read_brain_state_latest()
    regime_match: Optional[bool] = None
    regime_line: Optional[str] = None
    if brain:
        mkt = brain.get("market", {}).get(trade_symbol, {})
        regime = mkt.get("regime_primary")
        vol_regime = mkt.get("vol_regime")
        own_taker = mkt.get("taker_buy_pct")
        regime_line = (f"  Текущий: regime={regime} vol={vol_regime}"
                       f" own_taker={own_taker:.1f}%" if own_taker else
                       f"  Текущий: regime={regime} vol={vol_regime}")
        # Trend-align check: SHORT едет в TREND_DOWN, LONG в TREND_UP
        if play["dir"] == "SHORT" and regime == "TREND_DOWN":
            regime_match = True
        elif play["dir"] == "LONG" and regime == "TREND_UP":
            regime_match = True
        elif regime in ("TREND_UP", "TREND_DOWN"):
            regime_match = False  # opposite trend
        # Cross-asset conflict warning: if signal_symbol != trade_symbol AND
        # trade_symbol's OWN taker is opposite to direction → conflict
        if signal_symbol != trade_symbol and own_taker is not None:
            if play["dir"] == "SHORT" and own_taker > 55:
                regime_line += f"  ⚠ own taker {own_taker:.1f}% > 55% — против SHORT"
                regime_match = False
            if play["dir"] == "LONG" and own_taker < 45:
                regime_line += f"  ⚠ own taker {own_taker:.1f}% < 45% — против LONG"
                regime_match = False

    verdict = _verdict(play, rr2, len(vpvr_lines), edge_pp, regime_match)

    # Build card
    symbol_tag = f"[{trade_symbol[:3]}]"
    cross_tag = (f"  Сигнал: {signal_symbol} ({signal_symbol[:3]} taker_buy"
                 f" {current_value:.1f}%)") if signal_symbol != trade_symbol else None

    lines = ["", play["title"], "", "ЭДЖ:", edge_text, ""]
    if cross_tag:
        lines.extend([cross_tag, ""])

    lines.extend([
        f"💰 ПЛАН ВХОДА {symbol_tag}",
        f"  Направление: {play['dir']}",
        f"  Entry:  ~${price:,.4f}" if trade_symbol == "XRPUSDT" else f"  Entry:  ~${price:,.0f}",
        f"  Stop:   ${stop:,.4f}   ({play['stop_pct']:+.2f}%)" if trade_symbol == "XRPUSDT"
            else f"  Stop:   ${stop:,.0f}   ({play['stop_pct']:+.2f}%)",
        f"  TP1:    ${tp1:,.4f}   ({play['tp1_pct']:+.2f}%, R:R 1:{rr1:.2f}, BE-WR {be_wr_tp1:.0f}%)" if trade_symbol == "XRPUSDT"
            else f"  TP1:    ${tp1:,.0f}   ({play['tp1_pct']:+.2f}%, R:R 1:{rr1:.2f}, BE-WR {be_wr_tp1:.0f}%)",
        f"  TP2:    ${tp2:,.4f}   ({play['tp2_pct']:+.2f}%, R:R 1:{rr2:.2f}, BE-WR {be_wr_tp2:.0f}%)" if trade_symbol == "XRPUSDT"
            else f"  TP2:    ${tp2:,.0f}   ({play['tp2_pct']:+.2f}%, R:R 1:{rr2:.2f}, BE-WR {be_wr_tp2:.0f}%)",
        f"  Exit by time: {exit_at.strftime('%Y-%m-%d %H:%M UTC')} ({play['exit_after_h']}ч)",
    ])

    # Maker-only execution requirement (overrides normal entry)
    if play.get("maker_only"):
        cancel_min = play.get("cancel_after_min", 5)
        lines.append("")
        lines.append("⚠ MAKER-ONLY EXECUTION:")
        action_word = "SELL" if play["dir"] == "SHORT" else "BUY"
        price_fmt = f"${price:,.4f}" if trade_symbol == "XRPUSDT" else f"${price:,.0f}"
        # Dynamic edge claim per signal_symbol (extracted from per_signal stats)
        edge_mean_per_trade_pct = {
            "BTCUSDT": "+0.001%", "ETHUSDT": "+0.020%", "XRPUSDT": "+0.027%",
        }.get(signal_symbol, "tiny")
        lines.append(f"  1) Выставь {action_word} LIMIT (post-only) @ {price_fmt}")
        lines.append(f"  2) Если не fill за {cancel_min} мин — отменить, skip сетап")
        lines.append(f"  3) Market entry НЕ БРАТЬ — фи съедят edge (taker −0.10% > {edge_mean_per_trade_pct} edge)")

    # Scale-out plan (if defined) — replaces "TP-take" interpretation
    scale = play.get("scale_out_pct")
    if scale:
        sp = int(scale * 100)
        lines.append("")
        lines.append(f"📋 PLAN (рекомендуется):")
        lines.append(f"  1) При касании TP1: фикс {sp}% позиции, stop → BE (${price:,.0f})")
        lines.append(f"  2) Остаток {100-sp}% едет к TP2")
        lines.append(f"  3) Time-out: market exit at {exit_at.strftime('%H:%M UTC')}")

    # Edge-over-baseline
    lines.append("")
    lines.append("📊 ЭДЖ vs BASELINE:")
    lines.append(f"  Conditional WR (path-aware): {edge_wr_pct:.0f}%")
    lines.append(f"  Unconditional baseline: ~{play.get('baseline_4h_up_pct') if play['dir']=='LONG' else 100-play.get('baseline_4h_up_pct'):.0f}%")
    lines.append(f"  Edge over baseline: {edge_pp:+.1f} п.п. {'✅' if edge_pp >= 5 else '⚠ слабо' if edge_pp >= 3 else '❌ внутри шума'}")

    # VPVR / regime context
    if vpvr_lines or regime_line:
        lines.append("")
        lines.append("🎯 КОНТЕКСТ:")
        if regime_line:
            lines.append(regime_line)
        lines.extend(vpvr_lines)

    # Verdict
    lines.append("")
    lines.append(f"🎲 ВЕРДИКТ: {verdict}")

    if play.get("note"):
        lines.append("")
        lines.append(f"  ⚠ {play['note']}")
    return "\n".join(lines)
