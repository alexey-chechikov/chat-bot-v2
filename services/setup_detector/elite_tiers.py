"""Empirical elite-tier classification for setup_detector setups.

Used by:
  - telegram_card.py — render an ELITE / STRONG / WEAK badge + WR stats
    line on the trade card so the operator immediately sees the historical
    quality of this exact (setup_type, regime, session, pair) combination.
  - paper_trader/trader.py — multiply the paper notional size so the
    elite buckets get bigger paper-PnL allocation (and asymmetric
    feedback for forward-test calibration).

Rules derived from 2026-05-23 paper-perf audit + LMD deep-dive
(scripts/pump_research/_paper_perf_audit.py +
 scripts/pump_research/_multi_divergence_deepdive.py). 60 closed paper
trades of long_multi_divergence:
  range_wide regime  : n=53 / WR 92.5% / +$5010
  ny_pm session      : n=42 / WR 95.2% / +$3638
  ny_am session      : n=8  / WR 100%  / +$1414
  BTCUSDT pair       : n=49 / WR 98%   / +$4296
  asia session       : n=5  / WR 40%   /  +$148  (downgrade)
  XRPUSDT pair       : n=7  / WR 28.6% / +$1428  (downgrade; PnL only OK due to 2 outlier TP2)

Rules ordered most-specific to least; first match wins.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TierVerdict:
    tier: Optional[str]      # "ELITE" / "STRONG" / "WEAK" / None (no rule)
    wr_pct: Optional[float]  # historical WR in this bucket
    sample_n: Optional[int]
    size_mult: float         # paper-notional multiplier (1.0 = default)
    rule_id: str             # short label for logging / audit


# (setup_type, regime, session, pair, tier, wr, n, mult, rule_id)
# None means "any" for that dimension. Order matters — first match wins.
# Rule order: ELITE (most-specific) → WEAK (specific exclusions) → STRONG
# (broader defaults). WEAK must come before broad STRONG so an asia-session
# or XRPUSDT setup gets downgraded before the broad range_wide STRONG fires.
_RULES: list[tuple] = [
    # ELITE — narrowest, highest-conviction
    ("long_multi_divergence", "range_wide", "ny_am",  "BTCUSDT",
     "ELITE",  100.0, 8,   2.0, "LMD_BTC_range_NYam"),
    ("long_multi_divergence", "range_wide", "ny_pm",  "BTCUSDT",
     "ELITE",   95.2, 42,  2.0, "LMD_BTC_range_NYpm"),

    # WEAK — specific exclusions evaluated BEFORE the broad STRONG rules
    ("long_multi_divergence", None,         "asia",   None,
     "WEAK",    40.0, 5,   0.25, "LMD_asia_session"),
    ("long_multi_divergence", None,         None,     "XRPUSDT",
     "WEAK",    28.6, 7,   0.25, "LMD_XRPUSDT_pair"),

    # STRONG — broader defaults
    ("long_multi_divergence", "range_wide", None,     "BTCUSDT",
     "STRONG",  92.5, 53,  1.5, "LMD_BTC_range_any-session"),
    ("long_multi_divergence", "range_wide", None,     None,
     "STRONG",  92.5, 53,  1.3, "LMD_range_any-pair"),
]


def classify_setup(setup_type: Optional[str],
                   regime: Optional[str],
                   session: Optional[str],
                   pair: Optional[str]) -> TierVerdict:
    """Return the highest-specificity matching tier verdict.
    No rule match → TierVerdict(None, None, None, 1.0)."""
    if not setup_type:
        return TierVerdict(None, None, None, 1.0, "no-type")
    for st, rg, sn, pr, tier, wr, n, mult, rule_id in _RULES:
        if st and st != setup_type:
            continue
        if rg and rg != regime:
            continue
        if sn and sn != session:
            continue
        if pr and pr != pair:
            continue
        return TierVerdict(tier=tier, wr_pct=wr, sample_n=n,
                            size_mult=mult, rule_id=rule_id)
    return TierVerdict(None, None, None, 1.0, "no-match")


def badge_line(v: TierVerdict) -> Optional[str]:
    """Pretty TG-card badge line, or None if no tier classification."""
    if v.tier is None:
        return None
    icon = {"ELITE": "💎", "STRONG": "⭐", "WEAK": "⚠️"}.get(v.tier, "•")
    return (f"{icon} {v.tier} bucket — historical WR {v.wr_pct:.0f}% "
            f"(n={v.sample_n}, paper) | rule={v.rule_id}")
