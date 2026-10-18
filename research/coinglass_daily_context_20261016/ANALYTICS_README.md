# Offline daily analytics

```powershell
python -B research/coinglass_daily_context_20261016/analytics_daily.py --local-root C:/bot7/research/coinglass_daily_context_20261016/local
```

Standard library only. The helper reads normalized observations already present in real `YYYY-MM-DD/run_*/report.json` archives. It does not read raw evidence, preflight folders, synthetic archives, account/config files or network services. It never rewrites source archives, earlier analyses, journals, protocols or manifests.

The latest real run receives one immutable `local/analytics/analysis_<actual UTC milliseconds>/{report.json,summary.md}` bundle. Running again for the same input returns the existing analysis. Every previously frozen input SHA, including historical rows used for outcomes, is checked before calculation or reuse. An input modification is an error, not an excuse to rewrite results. Output publication uses an exclusive reservation and atomic directory rename on the intended Windows host. No mutable index is required.

Each report includes:

- Separate BTC spot/perpetual 96-closed-bar 24h price/volume/taker-flow statistics; 1h/4h activity and adjacent equal-duration volume comparisons.
- OI quantity and reported-value changes in separate units and time alignment; signed individually observed funding events keyed by `(timestamp, rate_type)`, with no assumed 8h schedule. Regular and Special at the same timestamp are separate events.
- Four hourly blocks for the latest closed 4h window, with aligned spot/perp flow and OI endpoints when available.
- Changes versus the immediately preceding real run only under matching stable source/settings/unit definitions. Missing/failed data is not a real zero drop. No prior baseline is invented.
- Prospective plans anchored at the first full 15m bar at/after the actual analysis creation timestamp. Later analyses evaluate +15/60/240/1440 minutes using the exact closed grid from current and archived observations.
- For each MATURE price outcome, same-window spot/perp volume, taker delta and weighted F, and exact OI endpoint changes; unavailable auxiliary context stays null with a reason. Related current daily changes remain separate; neither is a causal claim.

`PENDING`: target time has not elapsed, or no sufficiently later local refresh exists. `MISSING`: a new archive was collected at least 15m after the target but the exact grid/source is missing, failed, stale or semantically incompatible. `MATURE`: exact closed coverage exists after actual target time. The report exposes `horizon_elapsed`, `refresh_after_target`, `data_coverage_complete` and reasons. No outcome is backfilled from an earlier analysis time, and no incomplete day is rounded to 24h.

Numeric strings preserve Decimal arithmetic. Percent units mean percent; relative changes use fraction units. A zero baseline gives null relative change. As-of age never becomes known provider latency. Images/null matrices are not converted into zones or trading labels.

There is no timestamp override CLI. Private clock injection exists solely for clearly synthetic temporary-file tests; production outputs use the actual clock. All reports retain `order_permission:false`, with no prediction, PnL, primary or shadow-label generation.

```powershell
python -B -m unittest discover -s research/coinglass_daily_context_20261016 -p test_analytics_daily.py -v
```

See `ANALYTICS_ASSUMPTIONS.md` for frozen definitions. Root owns integration with the daily protocol/automation and the shared manifests.
