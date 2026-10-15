# Public OI context: read-only sanity QA — 16.10.2026

Read fetch_oi.py, build_context.py, qa_context.py and README; no fetcher/network
was run by this reviewer. Four synthetic OI tests pass. Read-only qa_context.py
passes:5184raw points=2592BTC+2592ETH,12saved response hashes,1729BTC context rows.
The intersection count is consistent with matching each15m price/flow bar END
to an OI timestamp, including the first bar17.09 23:45→18.09 00:00 and last bar
05.10 23:45→06.10 00:00. No value is forward-filled or interpolated outside
the actual intersection. Original OI quantity and USD value remain separate.

Historical received/publication-lag fields are empty, explicit availability is
UNKNOWN_HISTORICAL_LAG_DIAGNOSTIC_ONLY; lag1/lag4 are sensitivities, not measured
feed delays. Same-end OI is not claimed available to the trader at bar close.

Root separately verified the current primary Binance documentation in this
pass: timestamp is vendor-declared period-end milliseconds. This statement is
attributed to root primary-source verification, not a claim this offline reviewer
browsed or measured historical publication. It is compatible with the unknown
availability label. Current API download time does not prove past receive time.

Scope PASS: public retrospective context/readiness. No CoinGlass matrix,
probability, historical primary freeze, entry signal or trading profit is
created. The0primary /1secondary pilot status remains unchanged.
