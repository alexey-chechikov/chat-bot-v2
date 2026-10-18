# ETH causal PRICE/MARKET replay: pre-registration — 15.10.2026

Written before calculating any new replay return. One fixed candidate only:
ETHUSDT `intraday_impulse_follow`, z2.5, 15m signal, 60m impulse,
minimum absolute move 0.6%, volume ratio >=2, horizon 120m, stop 0.9%,
target 1.8%. No parameter search, new filters or direction selection.

The selected Binance USD-M period and the source 174-trade ledger have already
been viewed and used for selecting this candidate. This is NOT an OOS test,
WEEX replay, maker queue model or permission to trade.

## Inputs and signal comparability

Read the existing native Binance ETHUSDT 1m candles, funding and selected
174-trade benchmark. Independently reconstruct the original closed 15m onset /
side-change signals, 121-minute cooldown, and full 120-minute available horizon.
Compare timestamps and sides exactly to the old ledger BEFORE computing replay
returns. If the complete reconstruction differs for an unexplained reason,
stop and report non-comparability; do not silently choose an alternative signal
set. Timestamp conversion uses explicit milliseconds (pandas3 resolution safe).
All 1m timestamps must be unique, aligned and increasing; a needed missing minute
fails closed, and no later available minute replaces an exact scheduled entry or
expiry. Input file hashes are saved in INPUT_MANIFEST.json before the replay.

## Causal execution and sizing

- t0 is the closed signal's end, also the next exact 1m open; no pre-close entry.
- One position, fixed original signal calendar and cooldown; no averaging,
  delayed entry, extra entry or maker fill inferred from a candle touch.
- Stop and target are rebuilt from this scenario's actual entry, active from
  entry. Deadline is EXACTLY t0+120m and exits at that minute's open before its
  later high/low. Known gap open is processed before minute high/low. Gap through
  a stop uses the worse open; gap through a target gets only target price.
- If both stop and target are touched after the open in one minute, choose stop.
  An intraminute fill's accounting time is minute-end minus 1ms; exact ordering
  of funding within that minute is unknowable. Funding ambiguity is flagged and
  conservatively bounded rather than claimed to be an exact event ordering.
- Research risk budget R=10USDT, max entry notional=1000USDT, constant risk / no
  compounding. Quantity=min(1000/actual_entry,
  10/(0.009*actual_entry + cost_reserve*actual_entry)).
  Reserves are 4bp for base and 8bp for stress and are NOT additional cash costs.
- No dated Binance/WEEX contract metadata has been supplied or verified here.
  Quantity is therefore a clearly labelled CONTINUOUS diagnostic, not an
  executable rounded order. No invented tick, lot step or minimum is imposed.

## Four separate scenarios, no double counting

1. static_all_in_4bp: zero execution slip, levels from raw next-open entry;
   net = raw signed q*(exit-entry) minus .0004*entry_notional. NO extra fees,
   funding or slippage. This is a newly replayed PRICE path, not old-ledger
   repricing. All-in assumes a constant total budget, not a guaranteed cost cap.
2. static_all_in_8bp: same raw replay, .0008*entry_notional, reserve8bp.
3. decomposed_fee1bp_slip1bp: adverse1bp at entry and every exit, each actual
   traded notional charged1bp fee; stop/target rebuilt from slipped entry;
   actual Binance signed funding settlements separately. Reserve4bp.
4. decomposed_fee1bp_slip3bp: adverse3bp each side, fee1bp each actual notional,
   stop/target rebuilt from slipped entry and actual signed funding. Reserve8bp.

No additional flat 4/8bp is subtracted from either decomposed scenario. Funding
uses constant q times historical rate times mark price. Position is eligible
only when entry_time < settlement_time <= exit_time. A settlement in a minute
with an intraminute exit has uncertain ordering and must be disclosed with both
cashflow bounds if encountered. Missing/nonpositive funding mark fails closed
for affected trades; no invented proxy is inserted.

## Required outputs and decision scope

Per-scenario complete ledger, minute-close liquidation equity, realized net,
signed gross/fees/slippage/funding, stop/target/time counts, skip/data counters,
mean net on all174 source candidates and on completed trades, peak-to-trough DD
including initial zero and simulated immediate liquidation friction. Conditional
research capital1000USDT is only an accounting reference; report maximum dollar
loss and flag insolvency, not claim a real funded portfolio. Show the three best
net winners and net after removing them as adversarial diagnostics, not modeled
no-fill probability. Calendar-month block CI is descriptive on reused selected
data; no validation claim from N=174 or six months. No cross-family recalculation.

Synthetic tests precede return calculation: exact entry/expiry, gap stop,
same-minute ambiguity, missing minute fail-closed, fixed risk size, cost/funding
separation and funding ordering. Source ledgers are not modified. No network,
account, secrets, bots, Mac, Claude, collector or git mutations are needed.
