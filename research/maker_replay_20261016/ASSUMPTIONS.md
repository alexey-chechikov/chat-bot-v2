# Frozen before replay: 16 October 2026

This is an offline sensitivity model of received public messages. It is not evidence of actual maker fills, FIFO, exchange latency, executable profitability, or the actual price of turnover. No network, account/config/keys, live collectors, processes, Mac or Claude are used. Source files are immutable.

## Frozen inputs

| Input raw sidecar | Full file SHA256 | Accepted frames |
|---|---|---|
| `../weex_public_capture_20261015/market_capture_001/ordered_public.jsonl` | `59fba38efbee9626f3b321b192712403d58ecc4481b8fa1a3b0f442dfc83a5be` | all 2215 frames |
| `../weex_public_capture_20261015/capture_24h_001/chunk_000001/ordered_public.jsonl` | `7453c5d2214def73705b108e2fb0015a50f630537ad4e47693f88042b4183af0` | `receive_seq < 5283`; common raw/CSV committed prefix |

The second input is an intentionally stopped historical fragment, not 24 hours. No collector status or process is inspected. Its raw tail after the common prefix is excluded. Neither source supports a full 15-minute holding follow-up for a newly entered position.

## Timeline and data rules

- Local elapsed `recv_monotonic_ns` plus global `receive_seq` define observed receive order. Each frame is atomic. Trade rows are aggregated by exact price and raw side; no strategy action occurs between rows. Payload batch order is not engine order: execution timestamps frequently decrease inside a batch.
- `tradeSnapshot` is bootstrap only. Seen snapshot/live IDs are deduplicated in receive order; a later snapshot does not remove an earlier live event. IDs are strings, not a numeric completeness sequence. Missing/invalid/conflicting fields invalidate coverage rather than imply zero flow.
- Raw `m=True` is treated as seller taker; `False` as buyer taker. This follows the reviewed recorder's interpretation, not independent execution verification. Side, quote acceptance and quantity units remain assumptions; current official docs are not fetched for this offline run.
- Arrival uses the latest received book, at most 1000 ms old, with 15 positive levels on each side and continuous WEEX-style `U == previous u`. A depth loss/stale event triggers cancellation and risk liquidation without resetting inventory or pending orders. Unknown execution is retained and flagged.
- Prints received after virtual ACK may have executed before that ACK: E-T batching reaches about 696 ms, and exchange and receive clocks differ by about 5.4 seconds. No clock shift is invented. All modeled passive fills carry this unresolved ambiguity; even the first eligible subsequent frame does not prove engine causality.

## One frozen strategy, no optimization

ETH long only; one sequential episode, no simultaneous bid/ask strategy, hedge, self-trade or wash behavior. From FLAT, quote up to USD 30 at observed best bid, at most one new attempt per 5 seconds, spread <=3 bp. Quantity is continuous; historical step/min-notional/filters are unknown. Entry POST_ONLY, TTL 5 seconds from submit request. A first partial triggers cancellation of the remainder; late fills remain possible until virtual cancel ACK. Only after terminal entry ACK submit one reduceOnly TP at +8 bp from entry price. TP price uses an explicit inferred/assumed ETH tick of 0.01; this is not verified historical metadata. Stop 25 bp and maximum age 15 minutes from first fill; both remain active during pending/cancel states.

Submit and cancel latency scenarios are paired 100/500/1000 ms. Queue scenarios use 0x and 1x displayed quantity at the exact price at virtual ACK. They are scenario choices, not mathematical bounds on real fills. No credit is granted for L2 shrink/cancellations. Only same-price opposing observed live prints consume queue and remaining order quantity, once. If a price is not visible at ACK, queue is unknown: no passive fills are modeled for that order, and this censoring is reported. No fill is inferred from price-through prints.

Marketable POST_ONLY at arrival is rejected. Entry rejection finishes a no-fill attempt; TP rejection triggers risk liquidation. A risk exit cancels all own outstanding orders, waits for ACK, then submits one taker liquidation after the submit delay, walking fresh visible depth. Exposure continues until liquidation. If fresh/sufficient depth is unavailable, inventory remains unresolved and costs are incomplete.

Known dataset end is a research boundary: stop opening and initiate cancellation `cancel_delay + submit_delay` before the last accepted frame, so a terminal taker exit can be modeled at the end using fresh depth. Such episodes are explicitly truncated and separate from completed episodes. This endpoint policy is not a deployable signal.

## Accounting and interpretation

Maker and taker fee are each an assumed 1 bp of each modeled fill. No actual fee tier/rebate is claimed; funding is unavailable and set to zero only as an explicit scenario. Notional turnover = sum(abs(qty)*price) over modeled fills, never submitted/canceled orders. Scenario cost/M = -(sell value - buy value - fees)/turnover*1e6 only when inventory is flat. Incomplete inventory gives null, not free FLAT. Markout is signed future received-mid movement at 1/5/30/60 seconds, descriptive and not an additional PnL deduction. No slippage/markout is double counted. Market impact, hidden liquidity, real FIFO, complete trade feed and unseen depth are not known.

Required before actual turnover economics: calibrated anonymized send/ACK/cancel/fill and cash-fee records; versioned contract filters and funding; multiple complete days/regimes with verified coverage. Short-fragment scenario results cannot establish expected profit.
