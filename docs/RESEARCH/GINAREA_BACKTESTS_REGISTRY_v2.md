# GinArea Backtests Registry — v2 (Dynamic Grid era, июнь–июль 2026)

**Status:** REGISTRY — continuation of [GINAREA_BACKTESTS_REGISTRY_v1.md](GINAREA_BACKTESTS_REGISTRY_v1.md) (BT-001…017).
**Date:** 2026-07-18
**Source:** Operator-collected GinArea platform backtest results, transcribed from screenshots across the June–July 2026 Dynamic Grid sessions (Win-side chat).
**Method:** Pure structuring — **no recompute, no synthesis, no winner-picking.** Numbers are as-reported by the GinArea UI.
**Purpose:** Give Mac the raw config→result data so he can **independently** re-analyze, attempt to reproduce, and draw his own conclusions. Win's *interpretation* lives separately in [../CONTEXT/HANDOFF_MAC_DYNAMIC_GRID_2026-06-29.md](../CONTEXT/HANDOFF_MAC_DYNAMIC_GRID_2026-06-29.md) — read it AFTER forming your own view, or ignore it.

⚠️ **Transcription caveat (same as v1):** these are Win's transcriptions of operator screenshots. Small risk of typos in GinArea IDs / PnL signs. Cross-check against originals before decision-grade use. Where Win holds only an aggregate (not a per-run ID), it's marked.

---

## §0 Two canonical windows (all Dynamic Grid runs use one of these)

- **BASE** = `2026-02-05 → 2026-05-05` (3 mo, BTC ~drift up / range) — the tuning window.
- **FORWARD** = `2026-05-10 → 2026-06-28` (49 d, out-of-sample): BTC 70k→52k crash 06.06 → bounce 60k (**round-trip**, avg entry above close); ETH −34% capitulation to ~1500 + bounce.

The whole point of the split: BASE is where configs are fit, FORWARD is the honest out-of-sample stress. Several configs that look best on BASE are catastrophic on FORWARD (see BT-025 vs BT-029/030).

---

## §1 Master table — BTC Dynamic Grid, exit-at-average целевой sweep

**Constant across BT-018…031** (unless noted): BITMEX, BTCUSDT, USDT_FUTURES, DYNAMIC GRID, Auto direction,
base-offset 0.4, dyn-offset 0.05, **step 0.3**, order_count 200, order_size 0.005, **max_size 0.02**, mult 1.1,
min_stop 0.006, max_stop 0.02, %-mode ON, **«Выход по средней цене» (exit-at-average) ON**, TP off, SL off.
**Swept variable: `целевой` (target profit level) only** → clean A/B ladder.

| BT-ID | Window | GinArea ID | целевой | Realized PnL | Volume | Note |
|-------|--------|------------|--------:|-------------:|-------:|------|
| BT-018 | BASE | 5578561813 | 0.31 | +$2426.07 | $1,925,068 | |
| BT-019 | BASE | 6287789295 | 0.33 | +$2553.20 | $1,900,525 | |
| BT-020 | BASE | 6169958256 | 0.39 | +$2983.06 | $1,760,546 | |
| BT-021 | BASE | 5922781456 | 0.41 | +$3093.92 | $1,748,198 | P&L-trail ON on this run |
| BT-022 | BASE | 4335564660 | 0.44 | +$3325.84 | $1,727,734 | |
| BT-023 | BASE | 4390474049 | 0.49 | +$3612.96 | $1,653,269 | |
| BT-024 | BASE | 5560273419 | 0.59 | +$4023 | n/a | |
| BT-025 | BASE | 5852568381 | 0.67 | +$4529 | n/a | **best on BASE** — but see BT-029 (same целевой, FORWARD = catastrophe) |
| BT-026 | FORWARD | 6394032443 | 0.44 | +$921.70 | $501,158 | |
| BT-027 | FORWARD | 4791676836 | 0.49 | +$1072.05 | $489,926 | |
| BT-028 | FORWARD | 4885002346 | 0.55 | +$1185 | n/a | Win's "champion" pick |
| BT-029 | FORWARD | 5234319055 | 0.67 | **−$9269** | n/a | exit-at-average failed to flush; bag stuck ~1.5 BTC |
| BT-030 | FORWARD | 4597508371 | 0.69 | **−$9287** | n/a | same failure mode |

**Reported transient bag (unrealized low) for the ON-champion family on FORWARD: ~−$10,000** at the 06–07.06 bottom, before flush. Operator-reported, not per-BT-ID isolated.

---

## §2 BTC — exit-at-average toggle + step + overlay (mixed configs, NOT single-variable)

