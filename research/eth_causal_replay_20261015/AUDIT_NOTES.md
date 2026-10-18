# Final interpretation and comparison audit — 15.10.2026

**Not admitted / not confirmed.** The decomposed low-cost market model has a
positive point estimate, but its CI crosses zero, the stress is negative, and
removing three best winners makes the low-cost result negative. Nothing here
establishes a reliable manual strategy, maker edge or executable WEEX order.

## Why the new static 4bp result differs from the old sensitivity

Same 174 timestamps/sides and raw entry opens. The old sensitivity retained
stop/target levels from an adverse 2bp slipped entry. The new static PRICE replay
anchors stop/target to its own raw entry, as pre-registered before calculation.

- Old static4bp: +44.794213USDT; new static4bp: +56.586161USDT.
- 108 trades have unchanged exit bar, reason and price: zero meaningful delta.
- 53 keep the same exit bar/reason but have re-anchored exit price: -10.582USDT.
- 13 change exit bar and/or reason: +22.373948USDT.
- Total model difference: +11.791948USDT. It is not new unseen evidence.

Examples (zero-based immutable source candidate IDs):

| ID | Side | Old → new exit | Old static net | New static net | Delta USDT |
|---|---|---|---:|---:|---:|
|39|SHORT|stop → time|-9.198200|+5.007484|+14.205684|
|92|LONG|stop → time|-9.201800|+1.157464|+10.359264|
|44|LONG|target → target, same minute, new target price|+17.803600|+17.600000|-0.203600|

Exact prices/timestamps and all174 differences are in legacy_path_comparison.csv
and LEGACY_COMPARISON_QA.json. The two main positive path switches explain why
one must not describe the old-ledger sensitivity and new causal path as the same
execution model.

## Funding and timing boundaries

Exact exit-open/funding coincidence occurs for candidate124 (time exit, LONG).
Potential cash debit is -0.100094181USDT in base and -0.100074169USDT in stress.
Final code gives adverse/no-settlement bounds; conservative net is unchanged.
Stress also has one settlement inside an intraminute exit bar. Overall funding
lower/upper bounds: base -0.417153106 / -0.317058924USDT; stress
-0.385343378 / -0.264925336USDT. No possible credit is treated as guaranteed.

Entry and timed exit at t0 open are idealized zero decision/receive-latency
market assumptions. No BBO, trades, queue or send/ACK timing is available here.
Minute-close liquidation DD includes immediate entry friction and known exit
points; it does not recover the unobserved complete intraminute MTM path.

## QA and limits

17 synthetic tests pass after the funding-boundary and deadline-target-cap clarifications; 14 passed
before first strategy calculation. Signal reconstruction gives 223 raw onsets,
174 after fixed121min cooldown; all174 exactly match benchmark timestamp/side.
Prefix reconstruction, unique contiguous1m coverage and input hashes pass.

174/174 candidates complete in every scenario; no gap or unresolved interval
occurs in the selected native Binance period07.05–06.10.2026exclusive. Each
scenario recomputes its own entry/stop/target/exit. Static4/8bp excludes funding;
decomposed has no flat round-trip debit. Continuous quantity reflects missing
verified historical step/tick, not a rounded executable order. All parameters
stay fixed. No new family, side filter, fee fitting or next-candidate search.

Peer-review correction: at the exact deadline open, a standing target gap is
still capped at its target before timed market expiry. None of the174x4selected
scenario cases has a deadline target/stop gap; final numeric results unchanged.
