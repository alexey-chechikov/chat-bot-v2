# Offline maker sensitivity: 16 October 2026

**Not actual fills, actual cost/M, or expected profit.** Frozen assumptions: ASSUMPTIONS.md. Fee 1 bp per modeled leg, zero funding assumption; historical filters and queue/latency are uncalibrated.

| Capture | Delay ms | Queue factor | Filled episodes | Truncated | Unknown queue orders | Complete-scenario cost/M | Truncated-scenario cost/M |
|---|---:|---:|---:|---:|---:|---:|---:|
| five_minutes | 100 | 0 | 1 | 1 | 2 | n/a | -1327.77 |
| five_minutes | 100 | 1 | 0 | 1 | 10 | n/a | n/a |
| five_minutes | 500 | 0 | 1 | 1 | 1 | n/a | -1290.64 |
| five_minutes | 500 | 1 | 1 | 1 | 13 | n/a | 577.08 |
| five_minutes | 1000 | 0 | 1 | 1 | 2 | n/a | -1412.37 |
| five_minutes | 1000 | 1 | 0 | 1 | 12 | n/a | n/a |
| old_chunk_common_prefix | 100 | 0 | 1 | 1 | 1 | n/a | 204.51 |
| old_chunk_common_prefix | 100 | 1 | 0 | 1 | 1 | n/a | n/a |
| old_chunk_common_prefix | 500 | 0 | 1 | 1 | 1 | n/a | 204.51 |
| old_chunk_common_prefix | 500 | 1 | 1 | 1 | 1 | n/a | 20.07 |
| old_chunk_common_prefix | 1000 | 0 | 1 | 1 | 1 | n/a | 204.51 |
| old_chunk_common_prefix | 1000 | 1 | 1 | 1 | 2 | n/a | 20.07 |

The two inputs are about five and twelve minutes; no filled episode has full 15-minute follow-up. Boundary closes are separated, and unavailable markout horizons are blank. Zero fills means no modeled executed turnover, not zero cost. Unknown TP queues are censored with a no-modeled-passive-fill policy, not assumed empty.

Risk guards are checked on every received frame, state reconciliation and fill, including first position creation. A stale held position initiates cancellation even without another book frame. A late fill already below the current fresh stop initiates risk liquidation instead of placing TP. Unpriceable exits retain unresolved inventory. See test_replay.py and qa.json for verification; risk_guard_revision.json records changes from the pre-fix run.

All passive fills are ambiguous with respect to real engine ACK ordering. Trade batches are atomic; no L2 shrink grants queue progress; same-price volume is consumed once. Scenarios are neither estimates nor mathematical bounds on actual fill probability or actual economic results.

Files: scenario_report.json; per-scenario *_ledger.csv, *_fills.csv and *_episodes.csv. Replay is reproducible with `python -B research/maker_replay_20261016/replay.py`; tests with `python -B -m unittest discover -s research/maker_replay_20261016 -p test_replay.py -v`.
