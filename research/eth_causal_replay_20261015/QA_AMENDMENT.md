# QA amendment after first replay — 15.10.2026

The immutable README and first code manifest remain unchanged as evidence of
pre-result assumptions. Root review requested checking exact funding timestamp
coincidence with an exit at minute-open. One real selected candidate (#124,
time exit, LONG) has such a boundary. Its cashflow is a debit in both decomposed
scenarios, so the first replay already used the adverse outcome. Nevertheless,
actual event ordering is unknown. The final code therefore marks exact exit-open
coincidences ambiguous and reports lower=min(0,cashflow), upper=max(0,cashflow),
as already done for intra-exit-minute settlements. A 15th synthetic test covers
this boundary. No signal, parameter, price path, quantity or conservative net
result changes. Funding upper bounds increase by the possible avoided debit.

The final code hash is recorded in FINAL_CODE_MANIFEST.json. This is a disclosed
QA clarification of cashflow bounds, not a new parameter search or unseen result.

## Deadline-open standing target cap

Further peer review found that the deadline branch preceded standing stop/target
checks at its known open. A target gap on that exact minute could therefore
receive uncapped favorable open credit. Final code first processes known-open
stop/target with the pre-existing conservative target cap, then time expiry,
then (only before expiry) minute high/low. Two long/short deadline-gap tests were
added. All174x4real scenario ledgers were checked: zero deadline target gaps and
zero deadline stop gaps, so historical prices, reasons and numeric results do
not change. DEADLINE_GAP_AUDIT.json records the check. Final test count is17.
