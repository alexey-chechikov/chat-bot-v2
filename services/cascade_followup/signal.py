"""Cascade-followup signal: dataclass + TG card builder.

Variant nomenclature: side_thresholdBTC, e.g. "short_5btc". Side refers to the
liquidation side (which longs/shorts got hit). The actual TRADE direction is
derived from the variant config — short_5btc cascade → LONG fade.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CascadeFollowupVariant:
    """Per-variant config (which cascades to trade and how)."""
    variant: str
    liq_side: str
    threshold_btc: float
    trade_dir: str
    tp1_pct: float
    tp2_pct: float
    stop_pct: float
    size_usd: float
    predicted_4h_pct: float
    predicted_12h_pct: float
    backtest_wr_4h_pct: float
    backtest_n_live: int
    edge_note: str
    decision_window_sec: int = 60
    window_minutes: int = 5  # 5min for standard tier, 1min for mega tier


VARIANTS: dict[str, CascadeFollowupVariant] = {
    "short_5btc": CascadeFollowupVariant(
        variant="short_5btc",
        liq_side="short",
        threshold_btc=5.0,
        trade_dir="LONG",
        tp1_pct=+0.23,
        tp2_pct=+0.55,
        stop_pct=-0.45,
        size_usd=2500.0,
        predicted_4h_pct=+0.235,
        predicted_12h_pct=+0.227,
        backtest_wr_4h_pct=63.6,
        backtest_n_live=164,
        edge_note="Re-swept 2026-05-19 (cascade_backtest_combined, n=164 combined 2024 hist+2026 live): 4h WR 63.6% mean +0.235%, 12h WR 60.0% mean +0.227%. Live alert-dedup subset (cascade_edge_drift n=52): 57.7%. Half-size $2500 — edge ниже изначального 70.8% оценки.",
        window_minutes=5,
    ),
    "mega_short_10btc": CascadeFollowupVariant(
        variant="mega_short_10btc",
        liq_side="short",
        threshold_btc=10.0,
        trade_dir="LONG",
        tp1_pct=+0.20,
        tp2_pct=+0.50,
        stop_pct=-0.45,
        size_usd=3000.0,
        predicted_4h_pct=+0.112,
        predicted_12h_pct=+0.239,
        backtest_wr_4h_pct=61.1,
        backtest_n_live=75,
        edge_note="Re-swept 2026-05-19 (n=75): 4h WR 61.1% mean +0.112%, 12h WR 56.8% +0.239%, 24h WR 48.5% (coin-flip — hold ≤12h). Alert-dedup subset (cascade_accuracy n=11) показывает 81.8% — но малая выборка. Conservative size $3000.",
        window_minutes=1,
    ),
}


@dataclass
class CascadeFollowupSignal:
    signal_id: str
    ts_signal: str
    variant: str
    liq_side: str
    threshold_btc: float
    qty_btc: float
    last_price: float
    trade_dir: str
    entry: float
    tp1: float
    tp2: float
    stop: float
    size_usd: float
    size_btc: float
    predicted_4h_pct: float
    edge_drift_flag: bool = False
    by_exchange: dict = field(default_factory=dict)


def signal_id_from_ts(ts: datetime, variant: str) -> str:
    return f"cf_{ts.strftime('%Y%m%d_%H%M%S')}_{variant}"


def build_signal(*, variant: str, qty_btc: float, last_price: float,
                  by_exchange: Optional[dict] = None,
                  edge_drift_flag: bool = False,
                  now: Optional[datetime] = None) -> CascadeFollowupSignal:
    if now is None:
        now = datetime.now(timezone.utc)
    v = VARIANTS[variant]
    entry = float(last_price)
    tp1 = entry * (1 + v.tp1_pct / 100)
    tp2 = entry * (1 + v.tp2_pct / 100)
    stop = entry * (1 + v.stop_pct / 100)
    size_btc = v.size_usd / entry if entry > 0 else 0.0
    return CascadeFollowupSignal(
        signal_id=signal_id_from_ts(now, variant),
        ts_signal=now.isoformat(timespec="seconds"),
        variant=variant,
        liq_side=v.liq_side,
        threshold_btc=v.threshold_btc,
        qty_btc=float(qty_btc),
        last_price=entry,
        trade_dir=v.trade_dir,
        entry=entry,
        tp1=tp1,
        tp2=tp2,
        stop=stop,
        size_usd=v.size_usd,
        size_btc=size_btc,
        predicted_4h_pct=v.predicted_4h_pct,
        edge_drift_flag=edge_drift_flag,
        by_exchange=dict(by_exchange or {}),
    )


def format_tg_card(s: CascadeFollowupSignal) -> str:
    v = VARIANTS[s.variant]
    rr2 = abs(v.tp2_pct) / abs(v.stop_pct) if v.stop_pct else 0
    lines = [
        f"⚡ CASCADE-FOLLOWUP — {s.variant.upper()}",
        "",
        f"Тип: {s.liq_side.upper()}-cascade  ({s.qty_btc:.2f} BTC за 5 мин)",
        f"Trade direction: {s.trade_dir} (fade cascade)",
        f"Predicted 4h: {v.predicted_4h_pct:+.2f}%   |   WR backtest: {v.backtest_wr_4h_pct:.1f}% (n={v.backtest_n_live})",
        "",
        "💰 ПЛАН ВХОДА:",
        f"  Размер: ${v.size_usd:,.0f}  (≈{s.size_btc:.4f} BTC)",
        f"  Entry:  ~${s.entry:,.0f}",
        f"  Stop:   ${s.stop:,.0f}  ({v.stop_pct:+.2f}%)",
        f"  TP1:    ${s.tp1:,.0f}  ({v.tp1_pct:+.2f}%)",
        f"  TP2:    ${s.tp2:,.0f}  ({v.tp2_pct:+.2f}%, R:R 1:{rr2:.1f})",
        "",
        f"ℹ {v.edge_note}",
        "",
        f"⏱ Решение ≤{v.decision_window_sec}с — после latency edge горит.",
    ]
    if s.edge_drift_flag:
        lines.insert(1, "⚠ EDGE-DRIFT FLAG: live divergence detected, half-size.")
    if s.by_exchange:
        contribs = [(e, sides.get(s.liq_side, 0.0)) for e, sides in s.by_exchange.items()]
        contribs = [(e, q) for e, q in contribs if q >= 0.3]
        if len(contribs) >= 2:
            lines.append("📡 Cross-exchange: " + ", ".join(f"{e}={q:.1f}" for e, q in contribs))
    return "\n".join(lines)
