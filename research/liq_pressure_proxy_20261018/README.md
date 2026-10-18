# LPX-A0: offline reference kernel, not a completed research pipeline

The frozen specification is `PROTOCOL.md`, `MODEL.md` and their original
`PREREGISTRATION.json`, with explicit `AMENDMENT_001.md` and
`AMENDMENT_002.md` and their registration files. The original files were not
rewritten. All four specification SHA256 values are checked by the kernel.
No real market dataset, liquidation label or account information has been
loaded by this implementation. Only invented synthetic tests were run.

This models a two-sided native-OI pressure proxy. It does not reconstruct
CoinGlass Model 1, identify actual positions or leverage, predict price,
calculate PnL, grant trading permission or authorize Step B. The primary
contrast tests the entire fixed OI construction: positive-OI birth timing
and masses together, against a price-only map. It is not a weight-only test.

## Implemented

- `ProxyState`: equal native-quantity identities on both sides; initially all
  OI unknown; old barrier touches and 24h expiry transfer to unknown; exactly
  one OI contraction; four fixed virtual leverage offsets on new positive OI.
  Newborns cannot be touched by their own birth bar. A previous-end cohort is
  eligible at equality with the next bar start, per amendment 001.
- Exact contiguous closed UTC 5m feature validation. Gaps and unit changes
  reset cold; malformed/duplicate/conflicting input errors clear the segment.
  Warm-up is 288 complete consecutive bars, measured from first bar start.
  Decimal arithmetic is used for mass/price geometry, with the registered
  relative mass identity tolerance 1e-9; price boundaries receive no tolerance.
- Independent price-only unit cohort comparator, detached immutable snapshots
  at fixed anchors, exact 5m or 30m feature cutoffs, known late-receipt refusal.
  No stale endpoint substitution or skipping an unavailable historical bar.
- Up to three display bands per side with deterministic score/distance/price
  ties and strict non-touching intervals. They do not replace scoring geometry.
- All 199 deterministic placebos. Indices 0..198; age measured at feature end;
  LONG then SHORT, ascending age and distance bucket, stable cohort sorting.
  Singleton fraction means number of cohorts in singleton groups / all active
  OI cohorts, not a fraction of groups or mass. Empty-map fraction is null.
- Exact 240 consecutive closed one-minute MARK closes, same realized path for
  all maps. Full connected event-feed spans are required even for zero events.
  Canonical-message count labels, half-open minute assignment, path-conditioned
  log-score, equal mean across defined sides; no messages gives undefined d.
  Uniform-exposure comparison scores are separately descriptive only.
- Adapter-declared Binance target `o.T`, with envelope `E` and optional actual
  receipt separate. Transport-identical duplicate copies can have different
  receipt times; receive min/max/count survive in audit metadata. Conflicting
  canonical identity or unknown schema/side is refused.
- `validation_summary`: equal weighting of defined daily means, fixed 10,000
  whole-UTC-week bootstrap, seed 20261018, explicit evidence gates. Only weeks
  containing a defined day mean enter the bootstrap. Feed-valid no-message
  days/weeks are reported separately. Percentiles interpolate at `(n-1)*q`.
  Deleting the three largest observed message-count anchor episodes is a
  fragility diagnostic; ties use earlier anchor. A positive interval still
  explicitly requires the registered external diagnostics and a new protocol.

## Not implemented / not independently certified

This is a reference kernel with typed Python inputs, not a general CSV reader
or an end-to-end validated data pipeline. The CLI deliberately has no market
input or real-run option. Missing pieces include:

1. A provenance-audited exporter/adapter for historical native OI, trade VWAP,
   closed MARK candles, and exact forceOrder public envelopes. The kernel
   checks declared schema/side/identity fields but cannot certify their truth
   from an adapter-supplied hash or normalized string. It does not manufacture
   canonical identity from matching price, size or time.
2. Raw envelope canonicalization using sorted-key compact UTF-8 JSON while
   preserving original numeric/string types; SHA/adapter versions and actual
   receipt provenance must be produced outside the kernel. Local receive time
   is excluded from canonical identity. `Message.transport_sha256` is that
   adapter-supplied public-envelope digest, not a guessed economic trade ID.
3. Connection/heartbeat coverage reconstruction, historical schema/side repair
   audits, official contract-unit verification and complete input inventories.
   `ConnectedSpan.provenance_ref` is a required declaration/reference, not proof.
4. Calendar eligible-span discovery; frozen first-60%/last-40% whole-week split,
   240m purge and immutable `RUN_PLAN.json`; full planned/missing/excluded anchor
   journal. The aggregate function assumes its caller has supplied ONLY that
   preselected validation set of valid-path/feed anchors, retaining valid zero-
   message anchors as `ScoreRecord(..., anchor_d=None, 0, 0)`.
5. A batch runner joining inputs, generating both lags/all placebos, exporting
   cohort and active/unknown ledgers, LONG/SHORT aggregate results, input/code
   hashes and complete run-level audit artifacts. Pure functions can produce
   individual components; this is not evidence those joins/exports work.

No real-data result is authorized by successful unit tests or a positive
invented bootstrap. Existing pilot/daily journals, bots and orders are untouched.

## Input contracts for a future authorized public-data export

- `FeatureBar`: exact `start_ms/end_ms`, OHLC, positive base/quote volume,
  native `oi_quantity`, documented `oi_unit`, optional actual `received_at_ms`.
  VWAP = quote/base, within OHLC. One source unit per contiguous segment.
- `MarkMinute`: exact future `[start_ms,end_ms)` grid, positive MARK close,
  `price_kind="MARK"`, `closed=True`. Trade-price bars are not primary substitutes.
- `Message`: canonical ID, public-envelope SHA256, schema
  `binance_usdm_force_order_snapshot_v1`, normalized position side LONG/SHORT,
  venue BINANCE / product USD-M / symbol BTCUSDT; `event_ms=o.T`,
  `envelope_event_ms=E`, `event_time_field="o.T"`, optional actual receipt.
  Messages supplied to a score must lie inside its half-open 240m window.
- `ConnectedSpan`: known valid connected source intervals covering the complete
  target window, schema/channel/source fields and nonempty provenance reference.
  Absence of messages is not a substitute for connected-span evidence.

An authorized Mac operator would need to export already recorded PUBLIC data
and these metadata/coverage facts, not account records or secrets. This package
does not contact Mac, start recording, fetch exchange APIs, or require the user
to run new services. Unknown legacy provenance remains NOT_ASSESSABLE.

## Reproduce synthetic checks only

Run from `C:\bot7\research\liq_pressure_proxy_20261018`:

```powershell
& 'C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B proxy.py --verify-registration
& 'C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B -m unittest -v test_proxy
& 'C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B -m unittest -v test_proxy qa_ownership.test_independent
& 'C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B proxy.py --synthetic-demo
```

These commands use only stdlib, local frozen specification and invented fixtures.
They do not read an arbitrary input directory, access the network or create a
market report. `QA.json` records the actual synthetic check; `CODE_MANIFEST.json`
pins code/tests and specification after checks and before any future real use.
The final combined check passed 37 tests (33 core plus four independently
written synthetic QA tests). No historical market effect was calculated.
