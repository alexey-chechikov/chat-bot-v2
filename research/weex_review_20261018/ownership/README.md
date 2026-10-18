# WEEX ownership / history audit — 18.10.2026

Read-only audit of GitHub source at alexey-chechikov/chat-bot-v2@1d0da80863226acda8fdf57d07eee087fc08ef2c.
Relevant changes: multigrid 6912e1c, legacy monitor classification 125f4c7.
The deployed Mac version, live orders, account balances and provider behaviour were NOT verified.
No source/module from this bundle should be imported into the live bot.

## One-command offline reproduction

    & 'C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B 'C:\bot7\research\weex_review_20261018\ownership\audit_ownership_offline.py'

Requires only the Python standard library. Reads three inert .py.txt GitHub source
snapshots, verifies their SHA256 AND Git blob SHA, extracts only allowlisted function
definitions via AST, and executes those functions against synthetic objects.
It does not execute source imports, module initializers, constructors, network methods,
or account reads. Its only output write is ownership/results.json.
The file creation timestamp is the real rerun timestamp, not an observation timestamp.

Observed result on this host: exit 0; six reproduced cases; three verified sources;
zero network requests; zero production imports; zero real account inputs.
This means assertions reproduced the reviewed behaviour, not that the bot passed safety checks.

## Findings and scope

### P1: malformed trade row can release a lost-entry pending

services/weex_grid/engine.py:828–833 validates only list[dict].
engine.py:787–789 skips a row with absent orderId without marking the search incomplete.
After TTL and two negative history reads, engine.py:894–914 therefore accepts a false
complete negative result and removes pending.

Synthetic trace: history is a valid empty list, pending t=800, now=1000, prior absent=950.
The trade row has id/side/positionSide/qty/price/time but no orderId.
Trade search returns (None, True); resolve returns True; pending becomes null.
The next normal pass may permit a duplicate entry above an unaccounted first fill.

This is conditional on malformed provider input. The audit did not establish that WEEX
currently returns such rows. The existing defensive contract is nonetheless violated:
unreadable evidence is treated as proof of absence.

Minimum regression test: missing/empty orderId in any returned trade row retains pending,
does not count as a complete absent read, and does not permit a new entry.

### P2: twenty unresolved neighbours starve the own twenty-first order

engine.py:785–811 starts from the same first rows on every attempt.
Only valid foreign details enter the persistent foreign cache.

Control: twenty valid neighbours followed by the own order -> found in two attempts,
21 detail calls total. Counterexample: the first twenty details always unknown ->
100 attempts, 2,000 calls, own order never queried, cache stays empty.
This fails closed rather than adopting a neighbour, but a filled own entry can remain
without its recorded lot/take profit.

Minimum test: persistent round-robin progress reaches the own order after unresolved
neighbours, while unresolved rows never establish a complete negative result.

### P2: foreign trade fees and the 100-fill cap

engine.py:476–492 and 541–553 sum every returned commission without validating orderId,
deduplicating trade IDs or proving response completeness.
services/weex_api/client.py:196–206 uses limit=100, without pagination.
These paths predate the multigrid change; they are not claimed as a new regression.

Synthetic wrong-provider-response case: request OWN, return NEIGHBOUR commission 7 ->
OWN receives fee 7. This does not prove WEEX ignores the requested orderId.

Synthetic dense-order case: 101 own fills, commission 0.01 each, latest-100 API response ->
recorded fee 1.00 instead of 1.01. A later unchanged 100-fill response allows the cursor
to expire silently after the fee window. No incompleteness warning is emitted.

Minimum tests: reject wrong orderId without moving the cursor; duplicate fill IDs cannot
double-charge; exactly 100 returned fills require a completeness strategy; expired partial
fee history cannot be labelled fully settled.

### P2 configuration guard: L/S are documented reserved but accepted

engine.py:132–146 accepts tag L; 181–191 checks only current tag collisions.
Old BTC CID b7gLe17600002 begins with the new L-grid prefix b7gL.
research/weex/weex_monitor_common.py:174–179 tests other-grid prefixes before legacy format,
so BTC monitoring labels that historical CID OTHER if an L peer is configured.
Current tags 3/4/8 do not trigger this problem.

Minimum tests: reject newly assigned L/S, both cases, while preserving explicit
historical BTC ownership.

### Boundary contract: conditional risk, NOT a confirmed WEEX bug

engine.py:739–766 partitions inclusive integer milliseconds as [a,m] and [m+1,b].
There is no arithmetic gap under that contract.
The current realistic-history fake assumes inclusive endpoints.

Synthetic tests at a=0,m=2000,m+1=2001,b=4000 all succeed with inclusive ends.
With end-exclusive API semantics, a row at m is missed while search is marked complete.
This demonstrates why endpoint semantics must be established, not that real WEEX is exclusive.
Consider overlapping child windows and deduplication if the provider contract remains unknown.

## Paths that held under the reviewed assumptions

With distinct current tags, correct API responses and uncontaminated state,
the reviewed lookup paths did not directly adopt/cancel a neighbour:
self.open filters the own prefix; CID lookups require exact CID equality.
Budget exhaustion preserves incomplete status.
Trade-search _detail(oid) has no side, so unresolved neighbours do not enter the
own-side unknown_orders references, though generic issue escalation can still occur.
This limited result is not certification of the live deployment.

## Evidence files

- VERIFIED_SOURCES.json: repository/ref, exact Git blob SHA, SHA256 and byte lengths.
- source_origin.json: GitHub retrieval identity.
- sources/*.py.txt: inert exact source bytes, not executable source imports.
- audit_ownership_offline.py: synthetic reproducer.
- results.json: machine-readable results, source hashes and exact extracted line spans.

No real market/account data are included. No production files were changed.
