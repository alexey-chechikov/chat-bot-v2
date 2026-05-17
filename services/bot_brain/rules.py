"""Bot Brain — decision rules.

Each rule is a pure function: takes the latest bot_brain snapshot, returns a
list of proposed actions (Proposal). The executor processes proposals according
to risk-tier policy (auto-execute on testbed, dry-run-only on production for
risky actions, etc.).

Rules implemented (Phase 2 initial set):
  R1_cascade_short_pause   — SHORT bots when fresh cascade_short detected
                             (echo of short_bots_guard — kept here for unified
                             attribution, executor avoids double-pause)
  R2_cascade_long_pause    — LONG bots when fresh cascade_long detected (echo)
  R3_vol_high_resize       — When vol_regime=HIGH and bot unrealized < -3% →
                             resize × 0.5 (TESTBED ONLY initially)
  R4_drift_recenter        — When price drifted > 5% beyond grid + time-in-grid > 2h
                             → recenter (stub for now)
  R5_daily_pnl_cap         — When bot daily PnL < per-tier cap → pause
  R6_exhaustion_fix        — When exhaustion-fire same direction as bot AND
                             unrealized > +3% → fix_partial(50%) (TESTBED ONLY)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Pause-eligibility policy (2026-05-17 operator directive) ────────────────
# Per-tier filter: which managed bots are allowed to be auto-paused at all.
# Operator: "T2 и T3 вообще не нужно ставить на паузу". T1 — самый узкий
# grid_step, страдает от движений; T2/T3 — шире, переживают сами.
# LONG-D/V5 — отдельные хеджи, оператор не запросил их в фильтр; пока
# оставляем включёнными но с теми же price-movement gates.
PAUSE_ALLOWED_TIERS = {"T1", "TB", "LONG-D", "LONG-V5"}

# Minimum BTC 15-min one-sided move (absolute %) required to fire pre-cascade
# pause. Below this — micro-move, not worth pausing for. Operator: pause should
# trigger on TRULY STRONG one-sided moves, not 0.3-1% spikes.
MIN_PRICE_MOVE_15M_PCT = 1.5

# Minimum liq-cluster qty (BTC) on cluster side to count as meaningful signal.
# Existing detector threshold = 0.5 BTC. Bot-brain rule action requires more.
MIN_LIQ_CLUSTER_QTY_BTC = 1.5


def _pause_eligible(bot: dict, market: dict, *,
                    expected_price_dir: str,
                    require_strong_move: bool = True) -> tuple[bool, str]:
    """Central gate before any pause proposal fires. Returns (eligible, reason).

    expected_price_dir: 'up' for SHORT-bot pause (SHORT loses on price up),
                       'down' for LONG-bot pause.
    require_strong_move: if True (default for pre-cascade rules), require
                         BTC moved ≥ MIN_PRICE_MOVE_15M_PCT in expected dir.
                         Reactive R1/R2 (cascade-already-fired) skip this gate.
    """
    tier = bot.get("tier")
    if tier not in PAUSE_ALLOWED_TIERS:
        return False, f"tier {tier} excluded from auto-pause (operator policy)"
    if bot.get("paused_by_guard"):
        return False, "already paused"
    if not require_strong_move:
        return True, "ok (no price-move gate)"
    pc15 = market.get("price_change_15m_pct")
    if pc15 is None:
        return False, "price_change_15m_pct unavailable, fail-safe SKIP"
    if expected_price_dir == "up" and pc15 < MIN_PRICE_MOVE_15M_PCT:
        return False, f"BTC 15m move {pc15:+.2f}% < +{MIN_PRICE_MOVE_15M_PCT}% threshold"
    if expected_price_dir == "down" and pc15 > -MIN_PRICE_MOVE_15M_PCT:
        return False, f"BTC 15m move {pc15:+.2f}% > -{MIN_PRICE_MOVE_15M_PCT}% threshold"
    return True, f"ok (BTC 15m {pc15:+.2f}%)"


def _liq_cluster_qty_meets_min(market: dict, side: str) -> Optional[float]:
    """Return max qty_btc of recent cluster on `side` if it meets MIN threshold,
    else None. Filters out micro-clusters."""
    clusters = market.get("liq_cluster_fires_recent") or []
    max_qty = 0.0
    for c in clusters:
        if c.get("side") != side:
            continue
        q = c.get("qty_btc") or 0
        try:
            q = float(q)
        except (TypeError, ValueError):
            continue
        if q > max_qty:
            max_qty = q
    return max_qty if max_qty >= MIN_LIQ_CLUSTER_QTY_BTC else None


# Per-tier daily PnL stop caps (USD). Hit → pause.
DAILY_PNL_CAP_USD = {
    "T1": -50.0,
    "T2": -100.0,
    "T3": -150.0,
    "LONG-D": -100.0,
    "LONG-V5": -100.0,
    "TB": -30.0,
}


@dataclass
class Proposal:
    rule_id: str
    bot_id: str
    tier: str
    action: str            # e.g. "pause" / "resize" / "tighten_grid"
    params: dict           # action-specific params
    reason: str            # human-readable rationale
    confidence: float = 0.5  # 0-1; for ranking when multiple rules collide
    testbed_only: bool = False  # if True, executor skips on production bots


def _market_for_bot(snapshot: dict, bot: dict) -> dict:
    """Pick the market state most relevant to this bot (BTC for all current bots)."""
    return snapshot.get("market", {}).get("BTCUSDT", {}) or {}


def _has_fresh_cascade(market: dict, direction: str, max_age_min: float = 20.0) -> bool:
    """direction: 'short' or 'long' — checks cascades_recent list."""
    casc = market.get("cascades_recent") or []
    prefix = f"{direction}_"
    return any(
        c.get("age_min", 999) <= max_age_min and (c.get("type") or "").startswith(prefix)
        for c in casc
    )


# ─── Rules ────────────────────────────────────────────────────────────────────

def r1_cascade_short_pause(snapshot: dict) -> list[Proposal]:
    """Reactive: cascade_short ALREADY fired (≥2 BTC shorts liquidated). Strong
    real signal — gate by tier only, skip price-move re-check (cascade already
    confirms move happened)."""
    out: list[Proposal] = []
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "short":
            continue
        mkt = _market_for_bot(snapshot, bot)
        if not _has_fresh_cascade(mkt, "short"):
            continue
        eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="up",
                                            require_strong_move=False)
        if not eligible:
            continue
        out.append(Proposal(
            rule_id="R1_cascade_short_pause",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"fresh cascade_short detected ({reason})",
            confidence=0.9,
        ))
    return out


def r2_cascade_long_pause(snapshot: dict) -> list[Proposal]:
    """Reactive: cascade_long ALREADY fired (≥2 BTC longs liquidated). Same
    gate-by-tier-only as R1 — cascade itself confirms move."""
    out: list[Proposal] = []
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "long":
            continue
        mkt = _market_for_bot(snapshot, bot)
        if not _has_fresh_cascade(mkt, "long"):
            continue
        eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="down",
                                            require_strong_move=False)
        if not eligible:
            continue
        out.append(Proposal(
            rule_id="R2_cascade_long_pause",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"fresh cascade_long detected ({reason})",
            confidence=0.85,
        ))
    return out


def _has_fresh_liq_cluster(market: dict, side: str, max_age_min: float = 30.0) -> bool:
    """Validated 2026-05-17 pre-cascade signal (precision 44% / recall 65% @ 30min).
    side='long' = long-liq cluster → expects LONG cascade
    side='short' = short-liq cluster → expects SHORT cascade."""
    clusters = market.get("liq_cluster_fires_recent") or []
    return any(
        c.get("age_min", 999) <= max_age_min and c.get("side") == side
        for c in clusters
    )


def r1_5_pre_cascade_short_pause(snapshot: dict) -> list[Proposal]:
    """Pre-emptive pause for SHORT bots on liq-cluster short-side fire.
    Gates (2026-05-17 tighter policy):
      - tier in {T1, TB, LONG-*} (T2/T3 excluded per operator)
      - liq-cluster qty_btc ≥ 1.5 BTC (raised from 0.5 baseline to filter noise)
      - BTC moved ≥ +1.5% in last 15m (price-confirms expected up move)
    Without all 3 — skip. Net effect: pause only on genuinely strong setups."""
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    if not _has_fresh_liq_cluster(mkt, "short"):
        return out
    qty = _liq_cluster_qty_meets_min(mkt, "short")
    if qty is None:
        return out
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "short":
            continue
        eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="up")
        if not eligible:
            continue
        out.append(Proposal(
            rule_id="R1.5_pre_cascade_short_pause",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"liq-cluster SHORT {qty:.1f}BTC + {reason}",
            confidence=0.55,
        ))
    return out


def r2_5_pre_cascade_long_pause(snapshot: dict) -> list[Proposal]:
    """Pre-emptive pause for LONG bots on liq-cluster long-side fire.
    Same gates as R1.5 (qty ≥1.5 BTC, BTC moved ≥1.5% DOWN in 15m)."""
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    if not _has_fresh_liq_cluster(mkt, "long"):
        return out
    qty = _liq_cluster_qty_meets_min(mkt, "long")
    if qty is None:
        return out
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "long":
            continue
        eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="down")
        if not eligible:
            continue
        out.append(Proposal(
            rule_id="R2.5_pre_cascade_long_pause",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"liq-cluster LONG {qty:.1f}BTC + {reason}",
            confidence=0.55,
        ))
    return out


def r1_6_pre_cascade_short_HIGH(snapshot: dict) -> list[Proposal]:
    """HIGH-confidence pre-pause: short-side cluster + BTC taker_buy < 42%.
    Feature search 2026-05-17 (scripts/pre_cascade_feature_search.py):
      - baseline short-side liq_cluster: precision 44% (n=39)
      - + taker_buy < 42 filter: precision 67% (n=12) — +23 п.п. lift
      - + taker_buy < 38 filter: precision 80% (n=5) — +36 п.п. lift (tight sample)
    Pause confidence 0.70 vs 0.55 for baseline R1.5."""
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    if not _has_fresh_liq_cluster(mkt, "short"):
        return out
    qty = _liq_cluster_qty_meets_min(mkt, "short")
    if qty is None:
        return out
    taker = mkt.get("taker_buy_pct")
    if taker is None or taker >= 42:
        return out
    confidence = 0.80 if taker < 38 else 0.70
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "short":
            continue
        eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="up")
        if not eligible:
            continue
        out.append(Proposal(
            rule_id="R1.6_pre_cascade_short_HIGH",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"liq-cluster SHORT {qty:.1f}BTC + taker {taker:.1f}<42 + {reason}",
            confidence=confidence,
        ))
    return out


def _has_recent_tv_cvd_div(market: dict, expected_direction: str,
                            max_age_min: float = 15.0) -> bool:
    """Check tv_alerts_recent for CVD-divergence alert in expected direction
    within max_age_min. Used by R1.7/R2.7 combo rules.

    expected_direction: "bearish" or "bullish" — per Phase 3.4 finding,
    OPPOSITE-direction CVD div is the absorption signal that lifts precision.
    """
    alerts = market.get("tv_alerts_recent") or []
    for a in alerts:
        if a.get("age_min", 999) > max_age_min:
            continue
        p = a.get("payload") or {}
        if p.get("indicator") != "cvd_divergence":
            continue
        if p.get("direction") == expected_direction:
            return True
    return False


def r1_7_pre_cascade_short_TV_CONFIRMED(snapshot: dict) -> list[Proposal]:
    """HIGHEST-confidence pre-pause: short-side liq_cluster + TV CVD bullish-div alert.
    Per Phase 3.4 research: opposite-direction CVD div (bullish_div when short-cluster
    fires) is absorption signal. Expected precision 55-65% (vs 44% baseline /
    67% R1.6). Confidence 0.85 — TV signal is independent confirmation.

    Fires only when both signals are recent (≤30min cluster + ≤15min TV alert).
    Stays dormant until TV alerts start arriving (no-op when tv_alerts.jsonl empty).
    """
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    if not _has_fresh_liq_cluster(mkt, "short"):
        return out
    qty = _liq_cluster_qty_meets_min(mkt, "short")
    if qty is None:
        return out
    if not _has_recent_tv_cvd_div(mkt, "bullish"):
        return out
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "short":
            continue
        eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="up")
        if not eligible:
            continue
        out.append(Proposal(
            rule_id="R1.7_pre_cascade_short_TV_CONFIRMED",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"liq-cluster SHORT {qty:.1f}BTC + TV CVD bullish-div + {reason}",
            confidence=0.85,
        ))
    return out


def r2_7_pre_cascade_long_TV_CONFIRMED(snapshot: dict) -> list[Proposal]:
    """HIGHEST-confidence pre-pause for LONG bots: long-side cluster + TV CVD bearish-div."""
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    if not _has_fresh_liq_cluster(mkt, "long"):
        return out
    qty = _liq_cluster_qty_meets_min(mkt, "long")
    if qty is None:
        return out
    if not _has_recent_tv_cvd_div(mkt, "bearish"):
        return out
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "long":
            continue
        eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="down")
        if not eligible:
            continue
        out.append(Proposal(
            rule_id="R2.7_pre_cascade_long_TV_CONFIRMED",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"liq-cluster LONG {qty:.1f}BTC + TV CVD bearish-div + {reason}",
            confidence=0.85,
        ))
    return out


def r2_6_pre_cascade_long_HIGH(snapshot: dict) -> list[Proposal]:
    """HIGH-confidence pre-pause: long-side cluster + funding < -0.003%/8h.
    Feature search 2026-05-17:
      - baseline long-side liq_cluster: precision 42% (n=36)
      - + funding < -3e-5 filter: precision 60% (n=5) — +18 п.п. lift
    Negative funding = shorts paying longs = bearish positioning → when longs
    crowd up despite paying, snap-back DOWN cascade more likely."""
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    if not _has_fresh_liq_cluster(mkt, "long"):
        return out
    qty = _liq_cluster_qty_meets_min(mkt, "long")
    if qty is None:
        return out
    funding = mkt.get("funding_rate_8h")
    if funding is None or funding > -3e-5:
        return out
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "long":
            continue
        eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="down")
        if not eligible:
            continue
        out.append(Proposal(
            rule_id="R2.6_pre_cascade_long_HIGH",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"liq-cluster LONG {qty:.1f}BTC + funding {funding*100:.4f}<-0.003 + {reason}",
            confidence=0.60,
        ))
    return out


def r3_vol_high_resize(snapshot: dict) -> list[Proposal]:
    """When vol_regime=HIGH and bot is sitting on >3% unrealized loss → resize × 0.5.
    Cuts position size to limit further bleed in chaotic markets."""
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    if mkt.get("vol_regime") != "high":
        return out
    for bot in snapshot.get("bots", []):
        # Use ginarea-reported current_profit as proxy for unrealized PnL
        cp = bot.get("current_profit_usd")
        bal = bot.get("balance")
        if cp is None or bal is None or bal <= 0:
            continue
        unr_pct = (cp / bal) * 100.0
        if unr_pct < -3.0:
            out.append(Proposal(
                rule_id="R3_vol_high_resize",
                bot_id=bot["bot_id"], tier=bot["tier"],
                action="resize", params={"factor": 0.5},
                reason=f"vol=HIGH + unrealized {unr_pct:.1f}% < -3% → cut size 50%",
                confidence=0.6,
                testbed_only=True,  # risky on prod bots
            ))
    return out


def r4_drift_recenter(snapshot: dict) -> list[Proposal]:
    """When price drifted >5% from grid centre → recenter.
    Phase 2.5: uses real drift_from_mid_pct from enriched snapshot (border read
    from params.csv). Recenter action is still a stub but rule is now accurate."""
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    mid = mkt.get("mid")
    for bot in snapshot.get("bots", []):
        drift = bot.get("drift_from_mid_pct")
        if drift is None:
            continue
        if abs(drift) > 5.0:
            out.append(Proposal(
                rule_id="R4_drift_recenter",
                bot_id=bot["bot_id"], tier=bot["tier"],
                action="recenter", params={"target_mid": mid, "drift_pct": drift},
                reason=f"drift_from_grid_mid {drift:+.1f}% > 5% — recenter to {mid}",
                confidence=0.6,
                testbed_only=False,  # auto-recenter is "наверное аккуратно" prod-OK
            ))
    return out


def r5_daily_pnl_cap(snapshot: dict) -> list[Proposal]:
    """Bot 24h realized PnL hit per-tier cap → pause for cooldown.
    Phase 2.5: uses real pnl_24h_usd from enriched snapshot (current_profit
    delta vs 24h ago in bot_brain_state.jsonl). Falls back to current_profit_usd
    proxy when history < 24h."""
    out: list[Proposal] = []
    for bot in snapshot.get("bots", []):
        pnl_24h = bot.get("pnl_24h_usd")
        cp = bot.get("current_profit_usd")
        # Prefer 24h PnL when available; fall back to current_profit
        metric = pnl_24h if pnl_24h is not None else cp
        if metric is None:
            continue
        cap = DAILY_PNL_CAP_USD.get(bot.get("tier", ""), -100.0)
        if metric < cap and not bot.get("paused_by_guard"):
            source = "pnl_24h" if pnl_24h is not None else "current_profit (fallback)"
            out.append(Proposal(
                rule_id="R5_daily_pnl_cap",
                bot_id=bot["bot_id"], tier=bot["tier"],
                action="pause", params={},
                reason=f"{source} ${metric:.2f} < cap ${cap} for tier {bot.get('tier')}",
                confidence=0.7,
            ))
    return out


def r6_exhaustion_fix(snapshot: dict) -> list[Proposal]:
    """If exhaustion-fire same direction as bot's adverse side AND unrealized > +3%
    → fix_partial(50%). Locks in profit when grid_coordinator signals trend
    exhaustion. Testbed-only initially — needs validation.

    Logic per side:
      SHORT bot: profitable when price went DOWN → exhaustion "down" fire = signal
                 the down-move is ending → lock in profit before reversal.
      LONG bot:  profitable when price went UP → exhaustion "up" fire = signal
                 the up-move is ending."""
    out: list[Proposal] = []
    mkt = snapshot.get("market", {}).get("BTCUSDT", {}) or {}
    exh = mkt.get("exhaustion_fires_recent") or {}
    fresh_up = any(f.get("age_min", 999) <= 45 and (f.get("score") or 0) >= 4
                    for f in exh.get("up", []))
    fresh_down = any(f.get("age_min", 999) <= 45 and (f.get("score") or 0) >= 4
                      for f in exh.get("down", []))
    for bot in snapshot.get("bots", []):
        cp = bot.get("current_profit_usd")
        bal = bot.get("balance")
        if cp is None or bal is None or bal <= 0:
            continue
        unr_pct = (cp / bal) * 100.0
        if unr_pct < 3.0:
            continue
        side = bot.get("side")
        # SHORT bot profits when price down → take profit on "down" exhaustion
        # LONG bot profits when price up → take profit on "up" exhaustion
        trigger = (side == "short" and fresh_down) or (side == "long" and fresh_up)
        if trigger:
            out.append(Proposal(
                rule_id="R6_exhaustion_fix",
                bot_id=bot["bot_id"], tier=bot["tier"],
                action="fix_partial", params={"pct": 0.50},
                reason=f"exhaustion fire ({'down' if side=='short' else 'up'}) "
                       f"+ unrealized +{unr_pct:.1f}% → fix 50%",
                confidence=0.6,
                testbed_only=True,
            ))
    return out


ALL_RULES = [
    r1_cascade_short_pause,
    r1_5_pre_cascade_short_pause,
    r1_6_pre_cascade_short_HIGH,
    r1_7_pre_cascade_short_TV_CONFIRMED,
    r2_cascade_long_pause,
    r2_5_pre_cascade_long_pause,
    r2_6_pre_cascade_long_HIGH,
    r2_7_pre_cascade_long_TV_CONFIRMED,
    r3_vol_high_resize,
    r4_drift_recenter,
    r5_daily_pnl_cap,
    r6_exhaustion_fix,
]


def evaluate_all(snapshot: dict) -> list[Proposal]:
    proposals: list[Proposal] = []
    for rule_fn in ALL_RULES:
        try:
            proposals.extend(rule_fn(snapshot))
        except Exception:
            logger.exception("bot_brain.rule_eval_failed rule=%s", rule_fn.__name__)
    return proposals
