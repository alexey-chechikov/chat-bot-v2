# Step A — LPX-A0, preregistration before calculations

18 October 2026. This is a new offline research protocol, separate from the manual CoinGlass pilot, CG-SR1 and daily-as-seen archives. No market-result calculation has been run under this protocol. Model mechanics are frozen in MODEL.md; both documents receive SHA256 in PREREGISTRATION.json before implementation or target inspection.

## Question and permissible conclusion

Does one fixed OI-derived pressure proxy locate greater concentration of subsequently observed Binance BTCUSDT liquidation messages than a price-history-only proxy, conditional on the SAME subsequently observed price path? This tests an OI-weighting hypothesis, not attraction of future price, CoinGlass Model1 reconstruction, trade profitability, or a live grid switch.

Positive open interest creates equal matched contract exposure on both sides. Aggressor buys do not identify new longs versus closing shorts. LPX-A0 does NOT split OI using taker-buy share. Leverage, entry price, collateral, maintenance tiers and cross-margin are not observable from these inputs. A negative result rejects only LPX-A0 on its specified feed/period; it does not establish that CoinGlass or all liquidation maps are useless. Do not call previously viewed 2026 data untouched OOS.

## G0: metadata and provenance before target scoring

First produce a data inventory without inspecting predictor/target relationships: file SHA256/bytes, schema/adapter code SHA, symbol/venue/product, actual first/last UTC times, expected/observed grids, unit definitions, duplicate/conflict counts, connected feed spans, repairs and coverage. Report actual coverage, not advertised numbers of days. No Mac/account/network access is required by this package; an authorized operator can export already recorded PUBLIC market data.

Primary universe is Binance USD-M BTCUSDT only. ETH, XRP, Bybit and OKX do not enter primary selection or the primary result. They require later separate registrations. Historical OI and events can overlap for only the actually available months; two years of OI are not two years of liquidation labels.

OI uses native quantity, not USD notional. Inputs must use one documented quantity unit throughout; no inference of a contract multiplier from present prices. Features are exact closed UTC 5m bars with OHLC, trade VWAP=sum(quote volume)/sum(base volume), and OI at the bar end. Nonpositive/missing VWAP, bad OHLC, duplicate/conflicting times, a missing grid point or changed units break the segment. Start the next segment with all OI unknown and require 24h of uninterrupted warm-up again. No zero/forward fill/interpolation.

Primary future exposure is exact closed 1m MARK-price closes for the 240 minutes following an anchor. Trade-price candles are not silently substituted for mark. If historical mark data are absent, report NOT_ASSESSABLE for primary; a clearly named trade-path sensitivity may be registered and reported separately, never promoted to primary.

Events must have provenance linking the normalization to a known public feed schema, canonical message identity, event time and normalized position side. Deduplicate only transport-identical canonical messages; conflicting identity or an unknown side/schema is invalid, not no-liquidation. Binance order SELL corresponds to a liquidated LONG and BUY to SHORT only under the documented force-order adapter. Do not use the same side rule for another venue. Binance force-order snapshots are censored messages, NOT a census of positions or all liquidation volume. The primary target therefore counts observed canonical messages, not purported total liquidation dollars. Report optional message-notional totals only as a secondary descriptive field with explicit price/quantity semantics.

Coverage requires connected, valid source spans for the complete future window; inactivity is not evidence of a healthy connection. If the old CSV lacks sufficient coverage/provenance, retain the period in the inventory but mark it NOT_ASSESSABLE. Fixing a parser on 23 July does not prove that earlier files were relabelled. Bybit allLiquidation p is bankruptcy price: do not treat it as a universal trigger/execution price within a 0.25% tolerance.

## Frozen timing and model

Anchors: 00:00/06:00/12:00/18:00 UTC. Primary outcome horizon: 240 minutes, half-open [anchor, anchor+240m); nonoverlapping anchor windows. A feature bar ending at t is used no earlier than t+5m; at anchor a use only bar ends <=a-5m. This is an explicitly assumed historical availability delay, not measured provider lag. If known receive time is later, the bar is unavailable until that time; no unavailable bar is skipped over while pretending the model is continuous. The fixed 30m delay sensitivity must be shown without choosing a favourable delay. Historical results remain retrospective/event-time diagnostics unless actual availability is established.

MODEL.md fixes equal leverage weights 10/25/50/100, virtual offsets, 24h maximum cohort age, unknown pools, one-time OI contraction, barrier retirement, price-only comparator and deterministic placebo permutations. No parameters are selected from liquidation outcomes. Freeze top-three bands per side for descriptive overlap with operator screenshots; these are not the primary scoring surface. A screenshot must have its real receipt/settings/time and unknown publication lag; new annotations cannot be backdated or admitted to the old primary sample. No mandatory new screenshot schedule is imposed on the operator by this protocol.

