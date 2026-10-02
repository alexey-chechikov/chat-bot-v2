"""/setups TG command — детальный список открытых paper позиций и активных
сигналов с конкретными уровнями: entry, SL, TP1, TP2, R/R, причина, действие.

Делит вывод на 3 секции:
  1. ОТКРЫТЫЕ В РАБОТЕ — paper_trades.jsonl с action=OPEN и нет CLOSE
  2. P-15 LIVE LEGS — runtime state из p15_state.json (не торговые SL/TP,
     а R/K/dd_cap логика).
  3. СВЕЖИЕ СИГНАЛЫ (последние 2ч) — setups.jsonl, не открытые в paper, но
     эмитнутые. Это потенциальные ручные сделки.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PAPER_TRADES = _ROOT / "state" / "paper_trades.jsonl"
_SETUPS = _ROOT / "state" / "setups.jsonl"
_P15_STATE = _ROOT / "state" / "p15_state.json"
_LIVE_1M = _ROOT / "market_live" / "market_1m.csv"
_DERIV_LIVE = _ROOT / "state" / "deriv_live.json"


DETECTOR_RU = {
    "long_pdl_bounce": "LONG отбой от PDL",
    "long_dump_reversal": "LONG разворот после дампа",
    "long_double_bottom": "LONG двойное дно",
    "long_multi_divergence": "LONG мульти-дивергенция",
    "long_rsi_momentum_ga": "LONG RSI momentum",
    "long_oversold_reclaim": "LONG reclaim из oversold",
    "long_mega_dump_bounce": "LONG mega dump bounce",
    "short_pdh_rejection": "SHORT от PDH",
    "short_rally_fade": "SHORT fade rally",
    "short_mfi_multi_ga": "SHORT MFI multi",
    "short_double_top": "SHORT двойная вершина",
    "short_overbought_fade": "SHORT overbought fade",
    "short_div_bos_15m": "SHORT div BOS 15m",
}


def _current_prices() -> dict[str, float]:
    """Returns {'BTCUSDT': 80777.9, 'ETHUSDT': 2311.9, 'XRPUSDT': 1.464}.

    Reads mark_price from state/deriv_live.json (live, 5min refresh).
    """
    if not _DERIV_LIVE.exists():
        return {}
    try:
        d = json.loads(_DERIV_LIVE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for pair in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
        p = d.get(pair) or {}
        mark = p.get("mark_price")
        if mark is not None:
            try: out[pair] = float(mark)
            except (TypeError, ValueError): pass
    return out


def _load_paper_trades() -> tuple[list[dict], set[str]]:
    """Returns (open_records, closed_ids)."""
    if not _PAPER_TRADES.exists():
        return [], set()
    opens = []
    closed = set()
    try:
        with _PAPER_TRADES.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                action = (r.get("action") or "").upper()
                if action == "OPEN":
                    opens.append(r)
                elif action in ("CLOSE", "TP1", "TP2", "SL", "EXPIRE"):
                    closed.add(r.get("trade_id"))
    except OSError:
        pass
    return opens, closed


def _load_recent_setups(hours: int = 2) -> list[dict]:
    """Setups эмитнутые за последние N часов."""
    if not _SETUPS.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    try:
        with _SETUPS.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    s = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_raw = s.get("detected_at", "")
                try:
                    dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if dt >= cutoff:
                    s["_ts"] = dt
                    out.append(s)
    except OSError:
        pass
    return out


def _load_p15_legs() -> list[dict]:
    """Open P-15 legs from runtime state."""
    if not _P15_STATE.exists():
        return []
    try:
        data = json.loads(_P15_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for key, leg in data.items():
        if not isinstance(leg, dict) or not leg.get("in_pos"): continue
        try:
            pair, direction = key.split(":", 1)
        except ValueError:
            continue
        size = float(leg.get("total_size_usd") or 0)
        weighted = float(leg.get("weighted_entry") or 0)
        avg = weighted / size if size > 0 else 0
        out.append({
            "pair": pair,
            "direction": direction,
            "layers": int(leg.get("layers", 0)),
            "size": size,
            "avg_entry": avg,
            "extreme": float(leg.get("extreme_price") or 0),
            "dd_pct": float(leg.get("cum_dd_pct") or 0),
            "last_stage": str(leg.get("last_emitted_stage", "")),
            "opened": leg.get("opened_at_ts", ""),
        })
    return out


def _format_open_trade(r: dict, prices: dict[str, float]) -> list[str]:
    pair_key = r.get("pair", "BTCUSDT")
    cur_price = prices.get(pair_key)
    """4-5 lines per open trade: setup, entry/SL/TP, current PnL, action."""
    det = r.get("setup_type", "?")
    ru = DETECTOR_RU.get(det, det)
    pair = r.get("pair", "?")
    side = r.get("side", "?")
    entry = float(r.get("entry") or 0)
    sl = float(r.get("sl") or 0)
    tp1 = float(r.get("tp1") or 0)
    tp2 = float(r.get("tp2") or 0)
    rr = float(r.get("rr_planned") or 0)
    size_usd = float(r.get("size_usd") or 0)
    conf = float(r.get("confidence_pct") or 0)

    # Price formatting precision: BTC/ETH use 2 decimals, XRP and other low-priced 4 decimals.
    digits = 4 if entry < 100 else 2
    fmt = f",.{digits}f"
    arrow = "🟢" if side == "long" else "🔴"
    lines = [f"{arrow} {ru} ({pair})  conf {conf:.0f}%"]
    lines.append(f"    Entry  ${entry:{fmt}}  size ${size_usd:.0f}")
    lines.append(f"    Stop   ${sl:{fmt}}  ({(sl-entry)/entry*100:+.2f}%)")
    lines.append(f"    TP1    ${tp1:{fmt}}  ({(tp1-entry)/entry*100:+.2f}%)  R/R 1:{rr:.1f}")
    if tp2 and tp2 != tp1:
        lines.append(f"    TP2    ${tp2:{fmt}}  ({(tp2-entry)/entry*100:+.2f}%)")

    if cur_price and entry > 0:
        if side == "long":
            pnl_pct = (cur_price - entry) / entry * 100
            to_tp1 = (tp1 - cur_price) / cur_price * 100
            to_sl = (cur_price - sl) / cur_price * 100
        else:
            pnl_pct = (entry - cur_price) / entry * 100
            to_tp1 = (cur_price - tp1) / cur_price * 100
            to_sl = (sl - cur_price) / cur_price * 100
        pnl_emoji = "✅" if pnl_pct > 0 else "❌"
        lines.append(
            f"    Now    ${cur_price:{fmt}}  PnL {pnl_pct:+.2f}% {pnl_emoji}  "
            f"до TP1 {to_tp1:+.2f}%, до SL {to_sl:+.2f}%"
        )

    # Action recommendation
    if cur_price and entry > 0 and sl > 0:
        # how close are we to either side
        if side == "long":
            tp_dist = abs(tp1 - cur_price)
            sl_dist = abs(cur_price - sl)
        else:
            tp_dist = abs(cur_price - tp1)
            sl_dist = abs(sl - cur_price)
        if sl_dist < tp_dist * 0.3:
            lines.append(f"    💡 близко к SL — следи или fix loss")
        elif tp_dist < sl_dist * 0.3:
            lines.append(f"    💡 близко к TP1 — готовь частичное закрытие")
    return lines


def _format_p15_leg(leg: dict, prices: dict[str, float]) -> list[str]:
    cur_price = prices.get(leg["pair"])
    pair = leg["pair"]
    direction = leg["direction"]
    arrow = "🟢" if direction == "long" else "🔴"
    avg = leg["avg_entry"]
    size = leg["size"]
    extreme = leg["extreme"]
    dd = leg["dd_pct"]
    stage = leg["last_stage"]
    layers = leg["layers"]
    age_min = 0
    try:
        if leg["opened"]:
            opened_at = datetime.fromisoformat(leg["opened"].replace("Z", "+00:00"))
            if opened_at.tzinfo is None: opened_at = opened_at.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - opened_at).total_seconds() / 60
    except (ValueError, AttributeError):
        pass

    age_str = f"{age_min:.0f}м" if age_min < 60 else f"{age_min/60:.1f}ч"
    digits = 4 if avg < 100 else 2
    fmt = f",.{digits}f"
    lines = [f"{arrow} P-15 {direction.upper()} {pair}  ({layers} слоёв, {age_str})"]
    lines.append(f"    Avg entry  ${avg:{fmt}}  size ${size:.0f}")
    lines.append(f"    Extreme    ${extreme:{fmt}}  DD {dd:+.2f}%")

    if cur_price and avg > 0:
        if direction == "long":
            pnl_pct = (cur_price - avg) / avg * 100
        else:
            pnl_pct = (avg - cur_price) / avg * 100
        pnl_emoji = "✅" if pnl_pct > 0 else "❌"
        lines.append(f"    Now ${cur_price:{fmt}}  PnL {pnl_pct:+.2f}% {pnl_emoji}  stage: {stage}")

    # P-15 logic explanation
    lines.append(f"    💡 P-15: SL нет, выход по R={0.3}% retrace или dd_cap=3%")
    return lines


def _format_recent_signal(s: dict) -> list[str]:
    det = s.get("setup_type", "?")
    if det.startswith("p15_"):
        return []  # P-15 lifecycle — отдельная секция
    ru = DETECTOR_RU.get(det, det)
    pair = s.get("pair", "?")
    side = "long" if "long" in det else "short"
    arrow = "🟢" if side == "long" else "🔴"
    entry = float(s.get("entry_price") or 0)
    sl = float(s.get("stop_price") or 0)
    tp1 = float(s.get("tp1_price") or 0)
    tp2 = float(s.get("tp2_price") or 0)
    rr = float(s.get("risk_reward") or 0)
    conf = float(s.get("confidence_pct") or 0)
    age_min = (datetime.now(timezone.utc) - s["_ts"]).total_seconds() / 60

    digits = 4 if entry < 100 else 2
    fmt = f",.{digits}f"
    lines = [f"{arrow} {ru} ({pair})  conf {conf:.0f}%  {age_min:.0f}мин назад"]
    lines.append(f"    Entry ${entry:{fmt}}  SL ${sl:{fmt}}  TP1 ${tp1:{fmt}}"
                  + (f"  TP2 ${tp2:{fmt}}" if tp2 != tp1 else "")
                  + f"  R/R 1:{rr:.1f}")
    return lines


def build_setups_report() -> str:
    prices = _current_prices()
    btc_price = prices.get("BTCUSDT")
    now = datetime.now(timezone.utc)

    opens, closed_ids = _load_paper_trades()
    active = [r for r in opens
              if r.get("trade_id") not in closed_ids
              and not str(r.get("setup_type", "")).startswith("p15_")
              and "sl" in r]  # only proper trades with SL

    p15_legs = _load_p15_legs()
    # 2026-10-02: P-15 выключен, p15_state.json не обновлялся с 23.05 — карточка
    # называла бумажные ноги «P-15 LIVE» с PnL −13% / −33%. Файл старше суток =
    # остаток выключенной стратегии, а не живые позиции.
    p15_stale = None
    try:
        mtime = datetime.fromtimestamp(_P15_STATE.stat().st_mtime, timezone.utc)
        if now - mtime > timedelta(days=1):
            p15_stale = mtime
    except OSError:
        pass
    if p15_stale is not None:
        p15_legs = []
    setups = _load_recent_setups(hours=2)
    fresh_signals = [s for s in setups if not str(s.get("setup_type", "")).startswith("p15_")]
    # Dedupe fresh signals — show only most recent per (type, pair)
    seen = {}
    for s in sorted(fresh_signals, key=lambda x: x["_ts"], reverse=True):
        key = (s.get("setup_type"), s.get("pair"))
        if key not in seen:
            seen[key] = s
    fresh_unique = sorted(seen.values(), key=lambda x: x["_ts"], reverse=True)

    lines = [f"📋 СЕТАПЫ  ({now:%H:%M UTC})"]
    if prices:
        parts = []
        for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
            if sym in prices:
                p = prices[sym]
                if p > 100:
                    parts.append(f"{sym[:3]} ${p:,.0f}")
                else:
                    parts.append(f"{sym[:3]} ${p:.4f}")
        lines.append("  ".join(parts))
    lines.append("")

    # === 1. PAPER TRADES (открытые) ===
    if active:
        lines.append(f"━━ ОТКРЫТО В PAPER ({len(active)}) ━━")
        lines.append("")
        for r in active[:10]:
            lines.extend(_format_open_trade(r, prices))
            lines.append("")
    else:
        lines.append("━━ ОТКРЫТО В PAPER: 0 ━━")
        lines.append("")

    # === 2. P-15 LEGS (live) ===
    if p15_legs:
        lines.append(f"━━ P-15 LIVE ({len(p15_legs)} leg) ━━")
        lines.append("")
        for leg in p15_legs:
            lines.extend(_format_p15_leg(leg, prices))
            lines.append("")
    elif p15_stale is not None:
        lines.append(f"━━ P-15 выключен (бумажный, данные от {p15_stale:%d.%m}) — "
                     f"реальных позиций нет ━━")
        lines.append("")
    else:
        lines.append("━━ P-15 LIVE: нет активных leg ━━")
        lines.append("")

    # === 3. СВЕЖИЕ СИГНАЛЫ (последние 2ч) ===
    if fresh_unique:
        lines.append(f"━━ СВЕЖИЕ СИГНАЛЫ (последние 2ч, {len(fresh_unique)}) ━━")
        lines.append("")
        for s in fresh_unique[:8]:
            extra = _format_recent_signal(s)
            if extra:
                lines.extend(extra)
                lines.append("")
    else:
        lines.append("━━ СВЕЖИЕ СИГНАЛЫ: нет за 2ч ━━")
        lines.append("")

    # === ИТОГ ===
    lines.append("📋 ИТОГ:")
    if active:
        lines.append(f"  • {len(active)} открытых paper-trade с фикс. SL/TP")
    if p15_legs:
        total_size = sum(l["size"] for l in p15_legs)
        lines.append(f"  • {len(p15_legs)} P-15 leg ${total_size:.0f} (rolling без SL)")
    if fresh_unique:
        lines.append(f"  • {len(fresh_unique)} свежих сигналов — рассмотри для ручной сделки")
    if not (active or p15_legs or fresh_unique):
        lines.append("  • нет активности — рынок тихий")

    return "\n".join(lines)
