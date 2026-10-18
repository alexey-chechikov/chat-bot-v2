# Finite public history collector — review candidate

18 October 2026. `history_fetch.py` is a standalone Python standard-library helper. It has not been activated or run against market endpoints during implementation. Existing daily helpers, VERIFIED_FILES, archives, notes, automations and the pilot journal remain unchanged. Activation and replacement of the old daily public fetch await independent review of the complete package.

## Purpose and fixed request plan

One explicit invocation makes at most six public REST GET attempts, with no retry, redirect, proxy, authentication, account endpoint, WebSocket, daemon or background collection:

| Request | Fixed product and data | Bound |
|---|---|---|
| `/fapi/v1/time` | Public Binance clock | Once; failure skips every dependent request |
| `/api/v3/klines` | Binance BTCUSDT spot, 15m | 384 bars, one trailing 96h window |
| `/fapi/v1/klines` | Binance BTCUSDT USD-M perpetual, 15m | Same 384-bar window |
| `/futures/data/openInterestHist` | BTCUSDT, period 15m | 385 window endpoints |
| `/fapi/v1/fundingRate` | BTCUSDT actual funding events | Trailing 24h; limit 1000; saturation explicit |
| `/fapi/v1/premiumIndex` | BTCUSDT current mark/index metadata | Optional sixth request; not a closed candle |

The common candle cutoff is `floor(min(actual collection-start time, public server time)/15m)*15m`. Thus a server slightly ahead of the local clock cannot admit a locally forming candle. Clock skew is recorded separately from unknown provider lag. More than five minutes of clock disagreement fails the clock dependency; no local-time-only fallback is used.

The fixed 96h history allows ordinary daily and many weekend-delayed outcome checks. It does not guarantee coverage after a longer absence or provider failure. Funding remains a daily 24h source; this helper does not promise historical funding context for the entire 96h. Missing OI or funding does not become zero.

Binance documents maximum spot kline limit 1000 in its [official Spot API reference](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market); the request uses 384. The [official USD-M market-data reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data) documents kline maximum 1500, OI maximum 500, and OI availability only for the latest month; the requests use 384 and 385 respectively. These documentation pages were read on 18 October 2026; no market-data GET was performed during development.

## ABI and compatibility

```python
history, daily_fragment, evidence = collect(
    client, include_premium=True, clock=now_ms, synthetic=False
)
```

`client.get(url)` returns `Reply(status, body: bytes, error=None)`. An injected fake client and clock support offline tests without a socket.

`history` has schema `coinglass-outcome-history-v1`, actual `collected_at_ms`/`finished_at_ms`, the aligned `cutoff_ms`, code SHA256, and extended sources with the old normalized observation field names. Candle sources explicitly declare 384 points and OI 385. Each source carries `legacy_definition`; OI includes the old `row_units` enrichment used by `oi_metrics`, not merely `semantics(source)`. An evaluator must verify this allowlisted definition and actual product/endpoint/settings, rather than trusting a supplied compatibility hash.

`daily_fragment` has schema `daily-as-seen-v1` and only the trailing 96 candle/97 OI points. Its stable definitions exactly match the pinned old helper. The actual larger HTTP query and closure guard remain visible in `settings.request` and `settings.transport`. No extended rows masquerade as a 96-point source. Independent compatibility tests check these hashes:

| Source | Legacy analytic semantic SHA256 |
|---|---|
| Spot 15m | `b576a4dd667ad619a72606e23e3ad53494f007e95dc3c7f60eecaa4552cf3276` |
| Perpetual 15m | `c308f0be9199023e25abc619ef7f2c22d2dab60e5d60fb01471bfd7a512e7bc0` |
| OI 15m with row units | `98406a1e14641a0352c0549efaee345e9085ea26e1c046053e6c549ead8e4d06` |

Equivalent duplicate rows are deduplicated. Conflicting copies are all excluded; the timestamp is retained in `source.conflicting_timestamps` and `settings.validation.conflicting_timestamps` for a CONFLICT outcome. Missing or malformed data are explicit. Older gaps do not spoil an otherwise complete current 24h tail, and their full validation record remains in history and transport metadata. Zero-volume F and buy/sell shares remain null.

The collector imports no old helper at runtime. Parser/client code derives from the old `fetch_public_context.py` SHA256 `74c979e12c7ac095053120be5b71a000650ab58dcb29f652e6c9b19fed495e98`; it was copied only after that hash was checked. Compatibility tests import old fetch and analytics only after checking their pinned SHA256. The analytics pin is `2a71c2e64294b23b7e4efc7234dc76c959d82afcd5b7793b0710670978c51050`.

## Local output and review commands

Run synthetic tests from this folder:

```powershell
& 'C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B -m unittest -v test_history_fetch.py
```

Tests write and remove only generated synthetic temporary directories beneath this new folder's `local/test_temp`; resolved cleanup targets are checked. The native symlink creation test may be skipped when Windows denies that privilege; a separate mocked reparse-point test always exercises the guard.

The following is a future activation command, not a command executed during this implementation. First verify the complete review manifest and replace the old daily public fetch in the agreed protocol, so both helpers are never run as two six-GET collections for one daily job:

```powershell
$taskStamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$taskOut = "C:\bot7\research\coinglass_outcomes_20261018\local\history_$taskStamp"
& 'C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B 'C:\bot7\research\coinglass_outcomes_20261018\history_fetch.py' --run-network --include-premium --outdir $taskOut
```

The explicit absolute output directory must be new or have no own bundle/evidence files. An exclusive CLI reservation precedes HTTP client creation. `evidence/history_*` raw replies and request audits are written without overwrite, followed by `public_sources.json`; `history.json` is committed last. Its presence means a finished bundle, not that every source succeeded. A failed partial directory is never reused; use a new unique directory and inspect the previous failure. Symlink/junction/reparse ancestors and path traversal are rejected. Concurrent writers cannot overwrite a completed bundle.

All raw replies, history and daily fragments stay local. The helper does not read CoinGlass snapshots, account files, trading credentials, bot state or Mac services. A current historical fetch is dated when fetched; it does not manufacture a missed CoinGlass snapshot, past availability, a narrative prediction, a trade-primary observation or profit.
