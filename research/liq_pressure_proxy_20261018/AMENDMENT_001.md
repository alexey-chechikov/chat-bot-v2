# LPX-A0 amendment 001 — before execution or market data

This versioned amendment takes precedence over ambiguous wording in the original MODEL.md and PROTOCOL.md. The original documents and their registration remain unchanged. No real target data have been loaded and no market results have been calculated. Implementation is in progress but has not been executed at amendment registration.

1. Retirement eligibility is `cohort.birth_end_ms <= current_bar.start_ms`. A cohort born at the previous bar's end is eligible throughout the immediately following bar. A cohort born at the current bar's end cannot be retired by that same bar. The original phrase "born before this bar began" was too strict at the equality boundary. This correction is selected before implementation tests and before targets.
2. Placebo cohort age is measured at the frozen state's `feature_end_ms`, not at the later assessment anchor. Record both timestamps. The admitted feature state is unchanged between its last closed bar and the anchor; otherwise the assumed availability lag could move still-active cohorts beyond the frozen 24h age buckets.
3. Warm-up requires at least 288 complete consecutive 5m bars: duration is measured from the first accepted bar's start through the last accepted bar's end, at least 24 hours. A gap resets this clock.
4. Placebo replicate indices are integers 0..198. One local seeded RNG per replicate is consumed in LONG then SHORT order, ascending age bucket then ascending distance bucket, with stable cohort order `(birth_end_ms, virtual_level, mass)` within each group. No RNG or seed selection depends on results.
5. A cohort satisfying both touch and expiry transfers its mass once, with reason `touch_and_expiry`.
6. Descriptive display band membership is `center*(1-0.0025) <= level <= center*(1+0.0025)`. The primary scoring membership remains the original literal `abs(mark/level-1) <= 0.0025`; display bands are not the primary score.

All other fixed parameters, splits, gates, missingness rules and interpretation limits remain unchanged. This is a reference proxy specification, not reconstruction of CoinGlass Model 1. Its failure cannot reject CoinGlass as a whole.
