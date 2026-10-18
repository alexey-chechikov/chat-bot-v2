# WEEX public replay: finite quality audit

This is a data-quality result, not a maker-profitability result.

Both Release asset SHA256 values and all 24 internal CSV hashes match. Internal and external manifests are identical. CSV schemas, row counts and newline termination were checked. Raw files remain local.

| Symbol | UTC day | Sequence coverage, receive clock | Receive silence <=2s | <=5s | <=30s | Start snapshot prewarmed |
|---|---|---:|---:|---:|---:|---|
| BTCUSDT | 2026-10-16 | 99.82070255% | 37.44934954% | 45.46928819% | 86.02561227% | True |
| BTCUSDT | 2026-10-17 | 99.92630208% | 38.60104745% | 46.28126157% | 85.54353009% | True |
| ETHUSDT | 2026-10-16 | 99.82070602% | 36.80281366% | 44.01751852% | 83.82359028% | True |
| ETHUSDT | 2026-10-17 | 99.92659606% | 38.04865278% | 44.92260995% | 84.16158333% | True |

Sequence coverage is structural book availability between valid snapshot/updates and resets. It does not establish current quotes. Receive-silence columns additionally exclude quotes after 2/5/30 seconds without another depth update; these are explicit audit sensitivities, not exchange SLAs, true market-state age, or percentages of lost exchange messages. Buffered rows may already be old when received. Connection failures and a missing initial snapshot are excluded independently. report.json has compact exclusions and clock distributions; full intervals are local/quality_details.json only.

| Symbol | Depth rows | Applied=0 | Sequence/replay disagreements | Crossed/locked rows | Trades | Duplicate IDs |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 602790 | 25 | 0 | 0 | 1596608 | 0 |
| ETHUSDT | 602785 | 0 | 0 | 0 | 1678364 | 0 |

## Receive timing and event ordering

- BTCUSDT: receive-gap p50/p95/p99/max = 1/544/12582/198968 ms; recv minus E min/median/p99/max = -118/11957/138130/299482 ms. This combines transport/backlog and unmeasured clocks; it is not provider lag.
- BTCUSDT: 544466 trade timestamp decreases, 544465 with identical E/recv/session. Preserve source order and availability; do not globally sort by trade T and pretend earlier availability. The initial 14279 applied rows cannot be replayed without the missing pre-export snapshot; first available snapshot 2026-10-15T01:59:14.273+00:00.
- ETHUSDT: receive-gap p50/p95/p99/max = 1/528/11500/180474 ms; recv minus E min/median/p99/max = -118/11976/138234/299399 ms. This combines transport/backlog and unmeasured clocks; it is not provider lag.
- ETHUSDT: 581595 trade timestamp decreases, 581595 with identical E/recv/session. Preserve source order and availability; do not globally sort by trade T and pretend earlier availability. The initial 14278 applied rows cannot be replayed without the missing pre-export snapshot; first available snapshot 2026-10-15T01:59:14.274+00:00.

## Limits before maker replay

- No exchange confirmation of contract quantity unit/multiplier, tick or quantity step; exported specs came from bot configs.
- m_raw buyer-is-maker interpretation is declared by recorder but not independently confirmed in this audit.
- Depth15 is partial L2, not an order-level queue. No order acknowledgements, cancellations or queue position are observed.
- Capture connection windows and valid depth do not prove a complete trades census.
- Receive clock NTP error is unmeasured; receive minus exchange timestamp mixes clock difference and transport.
- The 2/5/30-second receive-silence tests limit time since a depth row arrived, not the true age of its market state; buffered rows may already describe an older market.
- Messages arrive in bursts, with substantial receive-time silence even when exchange E advances regularly. Event-time continuity is not executable receive-time freshness.
- No global receive ordinal/message batch identifier is stored. Cross-stream ties and exchange-time ordering within recorded trade batches cannot be resolved into an observed execution queue.
- Day 18 is an intraday copy while capture continued; end-of-file is administrative censoring, not a disconnect.
- No new fills, probabilities, trading/PnL result or live-state/deployment verification is calculated.

## Reproduce (Python standard library, offline)

Download the two pinned assets from the linked Release into local/ using the approved public download path. Run:

```text
python -X utf8 -B verify_replay.py --local-root local --out-root .
python -X utf8 -B -m unittest -v test_verify_replay
```

No production imports, Mac access, API calls, account access or model fitting are performed by the verifier. Synthetic tests cover gaps/resync, stale quotes, cross-day prewarm, missing snapshot, invalid level values and interval boundaries.
