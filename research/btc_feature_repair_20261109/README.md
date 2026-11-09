# BTC repair and loss-ranking lab — 2026-11-09

Pinned original experiment: `762ec6f8124cb499a7104fd74544887190d04acb`.
This directory contains public historical research results, not actual account
trades. No task here changes orders, starts services or installs a collector.

Start with `../../docs/WEEX_GPT_BTC_REPAIR_AND_LOSS_RANKING_2026-11-09.md`.

## Results

- `results/trade_repair_all.csv`: every one of 973 matched closed trades.
- `results/trade_repair_actual_affected.csv`: 250 rows with changed data/path or
  recorded funding clock. These are not 250 changed trading profits.
- `results/trade_repair_affected.csv`: expanded 345 rows, including the isolated
  hypothetical basis-add funding error. Scope flags distinguish these cases.
- `results/trade_table_btc_corrected.csv`: repaired research table.
- `audit_bad_trades_*`: fixed entry risk model, all 973 scores and factor ranks.
- `preentry_*`: eight additional fixed pre-entry axes, 653 Binance observations,
  32 descriptive comparisons and five chosen loser/winner trajectories.
- `progress_*`: as-of states at 4/12/24 actual hours, one fixed 24h model and
  funded evaluation of its unchanged seven exit actions.
- `funding_candidate_*`: all population, calendar, influence and cashflow
  controls of the positive funding7d short-blue sizing candidate.
- `funding_sizing_equity*`: fixed-signal, per-leg quantity/MTM replay of that
  exact calendar policy, all 288 closed test trades; no new model or threshold.
- `results/bad_trade_paths.png`: four selected, retrospective price-path pairs.

## Targeted tests from repository root

Use Python 3.10+ with numpy, pandas, scipy, sklearn and pytest. The numeric run
used Python 3.10.12, numpy 2.2.6, pandas 2.3.3, scipy 1.15.3 and sklearn 1.7.2.

```text
python -X utf8 -m pytest -q tests/services/btc_signals tests/research_tools/test_features_ext.py tests/research_tools/test_btc_funding_repair.py tests/research_tools/test_btc_path_repair.py research/btc_feature_repair_20261109/test_replay_cashflows.py
```

83 tests passed in the isolated original-plus-repair checkout. On Windows the
UTF-8 option avoids the existing locale-sensitive journal encoding. Use a new
workspace-local pytest basetemp if the OS sandbox cannot rename in system Temp.

## Rebuild the numeric replay

The large raw histories and trusted internal `replay_cache.pkl` are not stored
in Git. Provide a `BTC_REPAIR_DATA` directory containing these original public
source schemas (see the source manifests and inventory for hashes/coverage):

- `spot_BTCUSDT_1h.csv`: ms, open, high, low, close, volume; pre-entry flow also
  requires taker_base from this cache.
- `bitstamp_btcusd_1h.csv`: timestamp in seconds, open, high, low, close, volume.
- `um_BTCUSDT_funding.csv`: ms, rate as a decimal fraction.

`spot_hour_tail.csv`, `funding_tail.csv` and `target_exit_minutes.csv` provide the
small supplementary public slices already checked for this run. Rebuilding does
not need to run the optional network script `data_repair_fetch_missing.py`.

`replay_paths.py` finds the repository root automatically. Set
`BTC_REPAIR_OLD_SOURCE` to an existing original source directory if desired;
otherwise only the eleven needed pinned inputs are extracted with local
`git show` into ignored `original_source/`. Lazy fetching is disabled. Missing
Git objects cause a clear offline error, not an implicit network request.

From repository root, after setting the data environment variable:

```text
python -X utf8 research/btc_feature_repair_20261109/build_replay_cache.py
python -X utf8 research/btc_feature_repair_20261109/replay_comparison.py
python -X utf8 research/btc_feature_repair_20261109/repeat_findings.py
python -X utf8 research/btc_feature_repair_20261109/audit_bad_trades.py
python -X utf8 research/btc_feature_repair_20261109/progress_review.py
python -X utf8 research/btc_feature_repair_20261109/progress_funded_evaluation.py
python -X utf8 research/btc_feature_repair_20261109/preentry_review.py
python -X utf8 research/btc_feature_repair_20261109/funding_candidate_review.py
python -X utf8 research/btc_feature_repair_20261109/funding_sizing_equity.py
python -X utf8 research/btc_feature_repair_20261109/plot_bad_trade_paths.py
```

Individual scripts save their own results. Preserve the pinned original
forecasts if comparing hashes: re-running in another sklearn version can alter
numeric fits even if code and parameters are unchanged.

## Interpretation limits

`manifest.json` records tested Windows core bytes and LF-normalized published
core content separately; individual result JSON hashes refer to their recorded
input snapshots. Lab artifacts are published byte-for-byte.

Funding uses same-clock spot-close price proxies. Strict funded results are
missing for unsupported inception/venue or unresolved coverage. The observed-only
benchmark is not complete net when support is missing. Initial close entries
exclude same-time funding; already-standing intrabar adds precede close funding;
target exits precede exit-hour-close funding. Funding precedes standing orders
at the same hour open. These are explicit replay conventions, not actual fills.

Minute OHLC narrows the exit interval but does not establish tick order. Four
Bitstamp MAE paths remain bounded/unknown. Factor rankings, chosen case pairs,
monthly intervals and temporal splits are exploratory on already studied data.
The entry risk filter and fixed 24h exit model did not improve net; the funding7d
size candidate has a positive research result, not an approved trading change.