| BT-ID | Window | GinArea ID | Config delta vs §1 | Realized PnL | Note |
|-------|--------|------------|--------------------|-------------:|------|
| BT-031 | FORWARD | 5596670074 | **exit-at-average OFF**, max 0.02, целевой 0.49 | **−$8490** | bag stuck 1.28 BTC (vs ON → positive) |
| BT-032a | BASE | 5255793078 | exit-avg ON, **max 0.03**, целевой 0.49 | +$3736 | |
| BT-032b | FORWARD | 5593065911 | exit-avg ON, **max 0.03**, целевой 0.49 | +$1267 | transient bag dipped ~−$16,000 before flush (max 0.03 vs 0.02) |
| BT-033 | FORWARD | 5629177868 / 4377098744 | exit-avg ON, **step 0.2** (tighter) | ~+$1065 | transient bag ~−$16,000 (bag ×2 to ~2.0 BTC) — Win holds 2 IDs, aggregate |
| BT-034 | FORWARD | 5616369758 | **INDICATOR GRID SHORT** overlay (not symmetric DG) | +$1158 | directional short leg on the down-window |

**Uncontrolled-variable warning:** BT-031…034 each change more than one knob vs the §1 baseline (toggle, max-size, step, or strategy). They are directional readings, not clean single-variable A/B. Reproduce with care.

---

## §3 ETH Dynamic Grid (exit-at-average)

**Constant:** BITMEX, ETHUSDT, USDT_FUTURES, DYNAMIC GRID, base-offset 0.5, dyn 0.1, **step 0.1**, order_count 200,
order_size 0.01, **max_size 0.1**, mult 1.1, **целевой 0.89**, **TP 89**, %-mode ON, **exit-at-average ON**.

| BT-ID | Window | GinArea ID | Realized PnL | Reported transient bag |
|-------|--------|------------|-------------:|------------------------|
| BT-035 | BASE | 5375339018 | +$1920 | bag ~0.08 ETH, flat |
| BT-036 | FORWARD | 5018178002 | +$750 | trough ~−$800 (peak bag ~6 ETH) |

ETH note: same exit-at-average mechanism as BTC, but the transient trough is ~−$800 vs BTC's ~−$10,000 — the ETH bag notional is far smaller (~6 ETH ≈ $9k vs BTC 1.2 ≈ $84k).

---

## §4 Directional champions (config-level, from earlier research — for context, not per-run IDs)

These are locked configs from separate sweeps (pre-Dynamic-Grid), included so Mac has the full book. Not individual GinArea runs — summary configs from the Win-side research memory.

| Leg | Contract | Entry | grid_step | mult | целевой | TP | max | Notes |
|-----|----------|-------|-----------|------|---------|----|----|-------|
| SHORT BTC | inverse (live cascade T2=6287583200) | >0.7% | 0.01 | 1.4 | 0.24 | 20 | 0.003 | +$5–6k/2y, DD −4.5…−11.5k; pump_freeze overlay |
| SHORT ETH | — | >1.4% | 0.1 | 1.3 | 0.30 | 60 | 0.05 | robust across 4 walk-forward windows, min +$1311 |
| LONG BTC | linear | — | 0.04 | 1.3 | 0.29 | off | 100 | peak ≤62k; max=100 is the risk axis |
| LONG ETH | — | <−1.4% | 0.1 | 1.3 | off | off | 0.03 | max is the risk axis; TP better off |

---

## §5 What Mac CAN and CANNOT reproduce right now (critical dependency)

- **CAN:** re-run any §1–§3 config in his own `tools/_grid_sim.py` on his 2y frozen data — the parameters are all here. Independent PnL + max-bag + symmetry, full 2y walk-forward (which the GinArea UI can't easily do).
- **CANNOT (yet):** reproduce the **exit-at-average** numbers. `tools/_grid_sim.py` (Jun-8 version) closes positions only by per-position target (line 65) or force-close/EXIT-FAST (line 79) — it does **NOT** model closing the whole bag when price crosses the weighted-average entry. Until that mechanic is added to the sim, BT-018…036 will NOT reproduce, and the mismatch would be a sim gap, not a strategy result. **This is the #1 blocker for independent verification** (see handoff Task 3). The GinArea platform engine is the ground truth; Mac's sim is the independent replica that must first be taught exit-at-average.

---

## §6 What this registry does NOT do (anti-drift, same as v1)

- No interpretation of which целевой / max / step is "best."
- No regeneration or recompute of any number.
- No synthesis of missing values (n/a stays n/a).
- No claim these are a random sample — operator-curated experiments.
- Win's read (the целевой-cliff at 0.6, the base-window trap, the champion picks) is deliberately kept OUT of this file and parked in the handoff, so Mac's analysis stays independent.

---

## §7 Provenance

- **Source:** Operator GinArea UI screenshots, June–July 2026 sessions.
- **Transcribed by:** Win-side Claude, into research memory, then exported here verbatim.
- **Verification:** not cross-checked against GinArea API (no API keys on Win box; snapshots.csv frozen 2026-05-13). Face-value per the same convention as v1.
- **Каwaeats:** exit-at-average is a GinArea platform toggle («Выход по средней цене»); its exact flush semantics (when price crosses weighted-avg entry → close whole bag flat) are inferred from behavior, not from GinArea docs. Confirm semantics before trusting any replica.
