# Maker replay: independent targeted QA — 16.10.2026

Final reviewed replay.py SHA256:
524fe280965fdb775be766625adefa61a3e8156b19e4a31bd235dbfaf60e3e69.
scenario_report.json identifies this same source hash. **PASS for the declared
offline sensitivity scope, not for actual maker execution or turnover economics.**

## Tests and repaired risk guards

The original17author tests passed, but two independent invented fixtures exposed
missing risk checks: a held position with stale depth and no new depth frame;
a newly received entry fill while the already known fresh bid was below its
stop. Both fixtures originally retained inventory without a liquidation trigger.
The author fixed the shared state/risk check. Final20author tests pass.

Independent final assertions verify all three flows:

1. At1501ms after last book0ms, fresh=false and inventory1 remains tracked;
   liquidating=true with stale_or_invalid_book, pending TP is being cancelled.
2. A first late fill100 with current fresh bid99/stop99.75 triggers stop
   immediately; no TP is submitted and inventory is not erased.
3. Stop-triggered cancellation with entry partial0.4 plus late fill0.3 before
   cancel ACK retains0.7. A further print after terminal cancel does not fill.
   One reduce exit sells exactly0.7; final position0, net=-0.71393 in the wholly
   invented fixture. No double sell, lost partial or duplicate modeled cash.

Initial and final probe JSON are preserved separately. No reviewed source code,
production file or live service was changed by this reviewer.

## Accounting and boundary claims

Read-only cash/boundary checks cover all12alternative scenarios. Fill-level
turnover=sum(price*qty), net=signed cash minus each fill fee; both reconcile to
reported closed/truncated totals. Markouts are not deducted again. Actual cost/M
is null in the top-level report and every scenario. Zero turnover yields no
cost/M rather than a free-volume claim; unresolved inventory cannot produce a
completed flat-profit number.

There are9filled episode INSTANCES across alternative scenario runs, all ending
at the artificial data boundary. None is a completed filled episode before that
boundary; none has a full15min follow-up. These are not9independent market trades:
all scenarios reuse only two short source fragments. Thus report wording that
only boundary-truncated modeled outcomes are available is supported. Positive
or negative truncated cost/M numbers are neither an estimated expected value
nor proof of a deployable exit signal.

Queue0x/1x and delay100/500/1000ms are uncalibrated scenarios, not real fill bounds.
Unknown visible queue is not assumed empty; trade batches are atomic and queue
volume consumed once; cancellation requests remain pending until modeled ACK.
All passive fills retain the disclosed engine-ACK causality ambiguity. Quantity,
price tick, side semantics, funding=0 and fees are explicit assumptions, not
verified historical metadata or actual account economics.

Risk checks now run on received frames/state transitions. This offline module
does not establish an independently scheduled live wall-clock watchdog or a
measured stop/cancel latency guarantee during a completely silent stream. That
is another reason the PASS is scoped to a sensitivity model, not deployment.

Files: independent_probes.py, independent_probe_results.json,
independent_probe_results_pre_fix.json and CASH_BOUNDARY_QA.json. No network,
Mac, Claude, credentials, account state or live orders were used.
