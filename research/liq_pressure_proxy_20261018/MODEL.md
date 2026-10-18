# LPX-A0 model mechanics — fixed before implementation

This is a two-sided OI pressure proxy, not reconstructed CoinGlass Model1 or observed liquidation positions. It uses virtual offsets and native OI units only. No true maintenance margin, liquidation fee, cross collateral or historical leverage distribution is inferred. Consequently the virtual levels are NOT labelled exact liquidation prices.

## State and updates

Per side LONG and SHORT maintain unknown mass U>=0 and active cohorts (birth_end_ms, virtual_level, mass>=0). Identity after every accepted bar: U+sum(active masses)=observed native OI Q for EACH side. The two identities do not mean that 2Q distinct contracts are open; a contract has both sides.

On first valid bar, initialize both U=Q and no active cohorts. No fictional past entries are assigned to existing OI. A gap resets both proxy and comparator to this cold state and restarts the 24h warm-up. Future signals from an incomplete segment must remain missing, not an empty valid map.

For a subsequent contiguous closed 5m bar [t-5m,t):

1. Process only cohorts born before this bar began. A LONG barrier retires when low<=level, including a gap open below it; SHORT when high>=level, including a gap above it. Transfer all retired mass into the SAME side's unknown pool; do not subtract it from total OI and do not call this an observed liquidation. A cohort whose age at t is >=24h also transfers to unknown. Track touch versus expiry, without double counting a cohort.
2. Let old OI=Q_old and new OI=Q_new. If Q_new<Q_old, multiply every active cohort AND U on each side by Q_new/Q_old exactly once. If Q_old=0 and Q_new=0 retain empty state. Negative Q is invalid.
3. If Q_new>Q_old, allocate Delta=Q_new-Q_old to EACH side: four cohorts of Delta/4 at the current closed bar's trade VWAP E, with leverages [10,25,50,100]. LONG levels E*(1-1/L); SHORT E*(1+1/L). New cohorts are born at bar END t and cannot be touched by that bar's earlier high/low. No leverage fitting or aggressor-based split.
4. Check the per-side mass identities within tolerance 1e-9*max(1,Q). Unknown mass can dominate; report the active fraction rather than pretending the proxy explains all OI. Zero/negative volume when a VWAP is needed, bad OHLC, missing time or units is invalid.

With constant OI the model cannot observe opening/closing replacement activity: retired mass remains unknown and is not automatically reborn. This is a disclosed identifiability limitation. Current market price used as a reference cannot restore lost positions. Floating point implementation must be deterministic and disclose tolerance; exact equality at a threshold counts as a retirement.

## Price-only comparator

Use the same contiguous closed 5m bars, VWAP, virtual offsets, retirement rules and 24h lifetime. Initialize no cohorts on the first bar; on EACH subsequent valid bar add total unit mass 1 to each side, allocated 1/4 to the four offsets, independent of OI, aggressor or future liquidation events. Touch/expiry removes comparator cohorts without an OI reconciliation. The score normalizes total exposure, so units need not match the OI map. This comparator intentionally retains price history and survivor geometry while omitting OI weights and OI-positive birth timing.

## Snapshot and scoring geometry

At the fixed UTC anchor use only the complete feature prefix admitted by PROTOCOL.md availability rules. Freeze cohorts; subsequent bars and labels cannot modify that frozen object. Primary scoring uses ALL active levels and half-width 0.0025 relative to EACH level: price x belongs iff abs(x/level-1)<=0.0025. Use the same future MARK-close sequence for both models and all placebos. Equal one-minute exposure is path conditioning for evaluation, not a causal future feature.

Descriptive top bands: reference price is the last admitted feature close. Candidate centers are reference_price*(1+j*0.001), integer j=-100..100 excluding zero. LONG candidates below reference and SHORT above reference only. Candidate weight is the sum of same-side active mass in its relative +/-0.25% band. Consider positive scores only. Greedily select at most 3 per side, descending score, then absolute reference distance, then center price; require the selected absolute price intervals not to overlap or touch. Fewer than3 is allowed and explicitly counted. Do not substitute bands after observing future price. These display bands do not replace the full scoring surface.

## Frozen placebo algorithm

199 replicates per snapshot. Within each side, group active OI cohorts by age hours [0,1),[1,4),[4,12),[12,24] and absolute distance from reference in percent [0,.5),[.5,1),[1,2),[2,3),[3,5),[5,10],outside10. Permute ONLY mass values among cohorts in a group; preserve levels, births, count and total group mass. Singleton groups remain unchanged and their fraction is reported. Sort cohorts stably by (birth,level,mass) before permutation. Replicate seed is the integer represented by the first16 hex digits of SHA256('LPX-A0|20261018|'+snapshot_id+'|'+replicate_index). Use local random.Random(seed), never Python process hash or a shared/global RNG. No seed search. No future path/event is used for grouping or permutation.

## Integrity and scope

Record fixed parameters and this file's SHA with every run. Code and tests are frozen separately after synthetic verification and before a real-data pass. A failed mass identity, an unknown source schema, a changed parameter or a feature after the permitted cutoff is an error, not a repair opportunity inside an existing run. Revisions require a new version and fresh registration before targets. This model does not change any existing bot, dataset, protocol or journal.
