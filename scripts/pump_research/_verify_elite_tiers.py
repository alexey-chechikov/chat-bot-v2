"""Sanity check the elite-tier classifier — verifies 7 expected verdicts."""
import os, sys
sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.setup_detector.elite_tiers import classify_setup, badge_line

LMD = "long_multi_divergence"
cases = [
    # (setup_type, regime,        session, pair,       expected_tier, expected_mult)
    (LMD, "range_wide", "ny_am", "BTCUSDT", "ELITE", 2.0),
    (LMD, "range_wide", "ny_pm", "BTCUSDT", "ELITE", 2.0),
    (LMD, "range_wide", "london", "BTCUSDT", "STRONG", 1.5),
    (LMD, "range_wide", "ny_pm", "ETHUSDT", "STRONG", 1.3),
    (LMD, "trend_down", "asia",  "BTCUSDT", "WEAK",   0.25),
    (LMD, "range_wide", "ny_pm", "XRPUSDT", "WEAK",   0.25),
    ("short_pdh_rejection", "trend_down", "ny_pm", "BTCUSDT", None, 1.0),
]
ok = 0
for st, rg, sn, pr, exp_tier, exp_mult in cases:
    v = classify_setup(st, rg, sn, pr)
    pass_tier = v.tier == exp_tier
    pass_mult = abs(v.size_mult - exp_mult) < 1e-9
    status = "OK" if (pass_tier and pass_mult) else "FAIL"
    bdg = badge_line(v) or "(no badge)"
    print(f"  [{status}] {st:<25} {str(rg):<12} {str(sn):<8} {pr:<10} -> "
          f"{v.tier}/{v.size_mult}x  ({bdg})")
    if pass_tier and pass_mult:
        ok += 1
print(f"\n{ok}/{len(cases)} cases passed")
sys.exit(0 if ok == len(cases) else 1)
