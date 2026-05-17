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
    """Echo rule — short_bots_guard already pauses on cascade_short.
    Here we mirror the proposal for unified bot_brain audit trail.
    Skipped if bot already paused_by_guard."""
    out: list[Proposal] = []
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "short" or bot.get("paused_by_guard"):
            continue
        mkt = _market_for_bot(snapshot, bot)
        if _has_fresh_cascade(mkt, "short"):
            out.append(Proposal(
                rule_id="R1_cascade_short_pause",
                bot_id=bot["bot_id"], tier=bot["tier"],
                action="pause", params={},
                reason="fresh cascade_short detected (4h pct_up edge)",
                confidence=0.9,
            ))
    return out


def r2_cascade_long_pause(snapshot: dict) -> list[Proposal]:
    """Echo rule — short_bots_guard pauses LONG hedge bots on cascade_long."""
    out: list[Proposal] = []
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "long" or bot.get("paused_by_guard"):
            continue
        mkt = _market_for_bot(snapshot, bot)
        if _has_fresh_cascade(mkt, "long"):
            out.append(Proposal(
                rule_id="R2_cascade_long_pause",
                bot_id=bot["bot_id"], tier=bot["tier"],
                action="pause", params={},
                reason="fresh cascade_long detected (2026 inverted edge)",
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
    Liq-cluster short-side → expects SHORT cascade in next 30 min → SHORT bots
    (which profit when price DOWN but suffer when price spikes DOWN hard)
    paused upfront. Confidence lower than R1 (post-cascade) because precision
    is 44%, so 56% of pauses will be unneeded. Conservative — pause cost is
    low (skip some grid fills) vs cascade cost (drawdown). Confidence 0.55."""
    out: list[Proposal] = []
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "short" or bot.get("paused_by_guard"):
            continue
        mkt = _market_for_bot(snapshot, bot)
        # SHORT cascade hurts SHORT bots → pause if cluster of SHORT liqs (continuation)
        if _has_fresh_liq_cluster(mkt, "short"):
            out.append(Proposal(
                rule_id="R1.5_pre_cascade_short_pause",
                bot_id=bot["bot_id"], tier=bot["tier"],
                action="pause", params={},
                reason="liq-cluster SHORT-side fire (predicts SHORT cascade ~30min, precision 44%)",
                confidence=0.55,
            ))
    return out


def r2_5_pre_cascade_long_pause(snapshot: dict) -> list[Proposal]:
    """Pre-emptive pause for LONG bots on liq-cluster long-side fire."""
    out: list[Proposal] = []
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "long" or bot.get("paused_by_guard"):
            continue
        mkt = _market_for_bot(snapshot, bot)
        if _has_fresh_liq_cluster(mkt, "long"):
            out.append(Proposal(
                rule_id="R2.5_pre_cascade_long_pause",
                bot_id=bot["bot_id"], tier=bot["tier"],
                action="pause", params={},
                reason="liq-cluster LONG-side fire (predicts LONG cascade ~30min, precision 44%)",
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
    taker = mkt.get("taker_buy_pct")
    if taker is None or taker >= 42:
        return out
    confidence = 0.80 if taker < 38 else 0.70
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "short" or bot.get("paused_by_guard"):
            continue
        out.append(Proposal(
            rule_id="R1.6_pre_cascade_short_HIGH",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"liq-cluster SHORT + BTC taker_buy {taker:.1f}% < 42 "
                   f"(precision 67-80%, +23-36 п.п. vs baseline)",
            confidence=confidence,
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
    funding = mkt.get("funding_rate_8h")
    if funding is None or funding > -3e-5:
        return out
    for bot in snapshot.get("bots", []):
        if bot.get("side") != "long" or bot.get("paused_by_guard"):
            continue
        out.append(Proposal(
            rule_id="R2.6_pre_cascade_long_HIGH",
            bot_id=bot["bot_id"], tier=bot["tier"],
            action="pause", params={},
            reason=f"liq-cluster LONG + funding {funding*100:.4f}% < -0.003% "
                   f"(precision 60%, +18 п.п. vs baseline; small n=5)",
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
    r2_cascade_long_pause,
    r2_5_pre_cascade_long_pause,
    r2_6_pre_cascade_long_HIGH,
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
