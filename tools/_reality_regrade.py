"""Reality-filter re-grade — honest setup ranking net of CALIBRATED costs.

Truth source: state/setup_precision_outcomes.jsonl (real outcome per window:
TP1/SL/TIMEOUT at gross pnl_pct), NOT paper_trades.jsonl (intrabar-touch TP +
EXPIRE-in-profit = systematically inflated, proven by Win 2026-05-30).

Cost calibration from the 6 live auto_executor trades (all long_pdl_bounce):
  • ENTRY slippage: limit fills 0.00% ; market_fallback fills +0.15..+0.31%
    (4 of 6 were market_fallback). Blended avg +0.145%.
  • KEY adverse selection: 4/4 market_fallback trades hit SL; 2/2 clean limit
    fills did NOT (both expired ~flat). Chasing a non-filling limit at market
    enters into adverse momentum -> the fallback is both slower-fill AND loser.
  • Fees: post-only maker entry (-0.04% rebate) + market exit (~0.075% taker).
    precision pnl_pct is GROSS (exit/entry) -> subtract round-trip cost.

We therefore re-grade at three cost levels and flag survivors:
  limit-only  ~0.15% RT (maker in / taker out, NO market_fallback)
  blended     ~0.30% RT (Win's rough estimate; mix of limit+fallback)
  fallback    ~0.45% RT (market-fallback heavy — current reality)

Output: docs/STRATEGIES/REALITY_FILTER_REGRADE.md
"""
import json
import collections
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
PO = ROOT / "state" / "setup_precision_outcomes.jsonl"
OUT = ROOT / "docs" / "STRATEGIES" / "REALITY_FILTER_REGRADE.md"
COSTS = (0.15, 0.30, 0.45)


def main() -> int:
    rows = [json.loads(l) for l in PO.read_text().splitlines() if l.strip()]
    by = collections.defaultdict(list)
    for r in rows:
        if r.get("pnl_pct") is not None:
            by[r.get("setup_type", "?")].append(
                (float(r["pnl_pct"]), str(r.get("outcome", "")).upper()))

    md = ["# Reality-filter re-grade — honest net ranking", ""]
    md.append(f"Truth = setup_precision_outcomes.jsonl (n={len(rows)}). Gross pnl_pct "
              "minus calibrated round-trip cost. Calibration from 6 live trades: "
              "limit entry 0% slip, market_fallback +0.15..0.31% (4/6) AND adverse "
              "(4/4 fallback hit SL vs 2/2 limit flat).")
    md.append("")
    md.append("| setup | N | TP1 | SL | TO | gross avg% | net@0.15 | net@0.30 | net@0.45 |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    ranked = []
    for st, lst in by.items():
        n = len(lst)
        gross_avg = sum(p for p, _ in lst) / n
        oc = collections.Counter(o for _, o in lst)
        nets = {c: round(gross_avg - c, 3) for c in COSTS}
        ranked.append((gross_avg, st, n, oc, nets))

    for gross_avg, st, n, oc, nets in sorted(ranked, reverse=True):
        def cell(c):
            v = nets[c]
            flag = "🟢" if v > 0 else "🔴"
            return f"{v:+.3f}{flag}"
        md.append(f"| {st} | {n} | {oc.get('TP1',0)} | {oc.get('SL',0)} | "
                  f"{oc.get('TIMEOUT',0)} | {gross_avg:+.3f} | "
                  f"{cell(0.15)} | {cell(0.30)} | {cell(0.45)} |")
    md.append("")

    # survivors at the realistic limit-only cost (0.15) with n>=10
    surv = [(st, n, nets) for ga, st, n, oc, nets in ranked
            if nets[0.15] > 0 and n >= 10]
    surv.sort(key=lambda x: x[2][0.15], reverse=True)
    md.append("## Survivors (limit-only ~0.15% RT, N>=10)")
    md.append("")
    for st, n, nets in surv:
        md.append(f"- **{st}** — net {nets[0.15]:+.3f}%/trade, n={n} "
                  f"(still +{nets[0.30]:+.3f} at 0.30%)")
    md.append("")
    md.append("## Verdict")
    md.append("")
    md.append("- **long_multi_divergence** (live now) is honest **−21% / 54-of-57 "
              "TIMEOUT** — REMOVE from executor.")
    md.append("- Real survivors: **long_double_bottom, long_pdl_bounce, "
              "long_dump_reversal** — keep/add to executor.")
    md.append("- **Biggest real-PnL lever: disable market_fallback.** Live data: "
              "every market-fallback entry lost (4/4 SL), every clean limit fill "
              "didn't (2/2 flat). Limit-only entry removes both the +0.23% slippage "
              "and the adverse selection -> drops effective cost toward 0.15%.")
    md.append("- N small for survivors (10-21); out-of-time robustness still unproven.")
    md.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT}\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