## One primary statistic: concentration conditional on visited path

For each valid anchor and side s, freeze active proxy cohorts before the outcome. Let x_k be the future minute k MARK close; k=0..239, same path for all comparators. Let u_m,s,k be frozen cohort mass whose level l satisfies |x_k/l-1|<=0.0025, for model m in {OI proxy, price-only}. Visits are evaluated retrospectively only for scoring. No future path enters a stored forecast or cohort update at the anchor.

If sum_k u_k>0, define p_k=0.95*u_k/sum(u)+0.05/240; otherwise p_k=1/240. Thus all methods face exactly the same 240 one-minute exposure slots, including slots without events; an unreachable high-intensity level does not gain credit. Zero active mass gives a uniform score rather than dropping an unfavourable episode.

Let y_s,k be the number of observed canonical messages of side s during minute k. If Y_s=sum y_s,k>0, d_s=sum_k(y_s,k/Y_s)*ln(p_OI,s,k/p_price,s,k). If Y_s=0, d_s is undefined, not zero. Anchor d is the arithmetic mean of its defined sides. An anchor with neither side observed remains in the journal as NO_OBSERVED_MESSAGES, not as a zero-loss win. Primary estimate is the unweighted mean of daily means of defined anchor d; message counts, day counts and all exclusions must accompany it. A side with no price movement produces no information beyond the identical path-normalized comparator.

This conditional log-score difference measures timing/concentration along an already realized path. It is NOT a price forecast, a calibrated event probability, liquidation intensity in dollars, or PnL. The proposed raw share of liquidation dollars near bands versus arbitrary unvisited random prices is not a primary statistic because it can reward price-path geometry alone.

## Controls, split, uncertainty and verdict

Primary comparator: the fixed price-only cohort map in MODEL.md, with the same historical bars, virtual thresholds, lifetime, barrier retirement and future exposure. In addition report 199 frozen-seed permutations of OI cohort masses within same-side, fixed age and distance buckets; candidate geometry and the future path are identical. Do not choose a seed or discard a bad comparator. These are placebo diagnostics, not a second family of fitted strategies.

Inventory the common eligible calendar span first, without feature/target association summaries. Fix the first 60% of whole UTC weeks as development and the remaining 40% as a single temporal validation period, with a 240m purge before validation. Freeze this split, exact dates and inventory SHA in RUN_PLAN.json before scoring. No tuning is planned even in development. Warm-up may precede the split; it is not a scored episode. If a period was previously viewed, label validation as temporal/reused-history rather than untouched OOS. A future untouched confirmation is separate.

Report overall, LONG and SHORT descriptive results, without selecting a favourable side. Primary validation requires >=8 calendar-week clusters, >=40 valid UTC days, >=100 anchors with a defined d, and >=30 event-positive anchors for each side. Also show all planned/valid/no-message/missing anchors, feed/mark/OI coverage and active/unknown proxy fractions. Do not manufacture n by counting scenarios or nested horizons as independent observations. Failure of any evidence/count gate is INCONCLUSIVE/NOT_ASSESSABLE.

For eligible validation: percentile 95% interval from 10,000 whole-UTC-week bootstrap resamples, fixed seed 20261018; retain all valid days/anchors within each sampled week and recompute the daily-weighted mean. Display number of clusters. An interval spanning zero is INCONCLUSIVE, not proof of no effect. Upper endpoint <=0 permits rejection of incremental value of this fixed proxy on this feed/period. A positive lower endpoint allows only a separately registered next test, and must be accompanied by the fixed 30m-lag sensitivity, the 199 placebos and the predeclared deletion of the three largest observed message-count anchor episodes as a fragility diagnostic. None is a trading permission or proof of CoinGlass equivalence.

Limit the study to this A0. Do not start Step B, tune leverage/width/lifetime, add aggressor filters or deploy a grid switch based on Step A. An optional future comparison to actual CoinGlass has its own frozen as-seen sample and matched timestamps; apparent similarity of a few images does not validate equivalence.

## Deliverables and audit trail

Required output: input inventory and RUN_PLAN hashes, protocol/model/code SHA, all anchor rows with exclusions, fixed cohort snapshots with active/unknown mass accounting, OI/price-only/placebo scores, daily/week aggregates, confidence interval or exact unmet gate, and a limited conclusion. No raw CoinGlass, credentials, account records, orders or bot state enter outputs. Offline code must have meaningful synthetic tests for timing, gaps, mass identity, touches before birth, equality boundaries, expiration, comparator geometry, zero evidence, permutation determinism and side/schema refusal before any real-data computation.

Primary references: https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation ; https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data ; https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/All-Market-Liquidation-Order-Streams . Reference fields describe current documentation; archived schema/provenance still require audit.
